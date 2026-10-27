"""Real local MCP for normal discovery; explicit simulator for protocol failures."""
import json
import secrets
import concurrent.futures
import threading
import contextlib
import io
import unittest
from unittest.mock import patch
from support import APITest,store
from mcp_host_fixture import IsolatedMCP
import mcp_models
import mcp_client
import mcp_secrets
from teaching_models import parse_skill


class MCPHostTests(APITest):
    def setUp(self):
        super().setUp()
        self.mcp=IsolatedMCP();self.addCleanup(self.mcp.close)
        self.allowed=patch.dict('os.environ',{'CAMPUSCLAW_MCP_ALLOWED_URLS':self.mcp.base})
        self.allowed.start();self.addCleanup(self.allowed.stop)
        self.sid=self.register()

    def register(self,**extra):
        data={'classId':'a','server_key':'mcp-local','name':'本机工具','base_url':self.mcp.base,'auth_token':self.mcp.secret};data.update(extra)
        status,result=self.request('/api/mcp/servers','POST',data,self.teacher)
        self.assertEqual(status,201,result)
        self.assertTrue(self.mcp.secret not in json.dumps(result),'credential leak')
        return result['id']

    def connect(self,sid=None):return self.request('/api/mcp/servers/'+str(sid or self.sid)+'/connect','POST',{},self.teacher)
    def tools(self,sid=None):return self.request('/api/mcp/servers/'+str(sid or self.sid)+'/tools',token=self.teacher)[1]['tools']
    def server(self):return self.request('/api/mcp/servers/'+str(self.sid),token=self.teacher)[1]['server']
    def skill(self,reference='formula_hint@mcp-local',name='MCP技能'):
        return self.request('/teaching-skills','POST',{'classId':'a','source':'名称：'+name+'\n适用条件：方程\n工具：'+reference+'\n启用：是\n\n提示说明'},self.teacher)

    def test_register_read_edit_delete(self):
        self.assertEqual(len(self.request('/api/mcp/servers?classId=a',token=self.teacher)[1]['servers']),1)
        status,_=self.request('/api/mcp/servers/'+str(self.sid),'PUT',{'name':'新显示名称','base_url':self.mcp.base},self.teacher)
        self.assertEqual(status,200);self.assertEqual(self.server()['server_key'],'mcp-local');self.assertEqual(self.server()['name'],'新显示名称')
        self.assertEqual(self.request('/api/mcp/servers/'+str(self.sid),'DELETE',token=self.teacher)[0],200)
        self.assertEqual(self.request('/api/mcp/servers/'+str(self.sid),token=self.teacher)[0],404)

    def test_student_all_management_denied(self):
        for path,method,body in [('/api/mcp/servers?classId=a','GET',None),('/api/mcp/servers','POST',{}),('/api/mcp/servers/'+str(self.sid),'PUT',{}),('/api/mcp/servers/'+str(self.sid)+'/connect','POST',{}),('/api/mcp/servers/'+str(self.sid),'DELETE',None)]:
            with self.subTest(method=method):self.assertEqual(self.request(path,method,body,self.alice)[0],403)

    def test_cross_owner_consistent_404(self):
        with store.connect() as db:db.execute("UPDATE classes SET teacher='other' WHERE id='a'")
        self.assertEqual(self.request('/api/mcp/servers/'+str(self.sid),token=self.teacher),self.request('/api/mcp/servers/999999',token=self.teacher))
        self.assertEqual(self.connect()[0],404)

    def test_real_initialize_notification_discovery(self):
        status,data=self.connect();self.assertEqual(status,200,data);self.assertEqual(data['tool_count'],3)
        self.assertEqual(self.mcp.httpd.sequence,['initialize','notifications/initialized','tools/list'])
        self.assertEqual({t['name'] for t in self.tools()},{'formula_hint','calculator','unit_convert'})
        self.assertTrue(self.server()['connected'])

    def test_token_is_encrypted_and_not_returned(self):
        self.connect()
        for response in [self.server(),self.tools(),self.request('/api/mcp/servers?classId=a',token=self.teacher)[1]]:
            self.assertTrue(self.mcp.secret not in json.dumps(response),'credential leak')
            self.assertNotIn('token_blob',json.dumps(response))
        with store.connect() as db:
            blob=db.execute('SELECT token_blob FROM mcp_servers WHERE id=?',(self.sid,)).fetchone()[0]
            self.assertTrue(self.mcp.secret.encode() not in bytes(blob),'plaintext credential persisted')
            self.assertTrue(mcp_secrets.unprotect(blob)==self.mcp.secret,'DPAPI roundtrip failed')

    def test_wrong_token_error_and_empty_cache(self):
        self.connect()
        self.request('/api/mcp/servers/'+str(self.sid),'PUT',{'name':'本机工具','base_url':self.mcp.base,'auth_token':secrets.token_hex(24)},self.teacher)
        status,data=self.connect();self.assertEqual(status,502);self.assertIn('认证',data['message']);self.assertEqual(self.tools(),[]);self.assertFalse(self.server()['connected'])

    def test_bad_version(self):
        self.mcp.httpd.mode='version';self.assertEqual(self.connect()[0],502);self.assertEqual(self.tools(),[])

    def test_timeout(self):
        self.mcp.httpd.mode='timeout'
        with patch.object(mcp_client,'TIMEOUT',.05):self.assertEqual(self.connect()[0],502)
        self.assertEqual(self.tools(),[])

    def test_bad_schema(self):
        self.mcp.httpd.mode='schema';self.assertEqual(self.connect()[0],502);self.assertEqual(self.tools(),[])

    def test_missing_schema(self):
        self.mcp.httpd.mode='missing_schema';self.assertEqual(self.connect()[0],502)

    def test_schema_external_ref(self):
        self.mcp.httpd.mode='ref';self.assertEqual(self.connect()[0],502)

    def test_remote_duplicate_names(self):
        self.mcp.httpd.mode='duplicate';self.assertEqual(self.connect()[0],502)

    def test_remote_description_limits(self):
        self.mcp.httpd.mode='oversized';self.assertEqual(self.connect()[0],502)

    def test_rpc_id_mismatch(self):
        self.mcp.httpd.mode='id';self.assertEqual(self.connect()[0],502)

    def test_remote_token_echo_redacted(self):
        self.mcp.httpd.mode='leak';status,data=self.connect();self.assertEqual(status,502)
        self.assertTrue(self.mcp.secret not in json.dumps(data),'credential leak');self.assertEqual(self.tools(),[])

    def test_no_redirects(self):
        self.mcp.httpd.mode='redirect';self.assertEqual(self.connect()[0],502);self.assertEqual(self.tools(),[])

    def test_disconnect_revokes_saved_skill(self):
        self.connect();status,data=self.skill();self.assertEqual(status,201,data);skill_id=data['id']
        self.request('/api/mcp/servers/'+str(self.sid)+'/disconnect','POST',{},self.teacher)
        self.assertEqual(self.tools(),[])
        skill=self.request('/teaching-skills/'+str(skill_id),token=self.teacher)[1]['skill']
        self.assertEqual(skill['available_tools'],[]);self.assertEqual(skill['unavailable_tools'],['formula_hint@mcp-local'])
        self.assertEqual(self.skill(name='离线技能')[0],400)

    def test_rediscovery_replaces_cache(self):
        self.connect();self.assertEqual(len(self.tools()),3)
        self.mcp.httpd.mode='reduced';self.assertEqual(self.connect()[0],200);self.assertEqual(len(self.tools()),1)

    def test_failure_invalidates_old_cache(self):
        self.connect();self.mcp.httpd.mode='schema';self.assertEqual(self.connect()[0],502);self.assertEqual(self.tools(),[])

    def test_same_tool_on_two_servers_unambiguous(self):
        other=self.register(server_key='second',name='另一个')
        self.connect();self.connect(other)
        self.assertEqual(self.skill('formula_hint@mcp-local,formula_hint@second')[0],201)
        with store.connect() as db:
            available,_=mcp_models.resolve_tools(db,'a',['formula_hint@mcp-local','formula_hint@second'])
            self.assertEqual({t['server_id'] for t in available},{self.sid,other})

    def test_stable_key_cannot_change(self):
        self.assertEqual(self.request('/api/mcp/servers/'+str(self.sid),'PUT',{'name':'新','base_url':self.mcp.base,'server_key':'changed'},self.teacher)[0],400)

    def test_unknown_tool_and_cross_class_skill_rejected(self):
        self.connect();self.assertEqual(self.skill('not_found@mcp-local')[0],400)
        foreign=self.register(classId='b',name='外班',server_key='foreign');self.connect(foreign)
        self.assertEqual(self.skill('calculator@foreign')[0],400)

    def test_duplicates_and_invalid_reference(self):
        self.connect()
        for ref in ['calculator@mcp-local,calculator@mcp-local','calculator@'+str(self.sid),'Calculator@mcp-local','formula-hint@mcp-local','calculator@mcp-local@x']:
            with self.subTest(reference=ref):self.assertEqual(self.skill(ref)[0],400)

    def test_disabled_tool_rejected(self):
        self.connect()
        with store.connect() as db:db.execute("UPDATE mcp_tools SET enabled=0 WHERE server_id=? AND name='formula_hint'",(self.sid,))
        self.assertEqual(self.skill()[0],400)

    def test_update_clears_connection(self):
        self.connect()
        self.request('/api/mcp/servers/'+str(self.sid),'PUT',{'name':'新','base_url':self.mcp.base},self.teacher)
        self.assertEqual(self.tools(),[]);self.assertFalse(self.server()['connected'])

    def test_deleted_server_revokes_reference(self):
        self.connect();self.skill()
        self.request('/api/mcp/servers/'+str(self.sid),'DELETE',token=self.teacher)
        with store.connect() as db:
            available,unavailable=mcp_models.resolve_tools(db,'a',['formula_hint@mcp-local'])
            self.assertEqual(available,[]);self.assertEqual(unavailable,['formula_hint@mcp-local'])

    def test_restart_epoch_invalidates_cache(self):
        self.connect()
        with patch.object(mcp_models,'PROCESS_EPOCH','simulated-new-process'):
            self.assertFalse(self.server()['connected']);self.assertEqual(self.tools(),[]);self.assertEqual(self.skill()[0],400)

    def test_repeated_init_preserves_registry_and_legacy(self):
        self.connect();old=self.conversation()
        for _ in range(3):
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM mcp_servers').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT count(*) FROM mcp_tools').fetchone()[0],3)
                self.assertIsNotNone(db.execute('SELECT * FROM conversations WHERE id=?',(old,)).fetchone())

    def test_history_without_tools_field(self):
        source='名称：历史技能\n适用条件：方程\n启用：是\n\n旧说明'
        self.assertEqual(json.loads(parse_skill(source)['tools_json']),[])
        self.assertEqual(self.request('/teaching-skills','POST',{'classId':'a','source':source},self.teacher)[0],201)
        self.assertEqual(json.loads(parse_skill(source.replace('启用：是','工具：calculator@mcp-local\n启用：是'))['tools_json']),['calculator@mcp-local'])

    def test_forged_discovery_input_rejected(self):
        self.assertEqual(self.request('/api/mcp/servers/'+str(self.sid)+'/connect','POST',{'tools':[]},self.teacher)[0],400)

    def test_ssrf_rejected_before_network(self):
        for url in ['http://127.0.0.1:5000','http://127.0.0.1:8080','http://192.168.1.1:8090','https://example.com','http://169.254.169.254','http://127.0.0.1:8090@evil.com','file:///etc/passwd','http://127.1:8090','http://2130706433:8090',self.mcp.base+'/admin',self.mcp.base+'?x=1']:
            with self.subTest(address=url):
                self.assertEqual(self.request('/api/mcp/servers','POST',{'classId':'a','server_key':'bad','name':'坏地址','base_url':url,'auth_token':self.mcp.secret},self.teacher)[0],400)

    def test_environment_proxy_ignored(self):
        with patch.dict('os.environ',{'HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1'}):self.assertEqual(self.connect()[0],200)

    def test_openapi_has_routes_and_write_only_token(self):
        doc=self.request('/openapi.json')[1]
        self.assertIn('/api/mcp/servers/{id}/connect',doc['paths'])
        self.assertTrue(doc['components']['schemas']['MCPServerCreate']['properties']['auth_token']['writeOnly'])
        self.assertNotIn('auth_token',doc['components']['schemas']['MCPServer']['properties'])

    def test_disconnect_during_discovery_cannot_reactivate(self):
        ready=threading.Event();release=threading.Event()
        original=mcp_client.MCPClient.discover
        def delayed(client):
            result=original(client);ready.set();release.wait(5);return result
        with patch.object(mcp_client.MCPClient,'discover',delayed),concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.connect)
            try:
                self.assertTrue(ready.wait(3))
                self.assertEqual(self.request('/api/mcp/servers/'+str(self.sid)+'/disconnect','POST',{},self.teacher)[0],200)
            finally:release.set()
            self.assertEqual(future.result()[0],409)
        self.assertFalse(self.server()['connected']);self.assertEqual(self.tools(),[])

    def test_invalid_token_rejected_without_partial_save(self):
        status,_=self.request('/api/mcp/servers/'+str(self.sid),'PUT',{'name':'不应保存','base_url':self.mcp.base,'auth_token':'short'},self.teacher)
        self.assertEqual(status,400);self.assertEqual(self.server()['name'],'本机工具')

    def test_credential_not_in_request_logs(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):self.connect()
        self.assertTrue(self.mcp.secret not in output.getvalue(),'credential leak in logs')

    def test_public_name_cannot_echo_stored_credential(self):
        status,data=self.request('/api/mcp/servers/'+str(self.sid),'PUT',{'name':self.mcp.secret,'base_url':self.mcp.base},self.teacher)
        self.assertEqual(status,400);self.assertTrue(self.mcp.secret not in json.dumps(data),'credential leak')


class MCPClientValidationTests(unittest.TestCase):
    def test_safe_default_allowlist_and_url_canonicalization(self):
        with patch.dict('os.environ',{'CAMPUSCLAW_MCP_ALLOWED_URLS':''}):
            self.assertEqual(mcp_client.validate_url('http://localhost:8090/'),'http://127.0.0.1:8090')
            for url in ['http://127.0.0.1:5000','http://127.0.0.1:0','http://@127.0.0.1:8090','http://127.0.0.1:8090?','http://127.0.0.1:8090#']:
                with self.subTest(address=url),self.assertRaises(mcp_client.MCPError):mcp_client.validate_url(url)

    def test_schema_strict_subset_and_bounds(self):
        for schema in [{'type':'object','properties':{'a':{'type':'string','minimum':3}}},
                       {'type':'object','properties':{},'required':['x']},
                       {'type':'object','properties':{'a':{'type':'string','pattern':'(a+)+$'}}},
                       {'type':'object','properties':{'a':{'type':'number','minimum':10**500}}},
                       {'type':'object','properties':{'a':{'type':'number','enum':[float('inf')]}}}]:
            with self.subTest(case=list(schema)),self.assertRaises(mcp_client.MCPError):mcp_client.validate_schema(schema)
