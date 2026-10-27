"""Explicit simulated model, temporary storage and random loopback port only."""
import base64
import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch
from support import APITest, ROOT, server
from stage1_browser_fixture import Handler
import agent_chat


def main():
    fixture=APITest();fixture.setUp()
    reports=Path(os.environ.get('CAMPUSCLAW_BROWSER_REPORT_DIR') or ROOT/'apitest/reports')
    reports.mkdir(exist_ok=True,parents=True)
    captures=[]
    def mock_chat(messages):
        captures.append(messages)
        question=messages[-1]['content']
        if '停止测试' in question:
            for _ in range(100):
                time.sleep(.1);yield '模拟慢速片段'
        else:
            for delta in ['模拟教学提示：','先想一想条件。','[','1',']']:
                time.sleep(.06);yield delta
    try:
        fixture.httpd.RequestHandlerClass=Handler
        for subject,words in [('数学','方程,去括号'),('语文','阅读,作文')]:
            code,data=fixture.request('/materials','POST',dict(classId='a',title=subject+'材料',fileName=subject+'.md',dataBase64=base64.b64encode((words+'：模拟课程材料。').encode()).decode()),fixture.teacher)
            assert code==201
            mid=data['material']['id']
            code,data=fixture.request('/teaching-skills','POST',dict(classId='a',source='名称：'+subject+'解题引导\n适用条件：'+words+'\n资料：'+subject+'\n工具：knowledge_search\n启用：是\n\n'+subject+'模拟技能说明'),fixture.teacher)
            assert code==201
            sid=data['id']
            code,_=fixture.request('/agents','POST',dict(classId='a',name=subject+'助手',prompt=subject+'教师角色',enabled=True,skill_ids=[sid],material_ids=[mid]),fixture.teacher)
            assert code==201
        (reports/'stage2-browser-fixture.json').write_text(json.dumps({'url':fixture.url}),encoding='utf-8')
        with patch.object(agent_chat,'stream_chat',mock_chat):
            result=subprocess.run(['node',str(ROOT/'apitest/stage2_browser_check.cjs')],cwd=ROOT,env=dict(os.environ,CAMPUSCLAW_TEST_PASSWORD=fixture.password),timeout=140)
            time.sleep(.5)
        (reports/'stage2-model-inputs.json').write_text(json.dumps({'model':'EXPLICIT MOCK; not real AI','messages':captures},ensure_ascii=False,indent=2),encoding='utf-8')
        return result.returncode
    finally:fixture.cleanup()


if __name__=='__main__':raise SystemExit(main())
