from support import APITest,store,patch
from ai_gateway import AIGatewayError

class StreamTests(APITest):
    def test_disconnect_is_persisted_as_interrupted(self):
        self.material();ident=self.conversation()
        from server import CampusClawAPI
        original=CampusClawAPI.sse
        def send(handler,event,data):
            if event=='delta':raise BrokenPipeError('模拟客户端断开')
            return original(handler,event,data)
        with patch('assistant_api.stream_chat',return_value=iter(['先分析 [1]'])),patch.object(CampusClawAPI,'sse',send):
            self.request('/conversations/'+ident+'/messages','POST',{'question':'牛顿第二定律'},self.alice,raw=True)
        with store.connect() as db:
            message=db.execute("SELECT * FROM messages WHERE role='assistant'").fetchone()
            self.assertEqual(message['status'],'interrupted');self.assertEqual(message['sources'],'[]')
            self.assertEqual(db.execute('SELECT busy FROM conversations WHERE id=?',(ident,)).fetchone()[0],0)

    def test_restart_recovers_generation_and_preserves_messages(self):
        ident=self.conversation()
        with store.connect() as db:
            db.execute('UPDATE conversations SET busy=1 WHERE id=?',(ident,))
            db.execute("INSERT INTO messages(conversationId,role,content,status) VALUES(?,'assistant','部分回答','generating')",(ident,))
        store.recover_interrupted()
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT busy FROM conversations WHERE id=?',(ident,)).fetchone()[0],0)
            row=db.execute('SELECT * FROM messages WHERE conversationId=?',(ident,)).fetchone()
            self.assertEqual(row['status'],'interrupted');self.assertEqual(row['content'],'部分回答')

    def test_sse_no_data_does_not_call_ai(self):
        ident=self.conversation()
        with patch('assistant_api.stream_chat') as model:
            code,raw=self.request('/conversations/'+ident+'/messages','POST',{'question':'xyz'},self.alice,raw=True)
            model.assert_not_called()
        self.assertEqual(code,200)
        events=self.events(raw)
        self.assertEqual([e[0] for e in events],['start','delta','sources','done'])
        self.assertEqual(events[1][1]['text'],'当前班级资料中没有找到相关内容。')
        self.assertFalse(events[-1][1]['answered'])

    def test_stream_history_prompt_citations_persistence(self):
        self.material();ident=self.conversation();captured=[]
        def model(messages):
            captured.append(messages)
            yield '先思考：'
            yield '力与加速度有什么关系？[1]'
        with patch('assistant_api.stream_chat',side_effect=model):
            for i in range(2):
                code,raw=self.request('/conversations/'+ident+'/messages','POST',{'question':'牛顿第二定律'},self.alice,raw=True)
                self.assertEqual(code,200);events=self.events(raw)
                self.assertEqual(events[-1][0],'done')
                refs=[v['sources'] for k,v in events if k=='sources'][0]
                self.assertTrue(refs);self.assertTrue(all(s['classId']=='a' for s in refs))
        self.assertIn('教师定制',captured[0][0]['content']);self.assertIn('不要直接给出完整最终答案',captured[0][0]['content'])
        self.assertTrue(any(m['role']=='assistant' for m in captured[1]))
        code,data=self.request('/conversations/'+ident+'/messages',token=self.alice)
        self.assertEqual(len(data['messages']),4)
        self.assertTrue(all(m['status']=='complete' for m in data['messages']))
        with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0],4)

    def test_model_failure_invalid_citation_and_permissions(self):
        self.material();ident=self.conversation();path='/conversations/'+ident+'/messages'
        for kwargs in [{'side_effect':AIGatewayError('超时',504)},{'return_value':iter(['不正确的引用 [99]'])}]:
            with patch('assistant_api.stream_chat',**kwargs):
                code,raw=self.request(path,'POST',{'question':'牛顿第二定律'},self.alice,raw=True)
                events=self.events(raw);self.assertEqual(events[-1][0],'error');self.assertNotIn('done',[e[0] for e in events])
        self.assertEqual(self.request(path,'POST',{'question':'x'},self.amy)[0],404)
        self.assertEqual(self.request(path,'POST',{},self.alice)[0],400)
        self.assertEqual(self.request(path,'POST',{'question':'x'*2001},self.alice)[0],400)
        with store.connect() as db:
            failed=store.rows(db,"SELECT * FROM messages WHERE role='assistant'")
            self.assertTrue(all(m['status']=='failed' and m['sources']=='[]' for m in failed))
            db.execute('UPDATE conversations SET busy=1 WHERE id=?',(ident,));db.commit()
        self.assertEqual(self.request(path,'POST',{'question':'x'},self.alice)[0],409)
