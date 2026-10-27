import concurrent.futures
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import unittest
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
import tools


class MCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token=secrets.token_hex(24)
        cls.httpd=server.MCPServer(0,cls.token)
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.httpd.server_port)
        cls.client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        workspace=ROOT.parent
        files=list((workspace/'backend').rglob('*.py'))+list((workspace/'frontend').glob('*'))
        files+=list((workspace/'backend').glob('*.json'))+list((workspace/'backend/material_files').glob('*'))
        files+=list((workspace/'backend').glob('*.sqlite3*'))+[workspace/'.env',workspace/'nginx/nginx.conf']
        cls.business_baseline={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown();cls.httpd.server_close();cls.thread.join(2)

    def request(self,body=None,path='/mcp',token=True,headers=None,raw=None):
        h={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        if token is not False:h['Authorization']='Bearer '+(self.token if token is True else token)
        h.update(headers or {})
        payload=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req=urllib.request.Request(self.url+path,data=payload,headers=h)
        try:r=self.client.open(req,timeout=5)
        except urllib.error.HTTPError as e:r=e
        with r:
            data=r.read().decode();return r.status,json.loads(data) if data else None

    def rpc(self,method,params=None,ident=1):
        return self.request(dict(jsonrpc='2.0',id=ident,method=method,params={} if params is None else params))

    def call(self,name,args):
        status,body=self.rpc('tools/call',{'name':name,'arguments':args})
        self.assertEqual(status,200);return body

    def value(self,body):
        self.assertFalse(body['result']['isError']);return json.loads(body['result']['content'][0]['text'])

    def test_health_minimal(self):
        self.assertEqual(self.request(path='/health',token=False),(200,{'status':'ok'}))

    def test_missing_auth(self):self.assertEqual(self.request({},token=False)[0],401)
    def test_wrong_auth(self):self.assertEqual(self.request({},token='wrong-token')[0],401)
    def test_blank_auth(self):self.assertEqual(self.request({},token='')[0],401)

    def test_initialize(self):
        status,data=self.rpc('initialize',{'protocolVersion':server.VERSION,'capabilities':{},'clientInfo':{'name':'test','version':'1'}})
        self.assertEqual(status,200);self.assertEqual(data['result']['protocolVersion'],server.VERSION)
        self.assertEqual(data['result']['capabilities'],{'tools':{'listChanged':False}})
        self.assertEqual(data['result']['serverInfo']['name'],'campusclaw-tools')

    def test_version_negotiation(self):
        self.assertEqual(self.rpc('initialize',{'protocolVersion':'unknown','capabilities':{},'clientInfo':{'name':'test','version':'1'}})[1]['result']['protocolVersion'],server.VERSION)

    def test_initialize_validation(self):self.assertEqual(self.rpc('initialize')[1]['error']['code'],-32602)
    def test_notification(self):self.assertEqual(self.request({'jsonrpc':'2.0','method':'notifications/initialized'}),(202,None))
    def test_unknown_notification_no_response(self):self.assertEqual(self.request({'jsonrpc':'2.0','method':'notifications/unknown'}),(202,None))

    def test_tools_list_schema(self):
        definitions=self.rpc('tools/list')[1]['result']['tools']
        self.assertEqual({d['name'] for d in definitions},{'calculator','formula_hint','unit_convert'})
        for d in definitions:
            self.assertRegex(d['name'],r'^[a-z][a-z0-9_]*$');self.assertTrue(d['description'])
            s=d['inputSchema'];self.assertEqual(s['type'],'object');self.assertFalse(s['additionalProperties'])
            self.assertTrue(set(s['required'])<=set(s['properties']))

    def test_calculator_precedence(self):self.assertEqual(self.value(self.call('calculator',{'expression':'2*(3+4)-1/2'}))['value'],13.5)
    def test_calculator_unary_decimal(self):self.assertEqual(self.value(self.call('calculator',{'expression':'-0.1+0.3'}))['value'],.2)

    def test_formula_hint(self):
        self.assertIn('每一项',self.value(self.call('formula_hint',{'query':'去括号'}))['hint'])

    def test_unit_length(self):self.assertEqual(self.value(self.call('unit_convert',{'value':2.5,'from_unit':'km','to_unit':'m'})),{'value':2500.0,'unit':'m','factor':1000.0})
    def test_unit_mass(self):self.assertEqual(self.value(self.call('unit_convert',{'value':500,'from_unit':'g','to_unit':'kg'}))['value'],.5)
    def test_unit_time(self):self.assertEqual(self.value(self.call('unit_convert',{'value':2,'from_unit':'h','to_unit':'min'}))['value'],120)
    def test_incompatible_units(self):self.assertTrue(self.call('unit_convert',{'value':1,'from_unit':'m','to_unit':'s'})['result']['isError'])
    def test_unknown_units(self):self.assertEqual(self.call('unit_convert',{'value':1,'from_unit':'bogus','to_unit':'m'})['error']['code'],-32602)
    def test_missing_arguments(self):self.assertEqual(self.call('calculator',{})['error']['code'],-32602)
    def test_unexpected_arguments(self):self.assertEqual(self.call('calculator',{'expression':'1','extra':2})['error']['code'],-32602)
    def test_wrong_types(self):
        for value in ['1',True,None,[],{}]:
            with self.subTest(kind=type(value).__name__):self.assertEqual(self.call('unit_convert',{'value':value,'from_unit':'m','to_unit':'cm'})['error']['code'],-32602)

    def test_zero_division_tool_error(self):self.assertTrue(self.call('calculator',{'expression':'1/(2-2)'})['result']['isError'])
    def test_numeric_bounds(self):
        self.assertTrue(self.call('calculator',{'expression':'1000000000000*2'})['result']['isError'])
        self.assertEqual(self.call('unit_convert',{'value':1e13,'from_unit':'m','to_unit':'cm'})['error']['code'],-32602)
        self.assertTrue(self.call('unit_convert',{'value':1e12,'from_unit':'km','to_unit':'mm'})['result']['isError'])

    def test_malicious_expressions(self):
        for expression in ["__import__('os').system('echo bad')",'open(1)','[1][0]','2**8','1//2','a+1','1;2','1e9','１+２']:
            with self.subTest(expression=expression):self.assertEqual(self.call('calculator',{'expression':expression})['error']['code'],-32602)

    def test_expression_complexity(self):
        for expression in ['1'*201,'('*40+'1'+')'*40,'+'.join(['1']*40),'1..2']:
            with self.subTest(size=len(expression)):self.assertEqual(self.call('calculator',{'expression':expression})['error']['code'],-32602)

    def test_unknown_tool(self):self.assertEqual(self.call('unknown',{})['error']['code'],-32602)
    def test_unknown_method(self):self.assertEqual(self.rpc('not/a/method')[1]['error']['code'],-32601)
    def test_invalid_json(self):self.assertEqual(self.request(raw=b'{broken')[1]['error']['code'],-32700)
    def test_nonfinite_json(self):
        for raw in [b'{"value":NaN}',b'{"value":Infinity}']:
            self.assertEqual(self.request(raw=raw)[1]['error']['code'],-32700)

    def test_duplicate_keys(self):self.assertEqual(self.request(raw=b'{"jsonrpc":"2.0","jsonrpc":"1"}')[1]['error']['code'],-32700)
    def test_invalid_requests(self):
        for data in [None,True,123,'test',{},dict(jsonrpc='2.0',id=True,method='ping')]:
            with self.subTest(kind=str(data)):self.assertEqual(self.request(raw=json.dumps(data).encode())[1]['error']['code'],-32600)

    def test_invalid_params(self):self.assertEqual(self.rpc('tools/list',[])[1]['error']['code'],-32602)
    def test_batch(self):
        status,data=self.request([dict(jsonrpc='2.0',id=1,method='ping'),dict(jsonrpc='2.0',method='notifications/initialized')])
        self.assertEqual(status,200);self.assertEqual(data,[{'jsonrpc':'2.0','id':1,'result':{}}])
    def test_empty_batch(self):self.assertEqual(self.request([])[1]['error']['code'],-32600)
    def test_get_stream_not_supported(self):self.assertEqual(self.request()[0],405)
    def test_origin_denied(self):self.assertEqual(self.request({},headers={'Origin':'http://evil.example'})[0],403)
    def test_host_denied(self):self.assertEqual(self.request({},headers={'Host':'evil.example'})[0],403)
    def test_oversize_body(self):self.assertEqual(self.request(raw=b' '*17000)[0],413)
    def test_content_type(self):self.assertEqual(self.request({},headers={'Content-Type':'text/plain'})[0],415)

    def test_token_never_returned(self):
        for path,body in [('/health',None),('/mcp',{'jsonrpc':'2.0','method':'ping','id':self.token})]:
            response=self.request(body,path=path)
            self.assertNotIn(self.token,json.dumps(response))

    def test_concurrent_results(self):
        def worker(i):
            body=self.rpc('tools/call',{'name':'calculator','arguments':{'expression':str(i)+'*2'}},ident=i)[1]
            return body['id'],self.value(body)['value']
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(worker,range(30))),[(i,i*2) for i in range(30)])

    def test_startup_missing_token_fails_closed(self):
        environment=os.environ.copy();environment.pop('MCP_AUTH_TOKEN',None)
        result=subprocess.run([sys.executable,str(ROOT/'server.py')],env=environment,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,1);self.assertIn(b'MCP_AUTH_TOKEN',result.stderr)

    def test_startup_invalid_token_redacted(self):
        for value in ['', ' ', 'short', 'SECRET with spaces']:
            with self.subTest(size=len(value)):
                with self.assertRaises(ValueError) as error:server.MCPServer(0,value)
                if value:self.assertNotIn(value,str(error.exception))

    def test_logging_redacted(self):
        output=io.StringIO()
        with contextlib.redirect_stderr(output):self.httpd.handle_error(None,None)
        self.assertNotIn(self.token,output.getvalue());self.assertNotIn('Traceback',output.getvalue())

    def test_token_escaped_id_not_returned(self):
        encoded=''.join('\\u%04x'%ord(c) for c in self.token)
        raw=('{"jsonrpc":"2.0","id":"'+encoded+'","method":"ping"}').encode()
        status,body=self.request(raw=raw)
        self.assertEqual(status,400);self.assertNotIn(self.token,json.dumps(body))

    def test_zz_business_files_unchanged(self):
        for path,digest in self.business_baseline.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest,str(path.relative_to(ROOT.parent)))

    def test_listener_is_loopback(self):self.assertEqual(self.httpd.server_address[0],'127.0.0.1')
