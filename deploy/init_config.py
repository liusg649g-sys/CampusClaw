"""Create NEW isolated secrets/config only. Refuses existing output directories."""
import argparse
import base64
import os
from pathlib import Path
import secrets


def create(output,port=18080):
    output=Path(output).resolve()
    if not 1<=port<=65535 or port==8081:raise ValueError('端口无效或占用Litera保留端口')
    output.mkdir(parents=True,exist_ok=False)
    output.chmod(0o700)
    folder=output/'secrets';folder.mkdir(mode=0o700)
    values={'token_secret':secrets.token_hex(32),'mcp_auth_token':secrets.token_hex(32),
            'mcp_encryption_key':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            'teacher_password':secrets.token_urlsafe(24),'chat_api_key':'','embedding_api_key':''}
    for name,value in values.items():
        file=folder/name
        with file.open('x',encoding='utf-8') as stream:stream.write(value)
        # Files readable inside non-root containers; private parent blocks other
        # local POSIX users. On Windows retain user-private directory ACLs.
        file.chmod(0o444)
    project='campusclaw-stage4-'+secrets.token_hex(4)
    (output/'compose.env').write_text('CAMPUSCLAW_COMPOSE_PROJECT_NAME='+project+'\nCAMPUSCLAW_HTTP_PORT='+str(port)+'\nCAMPUSCLAW_COMPOSE_SECRETS_DIR='+folder.as_posix()+'\nCHAT_BASE_URL=\nCHAT_MODEL=course-chat\nEMBEDDING_BASE_URL=\nEMBEDDING_MODEL=course-embedding\nEMBEDDING_DIM=2048\n',encoding='utf-8')
    return output/'compose.env'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--port',type=int,default=18080)
    args=parser.parse_args()
    try:print('已创建独立配置，未输出secret：'+str(create(args.output,args.port)))
    except (OSError,ValueError):parser.exit(1,'创建失败：目录必须不存在且端口必须有效；不会覆盖已有配置。\n')
