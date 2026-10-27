"""Additive SQLite storage; existing material/account JSON remains untouched."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from teaching_models import SCHEMA as TEACHING_SCHEMA
from pathlib import Path
from runtime_paths import DATA_DIR

DB_FILE = Path(os.environ.get('CAMPUSCLAW_ASSISTANT_DB') or str(DATA_DIR/'assistant.sqlite3'))
DEFAULT_PROMPT = '你是一名耐心的课程解题辅导助手。帮助学生理解问题、分析条件、逐步形成解题思路。优先通过启发性问题、必要的概念解释及适当提示，引导学生独立思考。不要直接给出完整最终答案。遇到困难时逐步增加提示力度，但保持引导式教学。'

class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect():
    db = sqlite3.connect(DB_FILE, timeout=10, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS classes(id TEXT PRIMARY KEY,name TEXT NOT NULL,teacher TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS students(username TEXT PRIMARY KEY,name TEXT NOT NULL,password TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS members(classId TEXT REFERENCES classes(id),username TEXT REFERENCES students(username),PRIMARY KEY(classId,username));
    CREATE TABLE IF NOT EXISTS prompts(id TEXT PRIMARY KEY,classId TEXT REFERENCES classes(id),name TEXT NOT NULL,content TEXT NOT NULL,skill TEXT NOT NULL,teacher TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,student TEXT NOT NULL,classId TEXT REFERENCES classes(id),promptId TEXT,skill TEXT NOT NULL,prompt TEXT NOT NULL,createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,busy INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,conversationId TEXT REFERENCES conversations(id),role TEXT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL,sources TEXT NOT NULL DEFAULT '[]',createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    ''')
    db.executescript(TEACHING_SCHEMA)
    from mcp_models import SCHEMA as MCP_SCHEMA
    db.executescript(MCP_SCHEMA)
    from mcp_audit import SCHEMA as AUDIT_SCHEMA
    db.executescript(AUDIT_SCHEMA)
    # Add columns in place; legacy row values and primary keys are preserved.
    db.execute('BEGIN IMMEDIATE')
    try:
        additions = {
            'conversations': {'agentId': 'INTEGER', 'title': 'TEXT', 'updated_at': 'TEXT',
                              'title_initialized': 'INTEGER NOT NULL DEFAULT 0'},
            'messages': {'skill_name': 'TEXT'},
        }
        for table, columns in additions.items():
            existing = {r[1] for r in db.execute('PRAGMA table_info('+table+')')}
            for name, definition in columns.items():
                if name not in existing:
                    db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise
    return db

def password_hash(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000).hex()

def password_matches(password, stored):
    salt, digest = stored.split(':')
    return hmac.compare_digest(digest, hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000).hex())

def recover_interrupted():
    """Called once on server startup, never while requests are running."""
    with connect() as db:
        db.execute("UPDATE messages SET status='interrupted',sources='[]' WHERE status='generating'")
        db.execute('UPDATE conversations SET busy=0')

def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args).fetchall()]
