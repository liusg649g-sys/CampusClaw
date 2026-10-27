from support import APITest

SOURCE='名称：数学解题引导\n适用条件：方程,去括号\n资料：数学\n工具：knowledge_search\n启用：是\n\n先问学生的思路。'

class TeachingSkillTests(APITest):
    def test_create_read_edit_toggle_source_and_unique(self):
        code,data=self.request('/teaching-skills','POST',{'classId':'a','source':SOURCE},self.teacher)
        self.assertEqual(code,201,data);ident=data['id']
        self.assertEqual(data['skill']['source_text'],SOURCE);self.assertEqual(data['skill']['tools'],['knowledge_search'])
        self.assertEqual(self.request('/teaching-skills/'+str(ident),token=self.alice)[1]['skill']['name'],'数学解题引导')
        self.assertEqual(self.request('/teaching-skills','POST',{'classId':'a','source':SOURCE},self.teacher)[0],400)
        updated=SOURCE.replace('数学解题引导','新技能')
        code,data=self.request('/teaching-skills/'+str(ident),'PUT',{'source':updated},self.teacher)
        self.assertEqual(code,200);self.assertEqual(data['skill']['name'],'新技能')
        code,data=self.request('/teaching-skills/'+str(ident),'PUT',{'enabled':False},self.teacher)
        self.assertFalse(data['skill']['enabled']);self.assertIn('启用：否',data['skill']['source_text'])
        self.assertEqual(self.request('/teaching-skills/'+str(ident),token=self.bob),self.request('/teaching-skills/999999',token=self.bob))

    def test_invalid_files_do_not_create_records(self):
        invalid=[SOURCE.replace('工具：knowledge_search','工具：formula_hint@server'),SOURCE.replace('名称：','错误字段：'),SOURCE.replace('启用：是','启用：是\n启用：否'),SOURCE.replace('启用：是','启用：true'),SOURCE.split('\n\n')[0],SOURCE.replace('适用条件：方程,去括号\n','')]
        for source in invalid:
            code,data=self.request('/teaching-skills','POST',{'classId':'a','source':source},self.teacher)
            self.assertEqual(code,400,data);self.assertTrue(data['message'])
        self.assertEqual(self.request('/teaching-skills?classId=a',token=self.teacher)[1]['skills'],[])
