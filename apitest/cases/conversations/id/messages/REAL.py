import os
import unittest
from support import APITest

@unittest.skipUnless(os.environ.get('CAMPUSCLAW_TEST_REAL_AI')=='1','真实模型集成未启用；设置 CAMPUSCLAW_TEST_REAL_AI=1、CHAT_BASE_URL、CHAT_API_KEY、CHAT_MODEL 后运行')
class RealModelIntegration(APITest):
    def test_real_service_end_to_end(self):
        # No mock: actual teacher creation, student login, local class retrieval,
        # external chat SSE, citations, and persistent history.
        self.material();ident=self.conversation()
        code,raw=self.request('/conversations/'+ident+'/messages','POST',{'question':'请引导我理解牛顿第二定律，不要直接给答案。'},self.alice,raw=True,timeout=150)
        self.assertEqual(code,200)
        events=self.events(raw)
        self.assertEqual(events[-1][0],'done',raw)
        self.assertTrue(events[-1][1]['answered'])
        sources=[d['sources'] for e,d in events if e=='sources'][0]
        self.assertTrue(sources);self.assertTrue(all(s['classId']=='a' for s in sources))
        _,data=self.request('/conversations/'+ident+'/messages',token=self.alice)
        self.assertEqual(data['messages'][-1]['status'],'complete')
        self.assertTrue(data['messages'][-1]['sources'])
