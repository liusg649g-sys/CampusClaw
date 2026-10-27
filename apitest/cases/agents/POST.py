from support import APITest, store, server
from teaching_models import DEFAULT_AGENT_PROMPT, route_skill, allowed_material_ids

SOURCE='名称：数学解题引导\n适用条件：方程,去括号\n资料：数学\n工具：knowledge_search\n启用：是\n\n先检查学生的思路，不给最终答案。'

class AgentTests(APITest):
    def skill(self, name='数学解题引导', cid='a'):
        code,data=self.request('/teaching-skills','POST',{'classId':cid,'source':SOURCE.replace('数学解题引导',name)},self.teacher)
        self.assertEqual(code,201,data)
        return data['id']

    def agent(self, name='数学助手', **extra):
        body={'classId':'a','name':name,'prompt':'','enabled':True,'skill_ids':[],'material_ids':[],**extra}
        code,data=self.request('/agents','POST',body,self.teacher)
        self.assertEqual(code,201,data)
        return data['agent']

    def test_two_agents_defaults_unique_and_validation(self):
        one=self.agent();two=self.agent('语文助手')
        self.assertNotEqual(one['id'],two['id'])
        self.assertEqual(one['prompt'],'');self.assertEqual(one['effective_prompt'],DEFAULT_AGENT_PROMPT)
        for changes in [{'name':'数学助手'},{'name':'a'*65},{'prompt':'a'*2001},{'enabled':'true'},{'name':''},{'skill_ids':[True]},{'skill_ids':[10**100]},{'material_ids':[1]}]:
            body={'classId':'a','name':'新助手','prompt':'','enabled':True,'skill_ids':[],'material_ids':[],**changes}
            code,data=self.request('/agents','POST',body,self.teacher)
            self.assertEqual(code,400,data)
        with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM tutor_agents').fetchone()[0],2)

    def test_edit_enable_and_student_visibility(self):
        one=self.agent();other=self.agent('停用助手',enabled=False)
        code,data=self.request('/agents?classId=a',token=self.alice)
        self.assertEqual([a['id'] for a in data['agents']],[one['id']])
        missing=self.request('/agents/999999',token=self.alice)
        self.assertEqual(self.request('/agents/'+str(other['id']),token=self.alice),missing)
        self.assertEqual(self.request('/agents/'+str(one['id']),token=self.bob),missing)
        code,data=self.request('/agents/'+str(one['id']),'PUT',{'name':'新名称','prompt':'新角色','enabled':False,'skill_ids':[],'material_ids':[]},self.teacher)
        self.assertEqual(code,200);self.assertEqual(data['agent']['effective_prompt'],'新角色')
        self.assertEqual(self.request('/agents/'+str(one['id']),token=self.alice),missing)
        self.assertEqual(self.request('/agents?classId=b',token=self.alice),self.request('/agents?classId=missing',token=self.alice))
        self.assertEqual(self.request('/agents/'+str(10**100),token=self.alice),missing)

    def test_nonteacher_writes_and_unauthenticated(self):
        agent=self.agent();skill=self.skill()
        for path in ['/agents','/agents/'+str(agent['id']),'/agents/'+str(agent['id'])+'/bindings','/teaching-skills','/teaching-skills/'+str(skill)]:
            for method in ['POST','PUT','DELETE']:
                self.assertEqual(self.request(path,method,{} if method!='DELETE' else None,self.alice)[0],403)
        self.assertEqual(self.request('/agents?classId=a')[0],401)
        self.assertEqual(self.request('/teaching-skills?classId=a',token='invalid.invalid.invalid')[0],401)

    def test_binding_transaction_and_class_boundaries(self):
        skill=self.skill();foreign_skill=self.skill('他班技能','b')
        material=self.material();foreign_material=self.material('b')
        agent=self.agent(skill_ids=[skill],material_ids=[material])
        path='/agents/'+str(agent['id'])+'/bindings'
        expected=self.request(path,token=self.teacher)[1]['agent']
        for body in [{'skill_ids':[foreign_skill],'material_ids':[]},{'skill_ids':[],'material_ids':[foreign_material]},{'skill_ids':[999999],'material_ids':[]},{'skill_ids':[],'material_ids':['missing']}]:
            self.assertEqual(self.request(path,'PUT',body,self.teacher),self.request('/agents/999999',token=self.teacher))
            self.assertEqual(self.request(path,token=self.teacher)[1]['agent'],expected)
        code,data=self.request(path,'PUT',{'skill_ids':[],'material_ids':[]},self.teacher)
        self.assertEqual(code,200);self.assertEqual(data['agent']['skill_ids'],[]);self.assertEqual(data['agent']['material_ids'],[])
        with store.connect() as db:
            self.assertIsNone(route_skill(db,agent['id'],'a','方程'))
            self.assertEqual(allowed_material_ids(db,agent['id'],'a',server.load_materials(),server.MATERIAL_FILES_DIR),set())

    def test_deleted_file_and_deleted_material_revoke_immediately(self):
        material=self.material();agent=self.agent(material_ids=[material])
        with store.connect() as db:self.assertEqual(allowed_material_ids(db,agent['id'],'a',server.load_materials(),server.MATERIAL_FILES_DIR),{material})
        saved=server.load_materials()[0]
        file=server.MATERIAL_FILES_DIR/saved['storedName'];content=file.read_bytes();file.unlink()
        self.assertEqual(self.request('/agents/'+str(agent['id']),token=self.teacher)[1]['agent']['material_ids'],[])
        with store.connect() as db:self.assertEqual(allowed_material_ids(db,agent['id'],'a',server.load_materials(),server.MATERIAL_FILES_DIR),set())
        self.assertEqual(self.request('/agents/'+str(agent['id'])+'/bindings','PUT',{'skill_ids':[],'material_ids':[material]},self.teacher)[0],404)
        file.write_bytes(content)
        self.assertEqual(self.request('/materials/'+material,'DELETE',token=self.teacher)[0],200)
        self.assertEqual(self.request('/agents/'+str(agent['id']),token=self.teacher)[1]['agent']['material_ids'],[])

    def test_skill_delete_cascades_bindings_and_agent_delete(self):
        skill=self.skill();agent=self.agent(skill_ids=[skill])
        self.assertEqual(self.request('/teaching-skills/'+str(skill),'DELETE',token=self.teacher)[0],200)
        self.assertEqual(self.request('/agents/'+str(agent['id']),token=self.teacher)[1]['agent']['skill_ids'],[])
        self.assertEqual(self.request('/agents/'+str(agent['id']),'DELETE',token=self.teacher)[0],200)
        with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM tutor_agent_skills').fetchone()[0],0)

    def test_live_routing_enabled_bindings_tie_and_zero(self):
        first=self.skill('第一个');second=self.skill('第二个');unbound=self.skill('未绑定')
        agent=self.agent(skill_ids=[second,first])
        with store.connect() as db:
            self.assertEqual(route_skill(db,agent['id'],'a','方程')['id'],first)
            self.assertIsNone(route_skill(db,agent['id'],'a','完全不相关'))
            self.assertIsNone(route_skill(db,agent['id'],'b','方程'))
        self.request('/teaching-skills/'+str(first),'PUT',{'enabled':False},self.teacher)
        with store.connect() as db:self.assertEqual(route_skill(db,agent['id'],'a','方程')['id'],second)
        self.request('/agents/'+str(agent['id'])+'/bindings','PUT',{'skill_ids':[unbound],'material_ids':[]},self.teacher)
        with store.connect() as db:self.assertEqual(route_skill(db,agent['id'],'a','去括号')['id'],unbound)

    def test_routing_highest_score_casefold_and_separators(self):
        first=self.skill('普通');second=self.skill('更具体')
        source=SOURCE.replace('数学解题引导','更具体').replace('方程,去括号','Equation；移项、去括号|分数')
        self.request('/teaching-skills/'+str(second),'PUT',{'source':source},self.teacher)
        agent=self.agent(skill_ids=[first,second])
        with store.connect() as db:
            self.assertEqual(route_skill(db,agent['id'],'a','EQUATION 怎么移项去括号')['id'],second)
            self.assertIsNone(route_skill(db,agent['id'],'a','无匹配内容'))

    def test_repeated_init_preserves_legacy_and_new_records(self):
        ident=self.conversation();self.skill();self.agent()
        self.request('/conversations/'+ident+'/messages','POST',{'question':'没有资料'},self.alice,raw=True)
        tables=['classes','students','members','prompts','conversations','messages','skills','tutor_agents']
        with store.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in tables}
        for _ in range(3):
            with store.connect() as db:pass
        with store.connect() as db:after={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in tables}
        self.assertEqual(before,after)
        self.assertEqual(self.request('/skills?classId=a',token=self.alice)[1]['prompts'][0]['id'],self.prompt)

    def test_openapi_new_paths_and_bearer(self):
        code,doc=self.request('/openapi.json');self.assertEqual(code,200)
        for path in ['/agents','/agents/{id}','/agents/{id}/bindings','/teaching-skills','/teaching-skills/{id}']:
            self.assertIn(path,doc['paths'])
            for op in doc['paths'][path].values():self.assertEqual(op['security'],[{'BearerAuth':[]}])
        self.assertIn('/conversations/{id}/messages',doc['paths'])
