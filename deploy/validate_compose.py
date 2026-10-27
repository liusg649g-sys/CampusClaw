"""Engine-independent Compose validation; saves non-secret normalized topology."""
import argparse
import json
from pathlib import Path
import subprocess


def validate(env_file,output):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['docker','compose','--env-file',str(Path(env_file).resolve()),'-f',str(root/'compose.yaml'),'config','--format','json'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
    if result.returncode:raise ValueError('Compose配置校验失败（详情未输出，避免泄露配置）')
    config=json.loads(result.stdout);services=config['services']
    assert set(services)=={'nginx','backend','mcp'}
    assert not services['backend'].get('ports') and not services['mcp'].get('ports')
    ports=services['nginx']['ports'];assert len(ports)==1 and ports[0]['host_ip']=='127.0.0.1'
    assert int(ports[0]['published'])!=8081 and ports[0]['target']==8080
    assert not services['nginx'].get('volumes')
    assert services['backend']['volumes'][0]['type']=='volume' and services['backend']['volumes'][0]['target']=='/data'
    assert services['backend']['environment']['CAMPUSCLAW_MCP_ALLOWED_URLS']=='http://mcp:8090'
    assert set(services['nginx']['networks'])==set(services['backend']['networks'])==set(services['mcp']['networks'])
    assert 'auth_token' not in services['backend']['environment']
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    return config


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--env-file',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    validate(args.env_file,args.output)
    print('Compose CLI校验及端口/卷/白名单结构断言通过；没有构建或启动容器。')
