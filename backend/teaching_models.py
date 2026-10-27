"""Stage-one agent configuration. No chat/model requests or legacy migrations."""
import json
import re
from pathlib import Path

DEFAULT_AGENT_PROMPT = '你是一名耐心的课程学习助手，请结合可用资料帮助学生理解问题。'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS skills(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 class_id TEXT NOT NULL REFERENCES classes(id),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 32),
 trigger_text TEXT NOT NULL CHECK(length(trigger_text) BETWEEN 1 AND 120),
 description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 2000),
 tools_json TEXT NOT NULL, source_text TEXT NOT NULL CHECK(length(source_text)<=8000),
 subject_text TEXT NOT NULL DEFAULT '' CHECK(length(subject_text)<=32),
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), seed_key TEXT,
 UNIQUE(class_id,name), UNIQUE(class_id,seed_key)
);
CREATE TABLE IF NOT EXISTS tutor_agents(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 class_id TEXT NOT NULL REFERENCES classes(id),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 64),
 prompt TEXT NOT NULL DEFAULT '' CHECK(length(prompt)<=2000),
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 UNIQUE(class_id,name)
);
CREATE TABLE IF NOT EXISTS tutor_agent_skills(
 agent_id INTEGER NOT NULL REFERENCES tutor_agents(id) ON DELETE CASCADE,
 skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
 PRIMARY KEY(agent_id,skill_id)
);
CREATE TABLE IF NOT EXISTS tutor_agent_materials(
 agent_id INTEGER NOT NULL REFERENCES tutor_agents(id) ON DELETE CASCADE,
 material_id TEXT NOT NULL,
 PRIMARY KEY(agent_id,material_id)
);
'''


class ValidationError(ValueError):
    pass


def validate_tools(value, allow_mcp=True):
    """Syntax first; class/cache authority is checked inside the save transaction."""
    tools = [part.strip() for part in re.split(r'[,，、;；|]+', value) if part.strip()]
    if len(tools)>32:raise ValidationError('每个技能最多绑定32个工具')
    for tool in tools:
        if tool=='knowledge_search':continue
        if not allow_mcp:raise ValidationError('当前解析模式只允许工具 knowledge_search')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}@[a-z][a-z0-9_-]{0,63}',tool):raise ValidationError('工具引用格式无效，应为 tool@server-key')
    if allow_mcp and len(set(tools))!=len(tools):raise ValidationError('同一技能不能重复绑定工具')
    return list(dict.fromkeys(tools))


def parse_skill(source, allow_mcp=True):
    if not isinstance(source, str) or not source.strip() or len(source) > 8000:
        raise ValidationError('技能文件不能为空且不能超过8000字')
    lines = source.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    fields, body_start = {}, None
    allowed = {'名称', '适用条件', '资料', '工具', '启用'}
    for index, line in enumerate(lines):
        text = line.strip()
        if not text:
            if fields:
                body_start = index + 1
                break
            continue
        if text.startswith('#'):
            continue
        pair = re.split(r'[:：]', text, maxsplit=1)
        if len(pair) != 2 or pair[0].strip() not in allowed:
            raise ValidationError('技能元数据存在非法字段或缺少冒号')
        key, value = pair[0].strip(), pair[1].strip()
        if key in fields:
            raise ValidationError('技能字段重复：' + key)
        fields[key] = value
    for key in ('名称', '适用条件', '启用'):
        if not fields.get(key):
            raise ValidationError('技能缺少必填字段：' + key)
    if fields['启用'] not in ('是', '否'):
        raise ValidationError('启用字段只能为“是”或“否”')
    description = '\n'.join(lines[body_start:]).strip() if body_start is not None else ''
    if not description:
        raise ValidationError('技能元数据之后必须有空行及说明正文')
    for key, limit in [('名称', 32), ('适用条件', 120), ('资料', 32)]:
        if len(fields.get(key, '')) > limit:
            raise ValidationError('%s不能超过%s字' % (key, limit))
    if len(description) > 2000:
        raise ValidationError('技能说明正文不能超过2000字')
    tools = validate_tools(fields.get('工具', ''),allow_mcp)
    return dict(name=fields['名称'], trigger_text=fields['适用条件'],
                subject_text=fields.get('资料', ''), description=description,
                tools_json=json.dumps(tools), source_text=source,
                enabled=int(fields['启用'] == '是'))


def set_skill_enabled(source, enabled):
    """Keep parsed columns and editable source in agreement when using the switch."""
    parse_skill(source,allow_mcp=True)
    lines = source.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    for i, line in enumerate(lines):
        if re.match(r'^\s*启用\s*[:：]', line):
            lines[i] = '启用：' + ('是' if enabled else '否')
            break
    return '\n'.join(lines)


def effective_agent_prompt(agent):
    return agent['prompt'].strip() or DEFAULT_AGENT_PROMPT


def route_skill(db, agent_id, class_id, question):
    """Read live bindings; choose one enabled skill, lexical score then numeric ID."""
    candidates = db.execute('''SELECT s.* FROM skills s
        JOIN tutor_agent_skills b ON b.skill_id=s.id
        JOIN tutor_agents a ON a.id=b.agent_id
        WHERE a.id=? AND a.class_id=? AND s.class_id=a.class_id AND s.enabled=1
        ORDER BY s.id''', (agent_id, class_id)).fetchall()
    selected, highest = None, 0
    question = str(question).casefold()
    for row in candidates:
        words = [part.strip().casefold() for part in re.split(r'[,，、;；|]+', row['trigger_text']) if part.strip()]
        score = sum(word in question for word in words)
        if score > highest:
            selected, highest = dict(row), score
    return selected


def valid_material_ids(materials, class_id, files_dir):
    """JSON is authoritative; a missing/moved file never grants permission."""
    root = Path(files_dir).resolve()
    valid = set()
    for item in materials:
        if item.get('classId') != class_id or not isinstance(item.get('id'), str):
            continue
        stored = item.get('storedName', '')
        if not isinstance(stored, str) or not stored or Path(stored).name != stored:
            continue
        path = (root / stored).resolve()
        if path.is_relative_to(root) and path.is_file():
            valid.add(item['id'])
    return valid


def allowed_material_ids(db, agent_id, class_id, materials, files_dir):
    """Caller supplies a fresh JSON snapshot and an already-authorized class ID.

    No cached grant: every use intersects live bindings with live JSON/file state.
    Agent enabled is deliberately not tested here: future existing conversations
    may continue after an agent is disabled, as required by the course.
    """
    rows = db.execute('''SELECT b.material_id FROM tutor_agent_materials b
        JOIN tutor_agents a ON a.id=b.agent_id WHERE a.id=? AND a.class_id=?''',
        (agent_id, class_id)).fetchall()
    return {row[0] for row in rows} & valid_material_ids(materials, class_id, files_dir)
