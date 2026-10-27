from support import APITest
import urllib.parse

class SearchTests(APITest):
    def test_class_isolation_and_material_access(self):
        aid=self.material('a');bid=self.material('b')
        query=urllib.parse.quote('牛顿第二定律')
        code,data=self.request('/knowledge/search?classId=a&q='+query,token=self.alice)
        self.assertEqual(code,200);self.assertTrue(data['results'])
        self.assertTrue(all(s['classId']=='a' for s in data['results']))
        for path in ['/knowledge/search?classId=b&q='+query,'/materials/'+bid,'/materials/'+bid+'/download','/materials?classId=b']:
            self.assertEqual(self.request(path,token=self.alice)[0],403)
        self.assertEqual(self.request('/knowledge/search?classId=missing&q=x',token=self.alice)[0],404)
        self.assertEqual(self.request('/knowledge/search?classId=a',token=self.alice)[0],400)
        code,data=self.request('/materials',token=self.alice)
        self.assertEqual([m['id'] for m in data['materials']],[aid])
        self.assertEqual(self.request('/materials/'+aid,'DELETE',token=self.alice)[0],403)
        self.assertEqual(self.request('/knowledge/answer','POST',{'classId':'b','question':'牛顿'},self.alice)[0],403)

    def test_no_data(self):
        code,data=self.request('/knowledge/search?classId=a&q=xyz',token=self.alice)
        self.assertEqual(code,200);self.assertEqual(data['results'],[])
        code,data=self.request('/knowledge/answer','POST',{'classId':'a','question':'xyz'},self.alice)
        self.assertFalse(data['answered']);self.assertEqual(data['sources'],[])
