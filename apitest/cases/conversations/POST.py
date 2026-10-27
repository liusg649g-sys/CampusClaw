from support import APITest,store

class ConversationTests(APITest):
    def test_creation_validation_and_persistence(self):
        for body,code in [({},400),({'classId':'b','promptId':self.prompt},403),({'classId':'missing','promptId':self.prompt},404),({'classId':'a','promptId':'missing'},404)]:
            self.assertEqual(self.request('/conversations','POST',body,self.alice)[0],code)
        ident=self.conversation()
        with store.connect() as db:
            saved=dict(db.execute('SELECT * FROM conversations WHERE id=?',(ident,)).fetchone())
            self.assertEqual(saved['student'],'alice');self.assertEqual(saved['classId'],'a');self.assertIn('教师定制',saved['prompt']);self.assertTrue(saved['createdAt'])
            self.assertEqual(db.execute('SELECT count(*) FROM conversations').fetchone()[0],1)
        self.assertEqual(self.request('/conversations','POST',{'classId':'a','promptId':self.prompt},self.teacher)[0],403)
