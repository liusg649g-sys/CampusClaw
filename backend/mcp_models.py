"""Additive MCP registry/cache, process-local connection validity, live references."""
import json
import re
import secrets
from teaching_models import ValidationError

PROCESS_EPOCH=secrets.token_hex(24)
SCHEMA='''
CREATE TABLE IF NOT EXISTS mcp_servers(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 class_id TEXT NOT NULL REFERENCES classes(id),
 server_key TEXT NOT NULL, name TEXT NOT NULL, base_url TEXT NOT NULL,
 token_blob BLOB NOT NULL,
 status TEXT NOT NULL DEFAULT 'disconnected' CHECK(status IN ('disconnected','connecting','connected','error')),
 last_discovered_at TEXT, error_summary TEXT NOT NULL DEFAULT '',
 process_epoch TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
 UNIQUE(class_id,server_key), UNIQUE(class_id,name)
);
CREATE TABLE IF NOT EXISTS mcp_tools(
 server_id INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
 class_id TEXT NOT NULL REFERENCES classes(id), name TEXT NOT NULL,
 description TEXT NOT NULL, input_schema TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 PRIMARY KEY(server_id,name)
);
'''


def connected(row):return row['status']=='connected' and row['process_epoch']==PROCESS_EPOCH


def public_server(row):
    return {**{key:row[key] for key in ('id','class_id','server_key','name','base_url','last_discovered_at')},
            'status':row['status'] if row['process_epoch']==PROCESS_EPOCH else 'disconnected',
            'connected':connected(row),'auth_token_set':bool(row['token_blob']),
            'error_summary':row['error_summary'] if row['process_epoch']==PROCESS_EPOCH else ''}


def resolve_tools(db,class_id,references,strict=False):
    """Read live cache; never infer authority from a saved skill reference alone."""
    available=[];unavailable=[]
    for reference in references:
        if reference=='knowledge_search':
            available.append({'reference':reference,'builtin':True});continue
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}@[a-z][a-z0-9_-]{0,63}',reference):
            raise ValidationError('工具引用格式无效，应为 tool@server-key')
        name,key=reference.split('@')
        row=db.execute('''SELECT t.*,s.server_key,s.status,s.process_epoch FROM mcp_tools t
            JOIN mcp_servers s ON s.id=t.server_id AND s.class_id=t.class_id
            WHERE s.class_id=? AND s.server_key=? AND t.name=?''',(class_id,key,name)).fetchone()
        if row and connected(row) and row['enabled']:
            available.append({'reference':reference,'server_id':row['server_id'],'class_id':class_id,
                              'name':name,'description':row['description'],'inputSchema':json.loads(row['input_schema'])})
        else:unavailable.append(reference)
    if strict and unavailable:raise ValidationError('MCP工具引用不可用：请确认本班服务器已连接且工具存在并启用')
    return available,unavailable
