"""Offline AES-GCM key rotation with verified SQLite backup and transactional rewrite."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from mcp_secrets import aes_key,aes_encrypt,aes_decrypt


def rotate(database,backup,old_key,new_key):
    database=Path(database).resolve();backup=Path(backup).resolve()
    if backup.exists() or database==backup:raise ValueError('需要新的备份目标')
    with closing(sqlite3.connect(database.as_uri()+'?mode=rw',uri=True)) as db:
        rows=list(db.execute('SELECT id,token_blob FROM mcp_servers'))
        plain=[(ident,aes_decrypt(bytes(blob),aes_key(old_key))) for ident,blob in rows]
        with closing(sqlite3.connect(backup)) as copy:
            db.backup(copy)
            if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('备份校验失败')
        try:
            db.execute('BEGIN IMMEDIATE')
            for ident,token in plain:
                cipher=aes_encrypt(token,aes_key(new_key))
                if aes_decrypt(cipher,aes_key(new_key))!=token:raise ValueError('轮换验证失败')
                db.execute('UPDATE mcp_servers SET token_blob=?,status=\'disconnected\',process_epoch=\'\',revision=revision+1 WHERE id=?',(cipher,ident))
                db.execute('DELETE FROM mcp_tools WHERE server_id=?',(ident,))
            db.commit()
        except Exception:db.rollback();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True,type=Path);parser.add_argument('--backup',required=True,type=Path);parser.add_argument('--old-key-file',required=True,type=Path);parser.add_argument('--new-key-file',required=True,type=Path);parser.add_argument('--offline-confirmed',action='store_true');args=parser.parse_args()
    if not args.offline_confirmed:parser.error('必须停止对应Compose后端并确认离线')
    try:
        rotate(args.database,args.backup,args.old_key_file.read_text().strip(),args.new_key_file.read_text().strip())
        print('令牌密钥轮换完成；旧密文备份已保留，需要重新连接MCP。')
    except Exception:parser.exit(1,'轮换失败：请保留原数据和原密钥，确认密文环境及离线条件。\n')
