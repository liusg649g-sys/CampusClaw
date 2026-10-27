import base64
import json
import secrets
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import server
import knowledge_base
import assistant_store as store

class APITest(unittest.TestCase):
    def setUp(self):
        temporary_root=ROOT/'temp'/'isolated-api-tests'
        temporary_root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=temporary_root)
        root=Path(self.temp.name)
        self.patches=[patch.object(server,'ACCOUNT_FILE',root/'account.json'),patch.object(server,'MATERIALS_FILE',root/'materials.json'),patch.object(server,'MATERIAL_FILES_DIR',root/'files'),patch.object(knowledge_base,'KNOWLEDGE_FILE',root/'knowledge.json'),patch.object(store,'DB_FILE',root/'assistant.sqlite3'),patch.dict('os.environ',{'EMBEDDING_BASE_URL':'','EMBEDDING_API_KEY':'','AI_GATEWAY_BASE_URL':'','AI_GATEWAY_API_KEY':''})]
        for p in self.patches:p.start()
        server.MATERIAL_FILES_DIR.mkdir()
        self.password=secrets.token_urlsafe(24)
        server.save_account(dict(server.DEFAULT_ACCOUNT,password=self.password))
        server.save_materials([])
        self.httpd=server.ThreadingHTTPServer(('127.0.0.1',0),server.CampusClawAPI)
        # Join request workers before restoring patched paths and removing files.
        self.httpd.daemon_threads=False
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)
        self.url='http://127.0.0.1:'+str(self.httpd.server_port)
        self.teacher=self.login('teacher',self.password)
        self.request('/classes','POST',{'id':'a','name':'课程A'},self.teacher)
        self.request('/classes','POST',{'id':'b','name':'课程B'},self.teacher)
        for name,cid in [('alice','a'),('amy','a'),('bob','b')]:
            status,_=self.request('/students','POST',{'username':name,'password':self.password,'name':name,'classId':cid},self.teacher)
            self.assertEqual(status,201)
        self.alice=self.login('alice',self.password)
        self.amy=self.login('amy',self.password)
        self.bob=self.login('bob',self.password)
        status,data=self.request('/prompts','POST',{'classId':'a','name':'解题引导','content':'教师定制：先问学生对牛顿第二定律的理解。'},self.teacher)
        self.assertEqual(status,201)
        self.prompt=data['id']

    def cleanup(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join(2)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def request(self,path,method='GET',body=None,token=None,raw=False,timeout=8):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:
                value=response.read().decode()
                return response.status,value if raw else json.loads(value)
        except urllib.error.HTTPError as e:
            return e.code,json.loads(e.read().decode())

    def login(self,name,password):
        code,data=self.request('/login','POST',{'username':name,'password':password})
        self.assertEqual(code,200)
        return data['token']

    def conversation(self):
        code,data=self.request('/conversations','POST',{'classId':'a','promptId':self.prompt},self.alice)
        self.assertEqual(code,201)
        return data['id']

    def material(self,cid='a'):
        code,data=self.request('/materials','POST',{'classId':cid,'title':'物理','fileName':'physics.md','dataBase64':base64.b64encode('牛顿第二定律：力等于质量乘以加速度。'.encode()).decode()},self.teacher)
        self.assertEqual(code,201)
        return data['material']['id']

    def events(self,raw):
        return [(block.splitlines()[0][7:],json.loads(block.splitlines()[1][6:])) for block in raw.strip().split('\n\n')]
