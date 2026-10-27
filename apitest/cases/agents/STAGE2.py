"""Isolated stage-two integration tests. Every chat response is explicitly mocked."""
import json
from unittest.mock import patch
from support import APITest, store, server
import agent_chat
from ai_gateway import AIGatewayError


class AgentConversationTests(APITest):
    def setUp(self):
        super().setUp()
        self.captured=[]
        def mock_chat(messages):
            self.captured.append(messages)
            yield '模拟回答'
            yield '[9'
            yield '99]'
        self.model=patch.object(agent_chat,'stream_chat',mock_chat)
        self.model.start();self.addCleanup(self.model.stop)
        self.mid=self.material()
        code,data=self.request('/teaching-skills','POST',{'classId':'a','source':'名称：物理解题引导\n适用条件：牛顿,力\n资料：物理\n工具：knowledge_search\n启用：是\n\n技能原始说明'},self.teacher)
        self.assertEqual(code,201)
        self.sid=data['id']
        self.aid=self.agent()
        self.cid=self.chat()

    def agent(self,**kw):
        body=dict(classId='a',name='智能体',prompt='角色原文',enabled=True,skill_ids=[self.sid],material_ids=[self.mid]);body.update(kw)
        code,data=self.request('/agents','POST',body,self.teacher);self.assertEqual(code,201)
        return data['id']

    def chat(self,aid=None):
        code,data=self.request('/conversations','POST',{'classId':'a','agentId':aid or self.aid},self.alice)
        self.assertEqual(code,201);return data['id']

    def ask(self,q='牛顿',cid=None,**extra):
        code,raw=self.request('/conversations/'+(cid or self.cid)+'/messages','POST',dict(question=q,**extra),self.alice,raw=True)
        self.assertEqual(code,200)
        return self.events(raw)

    def detail(self):
        return self.request('/conversations/'+self.cid+'/messages',token=self.alice)[1]

    def test_create_title_and_agent_identity(self):
        c=self.detail()['conversation'];self.assertEqual(c['agentId'],self.aid);self.assertEqual(c['title'],'新的提问')

    def test_invalid_disabled_and_foreign_agents_same_404(self):
        other=self.agent(classId='b',name='B',skill_ids=[],material_ids=[])
        with store.connect() as db:db.execute('UPDATE tutor_agents SET enabled=0 WHERE id=?',(self.aid,))
        values=[]
        for aid in [self.aid,other,999999]:
            values.append(self.request('/conversations','POST',{'classId':'a','agentId':aid},self.alice))
        self.assertEqual(values[0],values[1]);self.assertEqual(values[1],values[2]);self.assertEqual(values[0][0],404)

    def test_disabled_agent_existing_session_continues(self):
        with store.connect() as db:db.execute('UPDATE tutor_agents SET enabled=0 WHERE id=?',(self.aid,))
        self.assertEqual(self.ask()[-1][0],'done')

    def test_tampered_request_does_not_switch_agent_or_class(self):
        self.ask(agentId=999,classId='b')
        c=self.detail()['conversation'];self.assertEqual(c['agentId'],self.aid);self.assertEqual(c['classId'],'a')

    def test_private_and_missing_session_same_404(self):
        first=self.request('/conversations/'+self.cid,token=self.amy)
        self.assertEqual(first,self.request('/conversations/not-found',token=self.amy));self.assertEqual(first[0],404)

    def test_removed_membership_denies_existing_session(self):
        with store.connect() as db:db.execute("DELETE FROM members WHERE username='alice' AND classId='a'")
        self.assertEqual(self.request('/conversations/'+self.cid,token=self.alice)[0],404)
        self.assertEqual(self.request('/conversations',token=self.alice)[1]['conversations'],[])

    def test_only_bound_materials_before_top_scoring(self):
        other=self.material('b');unbound=self.material()
        events=self.ask();sources=events[0][1]['citations']
        self.assertEqual({s['materialId'] for s in sources},{self.mid});self.assertNotIn(other,str(sources));self.assertNotIn(unbound,str(sources))

    def test_empty_bindings_call_model_without_class_fallback(self):
        self.request('/agents/'+str(self.aid)+'/bindings','PUT',{'skill_ids':[self.sid],'material_ids':[]},self.teacher)
        events=self.ask();self.assertEqual(events[0][1]['citations'],[]);self.assertEqual(len(self.captured),1)
        self.assertEqual(''.join(d['text'] for e,d in events if e=='delta'),'模拟回答')

    def test_no_hit_still_calls_model(self):
        events=self.ask('zzzzzzzzzzqxy');self.assertEqual(events[0][1]['citations'],[]);self.assertEqual(len(self.captured),1)

    def test_skill_disabled_and_unbound_next_turn(self):
        self.assertIsNotNone(self.ask()[0][1]['skill'])
        self.request('/teaching-skills/'+str(self.sid),'PUT',{'enabled':False},self.teacher)
        self.assertIsNone(self.ask()[0][1]['skill'])
        self.request('/teaching-skills/'+str(self.sid),'PUT',{'enabled':True},self.teacher)
        self.request('/agents/'+str(self.aid)+'/bindings','PUT',{'skill_ids':[],'material_ids':[self.mid]},self.teacher)
        self.assertIsNone(self.ask()[0][1]['skill'])

    def test_role_changed_next_turn(self):
        self.ask()
        with store.connect() as db:db.execute('UPDATE tutor_agents SET prompt=? WHERE id=?',('角色新文',self.aid))
        self.ask();self.assertIn('角色新文',self.captured[-1][0]['content']);self.assertNotIn('角色原文',self.captured[-1][0]['content'])

    def test_material_deleted_file_immediate_revocation(self):
        self.ask()
        record=next(m for m in server.load_materials() if m['id']==self.mid)
        (server.MATERIAL_FILES_DIR/record['storedName']).unlink()
        self.assertEqual(self.ask()[0][1]['citations'],[])

    def test_skill_subject_matches_title_not_filename(self):
        materials=server.load_materials();materials[0]['title']='语文';server.save_materials(materials)
        self.assertEqual(self.ask()[0][1]['citations'],[])

    def test_sse_order_and_persisted_body_and_metadata(self):
        events=self.ask();self.assertEqual(events[0][0],'meta');self.assertEqual(events[-1][0],'done')
        self.assertTrue(all(e=='delta' for e,_ in events[1:-1]))
        final=self.detail()['messages'][-1]
        self.assertEqual(final['content'],''.join(d['text'] for e,d in events if e=='delta'))
        self.assertEqual(final['id'],events[-1][1]['messageId']);self.assertEqual(final['skill_name'],'物理解题引导')
        self.assertEqual(final['sources'],events[0][1]['citations'])
        self.assertEqual([s['ref'] for s in final['sources']],list(range(1,len(final['sources'])+1)))

    def test_failure_status_and_busy_released(self):
        def fail(messages):
            yield '部分';raise AIGatewayError('模拟模型失败',502)
        with patch.object(agent_chat,'stream_chat',fail):events=self.ask()
        self.assertEqual(events[-1][0],'error');self.assertNotIn('done',[e for e,_ in events])
        self.assertEqual(self.detail()['messages'][-1]['status'],'failed')
        self.assertEqual(self.ask()[-1][0],'done')

    def test_timeout_status(self):
        with patch.object(agent_chat.time,'monotonic',side_effect=[0,121]):events=self.ask()
        self.assertEqual(events[-1][0],'error');self.assertEqual(self.detail()['messages'][-1]['status'],'failed')

    def test_interruption_status(self):
        original=server.CampusClawAPI.sse
        def disconnected(handler,event,data):
            if event=='delta':raise BrokenPipeError()
            return original(handler,event,data)
        with patch.object(server.CampusClawAPI,'sse',disconnected):events=self.ask()
        self.assertEqual(events[0][0],'meta');self.assertEqual(self.detail()['messages'][-1]['status'],'interrupted')

    def test_busy_409(self):
        with store.connect() as db:db.execute('UPDATE conversations SET busy=1 WHERE id=?',(self.cid,))
        self.assertEqual(self.request('/conversations/'+self.cid+'/messages','POST',{'question':'牛顿'},self.alice)[0],409)

    def test_title_once_and_activity_sorting(self):
        q='第一次问题的长度必须超过二十四个字符才能核实截断的结果'
        self.ask(q);self.assertEqual(self.detail()['conversation']['title'],q[:24])
        other=self.chat();self.ask('第二次',cid=other);self.ask('第三次')
        self.assertEqual(self.request('/conversations',token=self.alice)[1]['conversations'][0]['id'],self.cid)
        self.assertEqual(self.detail()['conversation']['title'],q[:24])
        # SQLite legacy timestamps use a space; new timestamps use ISO T.
        old=self.conversation()
        with store.connect() as db:
            stamp=db.execute('SELECT updated_at FROM conversations WHERE id=?',(self.cid,)).fetchone()[0]
            db.execute('UPDATE conversations SET createdAt=? WHERE id=?',(stamp[:10]+' 23:59:59',old))
        self.assertEqual(self.request('/conversations',token=self.alice)[1]['conversations'][0]['id'],old)

    def test_six_message_window_current_included_and_500_chars(self):
        with store.connect() as db:
            for i in range(10):db.execute("INSERT INTO messages(conversationId,role,content,status) VALUES(?,?,?,'complete')",(self.cid,'user' if i%2==0 else 'assistant',str(i)*700))
            db.execute("INSERT INTO messages(conversationId,role,content,status) VALUES(?,'system','BAD','complete')",(self.cid,))
            db.execute("INSERT INTO messages(conversationId,role,content,status) VALUES(?,'assistant',' ','complete')",(self.cid,))
        self.ask('Q'*500);messages=self.captured[-1]
        self.assertEqual(len(messages),7);self.assertTrue(all(len(m['content'])<=500 for m in messages[1:-1]));self.assertTrue(messages[-1]['content'].startswith('问题：'+'Q'*500+'\n'))
        self.assertEqual(len(self.detail()['messages']),14)

    def test_reconnect_retains_new_and_legacy_history(self):
        old=self.conversation();self.ask()
        for _ in range(3):
            with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM conversations').fetchone()[0],2)
        self.assertEqual(self.detail()['messages'][-1]['content'],'模拟回答')
        self.assertEqual(self.request('/conversations/'+old,token=self.alice)[0],200)

    def test_openapi_matches_two_modes(self):
        doc=self.request('/openapi.json')[1]
        self.assertIn('oneOf',doc['components']['schemas']['ConversationInput'])
        self.assertIn('agent',doc['paths']['/conversations/{id}/messages']['post']['responses']['200']['content']['text/event-stream']['examples'])

    def test_two_agents_have_disjoint_material_scopes(self):
        second=self.material()
        aid=self.agent(name='另一个智能体',material_ids=[second])
        other=self.chat(aid)
        self.assertEqual({s['materialId'] for s in self.ask()[0][1]['citations']},{self.mid})
        self.assertEqual({s['materialId'] for s in self.ask(cid=other)[0][1]['citations']},{second})

    def test_snapshot_consistency_during_config_change(self):
        def changing_model(messages):
            self.captured.append(messages)
            with store.connect() as db:
                db.execute('UPDATE tutor_agents SET prompt=? WHERE id=?',('动态新角色',self.aid))
                db.execute('DELETE FROM tutor_agent_skills WHERE agent_id=?',(self.aid,))
                db.execute('DELETE FROM tutor_agent_materials WHERE agent_id=?',(self.aid,))
            yield '模拟'
        with patch.object(agent_chat,'stream_chat',changing_model):first=self.ask()
        self.assertIsNotNone(first[0][1]['skill']);self.assertTrue(first[0][1]['citations'])
        self.assertIn('角色原文',self.captured[0][0]['content'])
        second=self.ask();self.assertIsNone(second[0][1]['skill']);self.assertEqual(second[0][1]['citations'],[])
        self.assertIn('动态新角色',self.captured[-1][0]['content'])

    def test_missing_model_config_is_explicit_error_no_fake_answer(self):
        from ai_gateway import stream_chat as real_stream
        with patch.dict('os.environ',{'CHAT_BASE_URL':'','CHAT_API_KEY':'','EMBEDDING_BASE_URL':'','EMBEDDING_API_KEY':'','AI_GATEWAY_BASE_URL':'','AI_GATEWAY_API_KEY':''}), patch.object(agent_chat,'stream_chat',real_stream):
            events=self.ask('unmatched-zzz')
        self.assertEqual(events[-1][0],'error');self.assertNotIn('delta',[e for e,_ in events]);self.assertEqual(self.detail()['messages'][-1]['status'],'failed')

    def test_split_reference_filter(self):
        cleaner=agent_chat.CitationFilter([1])
        result=''.join(cleaner.feed(t) for t in ['A[','99','] B[1',']',' C['])+cleaner.feed('',final=True)
        self.assertEqual(result,'A B[1] C[')

    def test_swagger_aliases_and_openapi(self):
        expected=self.request('/docs',raw=True)
        self.assertEqual(expected[0],200)
        for route in ('/swagger','/swagger/'):
            self.assertEqual(self.request(route,raw=True),expected)
        self.assertIn('/swagger',self.request('/openapi.json')[1]['paths'])

    def test_agent_question_course_length_limits(self):
        for text in ('Q','Q'*501,'Q'*900):
            self.assertEqual(self.request('/conversations/'+self.cid+'/messages','POST',{'question':text},self.alice)[0],400)
        self.assertEqual(self.captured,[])
        self.assertEqual(self.ask('QQ')[-1][0],'done')

    def test_agent_identity_in_initial_meta_without_tools(self):
        metadata=self.ask()[0][1]
        self.assertEqual(metadata['agent']['id'],self.aid)
        self.assertNotIn('tool_calls',metadata)

    def test_top_four_precede_subject_filter_without_backfill(self):
        other=self.material()
        materials=server.load_materials()
        for m in materials:
            if m['id']==other:m['title']='语文'
        server.save_materials(materials)
        self.request('/agents/'+str(self.aid)+'/bindings','PUT',{'skill_ids':[self.sid],'material_ids':[self.mid,other]},self.teacher)
        top=[dict(materialId=other,text='牛顿',sourceFile='语文.txt',chunkIndex=i) for i in range(4)]
        with patch.object(agent_chat,'search_knowledge',return_value=top) as search:
            events=self.ask()
        self.assertEqual(search.call_args.kwargs['limit'],4)
        self.assertEqual(search.call_args.kwargs['allowed_material_ids'],{self.mid,other})
        self.assertEqual(events[0][1]['citations'],[])
        self.assertEqual(len(self.captured),1)
        self.assertEqual(events[-1][0],'done')

    def test_subject_filter_renumbers_surviving_citations(self):
        other=self.material()
        materials=server.load_materials()
        for m in materials:
            if m['id']==other:m['title']='语文'
        server.save_materials(materials)
        self.request('/agents/'+str(self.aid)+'/bindings','PUT',{'skill_ids':[self.sid],'material_ids':[self.mid,other]},self.teacher)
        matches=[dict(materialId=m,text='牛顿',sourceFile='test.txt',chunkIndex=i) for i,m in enumerate([other,self.mid,other,self.mid])]
        with patch.object(agent_chat,'search_knowledge',return_value=matches):events=self.ask()
        self.assertEqual([s['ref'] for s in events[0][1]['citations']],[1,2])
        self.assertEqual({s['materialId'] for s in events[0][1]['citations']},{self.mid})
