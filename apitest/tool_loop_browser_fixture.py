"""Mock model with actual MCP tools; isolated browser/API/database and no real AI."""
import json
import os
import subprocess
import time
from unittest.mock import patch
from support import APITest,ROOT
from stage1_browser_fixture import Handler
from mcp_host_fixture import IsolatedMCP
import tool_loop


def main():
    fixture=APITest();fixture.setUp();mcp=IsolatedMCP()
    from pathlib import Path
    report=Path(os.environ.get('CAMPUSCLAW_BROWSER_REPORT_DIR') or ROOT/'apitest/reports/lesson6-stage3');report.mkdir(parents=True,exist_ok=True)
    inputs=[]
    def decision(messages,tools,timeout=20):
        if any(m['role']=='tool' for m in messages):return {'role':'assistant','content':'模拟决策完成','tool_calls':[]}
        declaration=next(t for t in tools if 'expression' in t['function']['parameters']['properties'])
        return {'role':'assistant','content':None,'tool_calls':[{'id':'browser_call','type':'function',
            'function':{'name':declaration['function']['name'],'arguments':'{"expression":"2*(3+4)"}'}}]}
    def final(messages):
        inputs.append(messages)
        data=[m for m in messages if m['role']=='tool']
        assert data and '14.0' in data[-1]['content']
        stop=any('停止' in m.get('content','') for m in messages if m['role']=='user')
        if stop:
            for _ in range(100):time.sleep(.1);yield '模拟慢速回答'
        else:
            time.sleep(.2);yield '模拟模型根据真实工具结果：';time.sleep(.1);yield '14。'
    try:
        fixture.httpd.RequestHandlerClass=Handler
        with patch.dict('os.environ',{'CAMPUSCLAW_MCP_ALLOWED_URLS':mcp.base}),patch.object(tool_loop,'chat_tool_turn',decision),patch.object(tool_loop,'stream_agent_final',final):
            code,data=fixture.request('/api/mcp/servers','POST',dict(classId='a',server_key='loop-local',name='工具循环验收',base_url=mcp.base,auth_token=mcp.secret),fixture.teacher);assert code==201
            sid=data['id'];assert fixture.request('/api/mcp/servers/'+str(sid)+'/connect','POST',{},fixture.teacher)[0]==200
            code,data=fixture.request('/teaching-skills','POST',dict(classId='a',source='名称：浏览器计算\n适用条件：计算\n工具：calculator@loop-local\n启用：是\n\n按需使用计算器。'),fixture.teacher);assert code==201
            code,data=fixture.request('/agents','POST',dict(classId='a',name='工具调用助手',prompt='',enabled=True,skill_ids=[data['id']],material_ids=[]),fixture.teacher);assert code==201
            (report/'browser-fixture.json').write_text(json.dumps({'url':fixture.url,'agent_id':data['id']}),encoding='utf-8')
            result=subprocess.run(['node',str(ROOT/'apitest/tool_loop_browser_check.cjs')],cwd=ROOT,env=dict(os.environ,CAMPUSCLAW_TEST_PASSWORD=fixture.password),timeout=150)
        (report/'browser-model-inputs.json').write_text(json.dumps({'model':'EXPLICIT MOCK; MCP real','inputs':inputs},ensure_ascii=False,indent=2),encoding='utf-8')
        (report/'real-mcp-sequence.json').write_text(json.dumps(mcp.httpd.sequence),encoding='utf-8')
        return result.returncode
    finally:mcp.close();fixture.cleanup()


if __name__=='__main__':raise SystemExit(main())
