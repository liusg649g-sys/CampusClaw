from support import APITest, server, store

class LoginTests(APITest):
    def test_roles_tokens_and_passwords(self):
        for token,role in [(self.teacher,'教师'),(self.alice,'学生')]:
            code,data=self.request('/session',token=token)
            self.assertEqual(code,200);self.assertEqual(data['role'],role);self.assertNotIn('password',data)
        for token in [None,'invalid.invalid.invalid',server.create_access_token('alice',ttl_seconds=-1)]:
            code,data=self.request('/classes',token=token)
            self.assertEqual(code,401);self.assertFalse(data['success'])
        self.assertEqual(self.request('/login','POST',{'username':'alice','password':'wrong'})[0],401)
        with store.connect() as db:
            password=db.execute('SELECT password FROM students WHERE username="alice"').fetchone()[0]
            self.assertNotEqual(password,self.password)
            self.assertTrue(store.password_matches(self.password,password))

    def test_bad_request_objects(self):
        for body in [[],None,{}, {'username':'alice'}]:
            code,_=self.request('/login','POST',body)
            self.assertIn(code,[400,401])
