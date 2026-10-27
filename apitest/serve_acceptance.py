"""Opt-in local acceptance site using existing handlers, Mock AI and real local MCP.

Does not read .env or touch native service data. Keeps its test data on exit.
"""
import json
import argparse
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

os.environ['CAMPUSCLAW_TOKEN_SECRET']=secrets.token_hex(32)
from support import APITest,ROOT,server,store,knowledge_base
from stage1_browser_fixture import Handler
from mcp_host_fixture import IsolatedMCP
import agent_chat
import tool_loop


class AcceptanceHandler(Handler):
    def do_GET(self):
        route=urlsplit(self.path).path
        if route=='/assistant.html/':route='/assistant.html'
        if route in ('/','/assistant.html'):
            file=ROOT/'frontend'/('index.html' if route=='/' else 'assistant.html')
            body=file.read_text(encoding='utf-8').replace('<body>', '<body><p style="background:#fff3cd;padding:12px">隔离验收站：Mock 模型，真实本地 MCP；不是原业务站。</p>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        else:super().do_GET()


def decision(messages,tools,timeout=20):
    if any(m['role']=='tool' for m in messages) or not tools:return {'role':'assistant','content':'Mock decision complete','tool_calls':[]}
    tool=next(t for t in tools if 'expression' in t['function']['parameters'].get('properties',{}))
    return {'role':'assistant','content':None,'tool_calls':[{'id':'acceptance_'+secrets.token_hex(6),'type':'function','function':{'name':tool['function']['name'],'arguments':json.dumps({'expression':'2*(3+4)'})}}]}


def final(messages):
    results=[m for m in messages if m['role']=='tool']
    status=json.loads(results[-1]['content'])['status'] if results else 'none'
    for text in ('【Mock 模型】本地工具执行状态：',status,'。这是假定表达式 2*(3+4) 的确定性验收，不代表真实模型理解了提问。'):
        time.sleep(.2);yield text


def plain(messages):
    for text in ('【Mock 模型】请先列出已知条件，','再说明你尝试的步骤。','本回答仅用于验收增量显示与解题引导配置。'):
        time.sleep(.2);yield text


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reuse-runtime',type=Path,help='Resume only an existing project-local isolated test dataset')
    args=parser.parse_args()
    reuse=None
    if args.reuse_runtime:
        runtime=args.reuse_runtime.resolve()
        if not runtime.is_relative_to((ROOT/'temp').resolve()):raise ValueError('只允许本项目临时运行记录')
        reuse=Path(json.loads(runtime.read_text(encoding='utf-8'))['data_dir']).resolve()
        if not reuse.is_relative_to((ROOT/'temp/isolated-api-tests').resolve()):raise ValueError('拒绝使用真实业务数据目录')
        for name in ('assistant.sqlite3','account.json','materials.json','files'):
            if not (reuse/name).exists():raise ValueError('原隔离数据不完整，拒绝初始化覆盖')
    # Binding probe refuses occupied ports; never kills another listener.
    with socket.socket() as probe:probe.bind(('127.0.0.1',18080))
    fixture=APITest();fixture.setUp();mcp=IsolatedMCP()
    if reuse:
        server.ACCOUNT_FILE=reuse/'account.json';server.MATERIALS_FILE=reuse/'materials.json'
        server.MATERIAL_FILES_DIR=reuse/'files';store.DB_FILE=reuse/'assistant.sqlite3'
        knowledge_base.KNOWLEDGE_FILE=reuse/'knowledge.json'
        fixture.teacher=server.create_access_token(server.load_account()['username'])
    report=ROOT/'temp/acceptance-site-20261027';report.mkdir(parents=True,exist_ok=True)
    # Keep independent test data, including user-created acceptance configurations.
    fixture.temp._finalizer.detach()
    os.environ['CAMPUSCLAW_MCP_ALLOWED_URLS']=mcp.base
    code,registered=fixture.request('/api/mcp/servers?classId=a',token=fixture.teacher)
    assert code==200
    existing=next((s for s in registered['servers'] if s['server_key']=='acceptance-local'),None)
    payload=dict(classId='a',server_key='acceptance-local',name=existing['name'] if existing else '隔离MCP',base_url=mcp.base,auth_token=mcp.secret)
    code,data=fixture.request('/api/mcp/servers'+('/'+str(existing['id']) if existing else ''),'PUT' if existing else 'POST',payload,fixture.teacher)
    assert code==(200 if existing else 201)
    assert fixture.request('/api/mcp/servers/'+str(data['id'])+'/connect','POST',{},fixture.teacher)[0]==200
    if not reuse:
        material=fixture.material()
        for name,trigger,tools in [('数学解题引导','方程,解题','knowledge_search'),('计算验证','计算','calculator@acceptance-local')]:
            code,skill=fixture.request('/teaching-skills','POST',dict(classId='a',source='名称：'+name+'\n适用条件：'+trigger+'\n工具：'+tools+'\n启用：是\n\n先询问思路，只给启发，不给完整最终答案。'),fixture.teacher);assert code==201
            assert fixture.request('/agents','POST',dict(classId='a',name=name+'助手',prompt='',enabled=True,skill_ids=[skill['id']],material_ids=[material] if tools=='knowledge_search' else []),fixture.teacher)[0]==201
    fixture.httpd.shutdown();fixture.httpd.server_close();fixture.thread.join()
    fixture.httpd=server.ThreadingHTTPServer(('127.0.0.1',18080),AcceptanceHandler)
    credentials=report/'TEST_ACCOUNTS.json'
    if not reuse:
        credentials.write_text(json.dumps({'notice':'ONLY isolated test accounts; do not reuse passwords','teacher':{'username':'teacher','password':fixture.password},'student':{'username':'alice','password':fixture.password},'second_student':{'username':'amy','password':fixture.password}},ensure_ascii=False,indent=2),encoding='utf-8');credentials.chmod(0o600)
    (report/'runtime.json').write_text(json.dumps({'pid':os.getpid(),'url':'http://127.0.0.1:18080/assistant.html','data_dir':str(reuse) if reuse else fixture.temp.name,'model':'EXPLICIT MOCK','mcp':'real local stage-one server'},indent=2),encoding='utf-8')
    with patch.object(agent_chat,'stream_chat',plain),patch.object(tool_loop,'chat_tool_turn',decision),patch.object(tool_loop,'stream_agent_final',final):
        print('Acceptance site ready: http://127.0.0.1:18080/assistant.html ; Mock AI + real local MCP',flush=True)
        fixture.httpd.serve_forever()


if __name__=='__main__':main()
