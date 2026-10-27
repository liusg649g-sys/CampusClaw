from support import APITest

class DocumentationTests(APITest):
    def test_openapi_bearer_and_stream(self):
        code,doc=self.request('/openapi.json')
        self.assertEqual(code,200);self.assertEqual(doc['openapi'],'3.0.3')
        self.assertEqual(doc['components']['securitySchemes']['BearerAuth']['scheme'],'bearer')
        self.assertEqual(doc['paths']['/login']['post']['security'],[])
        op=doc['paths']['/conversations/{id}/messages']['post']
        self.assertEqual(op['security'],[{'BearerAuth':[]}])
        self.assertIn('text/event-stream',op['responses']['200']['content'])
        code,html=self.request('/docs',raw=True)
        self.assertEqual(code,200);self.assertIn('SwaggerUIBundle',html)
