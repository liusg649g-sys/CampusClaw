"""Fail-closed Compose bootstrap. Secrets read only at runtime, never printed."""
import os
from pathlib import Path
import re
import sqlite3
import sys


def secret(name,required=True):
    try:value=(Path('/run/secrets')/name).read_text(encoding='utf-8').strip()
    except OSError:raise ValueError('部署secret文件不可读取') from None
    if required and not value:raise ValueError('部署必要secret为空')
    return value


def main(role):
    os.environ['CAMPUSCLAW_CONTAINER_MODE']='1'
    if role=='mcp':
        token=secret('mcp_auth_token')
        if not re.fullmatch(r'[!-~]{16,256}',token):raise ValueError('MCP专用令牌格式无效')
        os.environ['MCP_AUTH_TOKEN']=token
        target='/app/mcp-server/server.py'
    elif role=='backend':
        sys.path.insert(0,'/app/backend')
        from mcp_secrets import aes_key,unprotect
        os.environ['CAMPUSCLAW_SECRET_BACKEND']='aesgcm'
        os.environ['CAMPUSCLAW_MCP_ENCRYPTION_KEY']=secret('mcp_encryption_key')
        aes_key()
        signing=secret('token_secret');password=secret('teacher_password')
        if len(signing)<32 or len(password)<12:raise ValueError('应用签名secret或初始教师密码长度不足')
        os.environ['CAMPUSCLAW_TOKEN_SECRET']=signing
        os.environ['CAMPUSCLAW_INITIAL_TEACHER_PASSWORD']=password
        os.environ['CHAT_API_KEY']=secret('chat_api_key',False)
        os.environ['EMBEDDING_API_KEY']=secret('embedding_api_key',False)
        data=Path(os.environ.get('CAMPUSCLAW_DATA_DIR','/data'));data.mkdir(parents=True,exist_ok=True)
        dbfile=data/'assistant.sqlite3'
        if dbfile.exists():
            from contextlib import closing
            with closing(sqlite3.connect(dbfile.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='mcp_servers'").fetchone():
                    for row in db.execute('SELECT token_blob FROM mcp_servers'):unprotect(row[0])
        target='/app/backend/server.py'
    else:raise ValueError('不支持的容器入口')
    os.execv(sys.executable,[sys.executable,target])


if __name__=='__main__':
    try:main(sys.argv[1])
    except Exception:
        print('容器启动失败：请检查部署secret、加密密钥与数据卷；敏感详情已抑制。',file=sys.stderr)
        raise SystemExit(1)
