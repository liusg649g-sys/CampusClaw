"""Consistent SQLite backup plus verified copies of existing business files.

Does not import application modules, load secrets into the environment, migrate,
initialize or restore any database. Backups live under ignored temp/backups/.
"""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def configured_database():
    value=''
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('CAMPUSCLAW_ASSISTANT_DB='):
                value=line.split('=',1)[1].strip().strip('\"\'')
    path=Path(value) if value else ROOT/'backend/assistant.sqlite3'
    return path if path.is_absolute() else ROOT/path

def backup(database=None):
    database=Path(database) if database else configured_database()
    parent=ROOT/'temp/backups';parent.mkdir(parents=True,exist_ok=True)
    target=Path(tempfile.mkdtemp(prefix='lesson5-stage1-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-',dir=parent))
    manifest={'complete':False,'database_present':database.exists(),'files':{}}
    if database.exists():
        # URI mode=ro prevents accidental initialization of the source.
        with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(target/'assistant.sqlite3')) as destination:
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite backup integrity check failed')
                manifest['tables']=[r[0] for r in destination.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        manifest['database_sha256']=digest(target/'assistant.sqlite3')
    files=[ROOT/'backend'/name for name in ['teacher_account.json','materials.json','knowledge_chunks.json']]
    files+=sorted((ROOT/'backend/material_files').glob('*'))
    for file in files:
        if not file.is_file():continue
        relative=file.relative_to(ROOT)
        before=digest(file)
        destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(file,destination)
        if before!=digest(file) or before!=digest(destination):raise RuntimeError('业务文件在备份期间变化，请稍后重试；源文件未修改')
        manifest['files'][relative.as_posix()]=before
    manifest['complete']=True
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    # No account, token, key, SQL row content or .env is printed/copied.
    print('已创建并校验备份：'+str(target))
    print('备份包含原有账号数据，请仅在本机私有保管；未修改源文件或配置。')
    return target

def verify(target):
    target=Path(target)
    manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('complete'):raise RuntimeError('备份未完成，不应恢复')
    for relative,expected in manifest['files'].items():
        file=(target/relative).resolve()
        if not file.is_relative_to(target.resolve()) or digest(file)!=expected:raise RuntimeError('备份文件校验失败')
    if manifest['database_present']:
        database=target/'assistant.sqlite3'
        if digest(database)!=manifest['database_sha256']:raise RuntimeError('备份数据库摘要不一致')
        with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('备份数据库完整性校验失败')
    print('备份校验通过；未执行恢复。')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path)
    parser.add_argument('--verify',type=Path)
    arguments=parser.parse_args()
    verify(arguments.verify) if arguments.verify else backup(arguments.database)
