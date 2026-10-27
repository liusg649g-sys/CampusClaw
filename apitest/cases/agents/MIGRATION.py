from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import assistant_store as store

class AdditiveSchemaTests(unittest.TestCase):
    def test_old_database_is_extended_without_rewriting_legacy_schema_or_rows(self):
        legacy='''
        CREATE TABLE classes(id TEXT PRIMARY KEY,name TEXT NOT NULL,teacher TEXT NOT NULL);
        CREATE TABLE students(username TEXT PRIMARY KEY,name TEXT NOT NULL,password TEXT NOT NULL);
        CREATE TABLE members(classId TEXT REFERENCES classes(id),username TEXT REFERENCES students(username),PRIMARY KEY(classId,username));
        CREATE TABLE prompts(id TEXT PRIMARY KEY,classId TEXT REFERENCES classes(id),name TEXT NOT NULL,content TEXT NOT NULL,skill TEXT NOT NULL,teacher TEXT NOT NULL);
        CREATE TABLE conversations(id TEXT PRIMARY KEY,student TEXT NOT NULL,classId TEXT REFERENCES classes(id),promptId TEXT,skill TEXT NOT NULL,prompt TEXT NOT NULL,createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,busy INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,conversationId TEXT REFERENCES conversations(id),role TEXT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL,sources TEXT NOT NULL DEFAULT '[]',createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO classes VALUES('old-class','原有班级','teacher');
        INSERT INTO students VALUES('old-student','原有学生','fixture-hash');
        INSERT INTO members VALUES('old-class','old-student');
        INSERT INTO prompts VALUES('old-prompt','old-class','旧提示词','原文','解题引导','teacher');
        INSERT INTO conversations(id,student,classId,promptId,skill,prompt) VALUES('old-chat','old-student','old-class','old-prompt','解题引导','旧快照');
        INSERT INTO messages(conversationId,role,content,status) VALUES('old-chat','user','已有消息','complete');
        '''
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'legacy.sqlite3'
            with closing(sqlite3.connect(file)) as db:
                db.executescript(legacy)
                schema=dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
                rows={name:list(db.execute('SELECT * FROM '+name)) for name in schema}
            with patch.object(store,'DB_FILE',file):
                for _ in range(3):
                    with store.connect() as db:pass
                with store.connect() as db:
                    for name,sql in schema.items():
                        self.assertTrue(db.execute("SELECT sql FROM sqlite_master WHERE name=?",(name,)).fetchone()[0].startswith(sql[:-1]))
                        self.assertEqual([tuple(r)[:len(rows[name][0])] for r in db.execute('SELECT * FROM '+name)] if rows[name] else [],rows[name])
                    for name in ['tutor_agents','skills','tutor_agent_skills','tutor_agent_materials']:
                        self.assertEqual(db.execute('SELECT count(*) FROM '+name).fetchone()[0],0)
