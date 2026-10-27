"""Optional and potentially billable. Never enabled by default."""
import os
import unittest
from support import APITest


@unittest.skipUnless(os.environ.get('CAMPUSCLAW_TEST_REAL_AGENT')=='1',
                     '未启用真实智能体模型测试；需用户自行设置 CAMPUSCLAW_TEST_REAL_AGENT=1 与 CHAT_*')
class RealAgentIntegration(APITest):
    def test_real_agent_hit_and_no_bound_materials(self):
        mid=self.material()
        code,data=self.request('/agents','POST',dict(classId='a',name='真实模型隔离验收',
            prompt='',enabled=True,skill_ids=[],material_ids=[mid]),self.teacher)
        self.assertEqual(code,201);aid=data['id']
        code,data=self.request('/conversations','POST',dict(classId='a',agentId=aid),self.alice)
        self.assertEqual(code,201);cid=data['id']
        for empty in (False,True):
            if empty:
                self.request('/agents/'+str(aid)+'/bindings','PUT',dict(skill_ids=[],material_ids=[]),self.teacher)
            code,raw=self.request('/conversations/'+cid+'/messages','POST',dict(question='请解释牛顿第二定律。'),self.alice,raw=True,timeout=150)
            self.assertEqual(code,200)
            events=self.events(raw)
            self.assertEqual(events[0][0],'meta');self.assertEqual(events[-1][0],'done',raw)
            self.assertEqual(bool(events[0][1]['citations']),not empty)
            _,detail=self.request('/conversations/'+cid+'/messages',token=self.alice)
            self.assertEqual(detail['messages'][-1]['content'],''.join(d['text'] for e,d in events if e=='delta'))
