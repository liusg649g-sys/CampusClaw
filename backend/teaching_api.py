"""Agent/skill configuration endpoints, separate from legacy prompt chat."""
import json
import re
import sqlite3
from urllib.parse import urlparse, parse_qs
import assistant_store as store
from teaching_models import (ValidationError, parse_skill, set_skill_enabled,
                             effective_agent_prompt, allowed_material_ids,
                             valid_material_ids)


class ManagementError(Exception):
    def __init__(self, message='资源不存在', status=404):
        super().__init__(message)
        self.status = status


class TeachingMixin:
    def teaching_route(self, method):
        parsed = urlparse(self.path)
        match = re.fullmatch(r'/(agents|teaching-skills)(?:/([^/]+))?(?:/(bindings))?', parsed.path)
        if not match:
            return False
        if not self.require_login():
            return True
        try:
            if method != 'GET' and self.auth_payload['role'] != 'teacher':
                raise ManagementError('仅教师可操作', 403)
            data = self.read_json() if method in ('POST', 'PUT') else {}
            with store.connect() as db:
                self.teaching_dispatch(db, method, match.groups(), parse_qs(parsed.query), data)
        except ManagementError as error:
            self.send_json({'success': False, 'message': str(error)}, error.status)
        except (ValidationError, ValueError, TypeError) as error:
            message = str(error) if isinstance(error, ValidationError) else '请求体或参数格式错误'
            self.send_json({'success': False, 'message': message}, 400)
        except sqlite3.IntegrityError:
            self.send_json({'success': False, 'message': '名称在本班已存在，或绑定数据无效'}, 400)
        return True

    def teaching_class(self, db, class_id):
        if not isinstance(class_id, str) or not class_id.strip():
            raise ValidationError('请先选择已创建或导入的服务端班级')
        user = self.auth_payload
        if user['role'] == 'teacher':
            allowed = db.execute('SELECT 1 FROM classes WHERE id=? AND teacher=?',
                                 (class_id, user['sub'])).fetchone()
        else:
            allowed = db.execute('SELECT 1 FROM members WHERE classId=? AND username=?',
                                 (class_id, user['sub'])).fetchone()
        if not allowed:
            raise ManagementError()
        return class_id

    def teaching_item(self, db, kind, identifier):
        if not identifier or not identifier.isascii() or not identifier.isdigit() or len(identifier)>19 or int(identifier)>9223372036854775807:
            raise ManagementError()
        table = 'tutor_agents' if kind == 'agents' else 'skills'
        row = db.execute('SELECT * FROM '+table+' WHERE id=?', (int(identifier),)).fetchone()
        if not row:
            raise ManagementError()
        self.teaching_class(db, row['class_id'])
        if kind == 'agents' and self.auth_payload['role'] == 'student' and not row['enabled']:
            raise ManagementError()
        return dict(row)

    def teaching_skill_public(self, row, db=None):
        result = dict(row)
        result['enabled'] = bool(result['enabled'])
        result['tools'] = json.loads(result['tools_json'])
        if db is not None:
            from mcp_models import resolve_tools
            available, unavailable=resolve_tools(db,row['class_id'],result['tools'])
            result['available_tools']=[t['reference'] for t in available]
            result['unavailable_tools']=unavailable
        return result

    def teaching_agent_public(self, db, row):
        result = dict(row)
        result['enabled'] = bool(result['enabled'])
        result['effective_prompt'] = effective_agent_prompt(result)
        result['skill_ids'] = [r[0] for r in db.execute('''SELECT s.id FROM skills s
            JOIN tutor_agent_skills b ON b.skill_id=s.id
            WHERE b.agent_id=? AND s.class_id=? ORDER BY s.id''', (row['id'], row['class_id']))]
        materials, files_dir = self.teaching_material_source()
        result['material_ids'] = sorted(allowed_material_ids(db, row['id'], row['class_id'], materials, files_dir))
        return result

    def teaching_bindings(self, db, class_id, data):
        skill_ids, material_ids = data.get('skill_ids'), data.get('material_ids')
        if not isinstance(skill_ids, list) or len(skill_ids) > 1000 or any(type(v) is not int or v <= 0 or v>9223372036854775807 for v in skill_ids):
            raise ValidationError('skill_ids 必须是正整数数组（最多1000项）')
        if not isinstance(material_ids, list) or len(material_ids) > 1000 or any(not isinstance(v, str) or not v or len(v)>200 for v in material_ids):
            raise ValidationError('material_ids 必须是原材料ID字符串数组（最多1000项）')
        skill_ids, material_ids = set(skill_ids), set(material_ids)
        for ident in skill_ids:
            if not db.execute('SELECT 1 FROM skills WHERE id=? AND class_id=?', (ident, class_id)).fetchone():
                raise ManagementError()
        materials, files_dir = self.teaching_material_source()
        if not material_ids.issubset(valid_material_ids(materials, class_id, files_dir)):
            raise ManagementError()
        return sorted(skill_ids), sorted(material_ids)

    def teaching_replace_bindings(self, db, agent_id, skill_ids, material_ids):
        db.execute('DELETE FROM tutor_agent_skills WHERE agent_id=?', (agent_id,))
        db.execute('DELETE FROM tutor_agent_materials WHERE agent_id=?', (agent_id,))
        db.executemany('INSERT INTO tutor_agent_skills VALUES(?,?)', [(agent_id, ident) for ident in skill_ids])
        db.executemany('INSERT INTO tutor_agent_materials VALUES(?,?)', [(agent_id, ident) for ident in material_ids])

    def teaching_dispatch(self, db, method, parts, query, data):
        kind, identifier, suffix = parts
        if suffix and (kind != 'agents' or not identifier):
            raise ManagementError()
        if identifier:
            item = self.teaching_item(db, kind, identifier)
            class_id = item['class_id']
        else:
            class_id = data.get('classId') if method == 'POST' else (query.get('classId') or [''])[0]
            self.teaching_class(db, class_id)
            item = None
        if method == 'GET':
            if kind == 'agents':
                if item:
                    payload = self.teaching_agent_public(db, item)
                    return self.send_json({'success': True, 'agent': payload})
                condition = ' AND enabled=1' if self.auth_payload['role'] == 'student' else ''
                rows = db.execute('SELECT * FROM tutor_agents WHERE class_id=?'+condition+' ORDER BY id', (class_id,)).fetchall()
                return self.send_json({'success': True, 'agents': [self.teaching_agent_public(db, dict(r)) for r in rows]})
            if item:
                return self.send_json({'success': True, 'skill': self.teaching_skill_public(item,db)})
            rows = db.execute('SELECT * FROM skills WHERE class_id=? ORDER BY id', (class_id,)).fetchall()
            return self.send_json({'success': True, 'skills': [self.teaching_skill_public(r,db) for r in rows]})
        if method == 'DELETE' and item and not suffix:
            table = 'tutor_agents' if kind == 'agents' else 'skills'
            db.execute('DELETE FROM '+table+' WHERE id=?', (item['id'],))
            db.commit()
            return self.send_json({'success': True})
        if kind == 'agents' and method in ('POST', 'PUT'):
            if (method == 'POST' and item) or (method == 'PUT' and not item):
                raise ManagementError('方法不允许', 405)
            if suffix:
                if method != 'PUT':
                    raise ManagementError('方法不允许', 405)
                skill_ids, material_ids = self.teaching_bindings(db, class_id, data)
                self.teaching_replace_bindings(db, item['id'], skill_ids, material_ids)
            else:
                name, prompt, enabled = data.get('name'), data.get('prompt', ''), data.get('enabled', True)
                if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
                    raise ValidationError('智能体名称不能为空且不能超过64字')
                if not isinstance(prompt, str) or len(prompt) > 2000:
                    raise ValidationError('角色提示词不能超过2000字，允许为空')
                if type(enabled) is not bool:
                    raise ValidationError('enabled 必须是布尔值')
                # Validate every binding before writing anything, then replace in
                # the same transaction as the agent itself.
                skill_ids, material_ids = self.teaching_bindings(db, class_id, data)
                if item:
                    db.execute('UPDATE tutor_agents SET name=?,prompt=?,enabled=? WHERE id=?',
                               (name.strip(), prompt, int(enabled), item['id']))
                else:
                    ident = db.execute('INSERT INTO tutor_agents(class_id,name,prompt,enabled) VALUES(?,?,?,?)',
                                       (class_id, name.strip(), prompt, int(enabled))).lastrowid
                    item = {'id': ident, 'class_id': class_id}
                self.teaching_replace_bindings(db, item['id'], skill_ids, material_ids)
            db.commit()
            row = dict(db.execute('SELECT * FROM tutor_agents WHERE id=?', (item['id'],)).fetchone())
            return self.send_json({'success': True, 'id': row['id'], 'agent': self.teaching_agent_public(db, row)}, 201 if method=='POST' else 200)
        if kind == 'teaching-skills' and not suffix and method in ('POST', 'PUT'):
            if (method == 'POST' and item) or (method == 'PUT' and not item):
                raise ManagementError('方法不允许', 405)
            source = data.get('source')
            if 'enabled' in data:
                if not item or type(data['enabled']) is not bool or 'source' in data:
                    raise ValidationError('启停操作仅提交布尔 enabled；编辑操作提交 source')
                source = set_skill_enabled(item['source_text'], data['enabled'])
            values = parse_skill(source,allow_mcp=True)
            from mcp_models import resolve_tools
            db.execute('BEGIN IMMEDIATE')
            resolve_tools(db,class_id,json.loads(values['tools_json']),strict=True)
            keys = ['name','trigger_text','description','tools_json','source_text','subject_text','enabled']
            if item:
                db.execute('UPDATE skills SET '+','.join(k+'=?' for k in keys)+' WHERE id=?',
                           tuple(values[k] for k in keys)+(item['id'],))
                ident = item['id']
            else:
                ident = db.execute('INSERT INTO skills(class_id,'+','.join(keys)+') VALUES('+','.join('?' for _ in range(8))+')',
                                   (class_id,)+tuple(values[k] for k in keys)).lastrowid
            db.commit()
            row = db.execute('SELECT * FROM skills WHERE id=?', (ident,)).fetchone()
            return self.send_json({'success': True, 'id': ident, 'skill': self.teaching_skill_public(row,db)}, 201 if method=='POST' else 200)
        raise ManagementError('方法不允许', 405)
