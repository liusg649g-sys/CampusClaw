from support import APITest,store

class PromptTests(APITest):
    def test_crud_and_role_validation(self):
        with store.connect() as db:before=db.execute('SELECT count(*) FROM prompts').fetchone()[0]
        for token in [self.alice,self.bob]:
            self.assertEqual(self.request('/prompts','POST',{'classId':'a','name':'x','content':'x'},token)[0],403)
            self.assertEqual(self.request('/prompts/'+self.prompt,'DELETE',token=token)[0],403)
        self.assertEqual(self.request('/skills?classId=a',token=self.bob)[0],403)
        self.assertEqual(self.request('/prompts','POST',{'classId':'a'},self.teacher)[0],400)
        with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM prompts').fetchone()[0],before)
        code,data=self.request('/prompts/'+self.prompt,'PUT',{'name':'新的名称','content':'新的引导'},self.teacher)
        self.assertEqual(code,200)
        code,data=self.request('/skills?classId=a',token=self.alice)
        self.assertEqual(data['prompts'][0]['content'],'新的引导')
        self.assertEqual(self.request('/prompts/'+self.prompt,'DELETE',token=self.teacher)[0],200)
        self.assertEqual(self.request('/skills?classId=a',token=self.alice)[1]['prompts'],[])
