"""Offline-confirmed, consistent SQLite + hashed JSON/material archive; empty restore only."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path,PurePosixPath
import sqlite3
import tempfile
import zipfile


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def backup(data,output):
    data=Path(data).resolve();output=Path(output).resolve()
    if not data.is_dir() or output.exists() or output.is_relative_to(data):raise ValueError('备份源/目标无效，目标必须是数据目录之外的新文件')
    with tempfile.TemporaryDirectory() as temp:
        staging=Path(temp);manifest={}
        database=data/'assistant.sqlite3'
        if database.exists():
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(staging/'assistant.sqlite3')) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库完整性异常')
        for file in data.rglob('*'):
            if file.is_symlink():raise ValueError('数据目录不得包含符号链接')
            if not file.is_file() or file.name in ('assistant.sqlite3','assistant.sqlite3-wal','assistant.sqlite3-shm'):continue
            relative=file.relative_to(data);destination=staging/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            before=digest(file);destination.write_bytes(file.read_bytes())
            if digest(file)!=before or digest(destination)!=before:raise ValueError('备份期间数据变化，请停用该Compose后端后重试')
        for file in staging.rglob('*'):
            if file.is_file():manifest[file.relative_to(staging).as_posix()]=digest(file)
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in manifest:archive.write(staging/relative,relative)
            archive.writestr('backup-manifest.json',json.dumps(manifest))


def restore(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):raise ValueError('只允许恢复到空目录/新卷，不覆盖现有业务数据')
    with zipfile.ZipFile(archive) as source:
        manifest=json.loads(source.read('backup-manifest.json'))
        if set(source.namelist())!=set(manifest)|{'backup-manifest.json'}:raise ValueError('归档内容不匹配')
        for relative,expected in manifest.items():
            path=PurePosixPath(relative)
            if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in relative or ':' in relative:raise ValueError('归档路径不安全')
            if hashlib.sha256(source.read(relative)).hexdigest()!=expected:raise ValueError('备份摘要不匹配')
        destination.mkdir(parents=True,exist_ok=True)
        for relative in manifest:
            file=destination/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(source.read(relative))
    database=destination/'assistant.sqlite3'
    if database.exists():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('恢复数据库完整性校验失败')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['backup','restore']);parser.add_argument('--data',required=True,type=Path);parser.add_argument('--archive',required=True,type=Path);parser.add_argument('--offline-confirmed',action='store_true')
    args=parser.parse_args()
    if not args.offline_confirmed:parser.error('必须先停止当前Compose项目后端并明确--offline-confirmed')
    try:
        backup(args.data,args.archive) if args.action=='backup' else restore(args.archive,args.data)
        print('备份/恢复及校验完成；未显示业务内容。')
    except Exception:parser.exit(1,'备份/恢复失败：检查空目标、归档完整性及离线条件；不会自动删除数据。\n')
