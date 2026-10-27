"""Minimal immutable identity and bounded audit metadata; never arguments/results."""
from datetime import datetime,timezone
import hashlib
import hmac
import secrets
import sqlite3
from ai_gateway import AIGatewayError

HASH_KEY=secrets.token_bytes(32)
SCHEMA='''CREATE TABLE IF NOT EXISTS mcp_tool_calls(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 class_id TEXT NOT NULL, user_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
 message_id INTEGER NOT NULL, server_id INTEGER, server_name TEXT NOT NULL,
 tool_name TEXT NOT NULL, tool_ref TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ok','denied','error')),
 round INTEGER NOT NULL, started_at TEXT NOT NULL, duration_ms INTEGER NOT NULL DEFAULT 0,
 error_summary TEXT NOT NULL DEFAULT '', arguments_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mcp_calls_class_id ON mcp_tool_calls(class_id,id);
'''


class AuditError(AIGatewayError):pass


def begin(db,conversation,message_id,target,raw,round_number):
    digest=hmac.new(HASH_KEY,str(raw).encode('utf-8'),hashlib.sha256).hexdigest()
    try:
        ident=db.execute('''INSERT INTO mcp_tool_calls(class_id,user_id,conversation_id,message_id,
            server_id,server_name,tool_name,tool_ref,status,round,started_at,error_summary,arguments_hash)
            VALUES(?,?,?,?,?,?,?,?,'error',?,?,'调用未完成',?)''',(
                conversation['classId'],conversation['student'],conversation['id'],message_id,
                target.get('server_id'),target.get('server_key',''),target.get('name','unknown'),target.get('reference','unrecognized'),
                round_number,datetime.now(timezone.utc).isoformat(),digest)).lastrowid
        db.commit();return ident
    except sqlite3.Error:db.rollback();raise AuditError('工具审计写入失败，已停止执行',503) from None


def finish(db,ident,status,summary,duration):
    try:
        if db.execute("UPDATE mcp_tool_calls SET status=?,error_summary=?,duration_ms=? WHERE id=? AND status='error' AND error_summary='调用未完成'",(status,summary,int(duration*1000),ident)).rowcount!=1:raise sqlite3.IntegrityError()
        db.commit()
    except sqlite3.Error:db.rollback();raise AuditError('工具审计完成状态写入失败，回答已终止',503) from None
