from support import APITest

class HistoryTests(APITest):
    def test_private_history(self):
        ident=self.conversation()
        for token in [self.amy,self.bob,self.teacher]:
            self.assertEqual(self.request('/conversations/'+ident,token=token)[0],404)
            self.assertEqual(self.request('/conversations/'+ident+'/messages',token=token)[0],404)
        self.assertEqual(self.request('/conversations/missing',token=self.alice)[0],404)
        code,data=self.request('/conversations',token=self.alice)
        self.assertEqual(data['conversations'][0]['id'],ident)
        code,data=self.request('/conversations/'+ident+'/messages',token=self.alice)
        self.assertEqual(data['messages'],[])
        # Every history/message request rechecks current membership.
        import assistant_store as store
        with store.connect() as db:db.execute('DELETE FROM members WHERE classId=? AND username=?',('a','alice'))
        self.assertEqual(self.request('/conversations/'+ident+'/messages',token=self.alice)[0],403)
        self.assertEqual(self.request('/conversations',token=self.alice)[1]['conversations'],[])
