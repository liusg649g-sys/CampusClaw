"""Isolated actual stage-one MCP service plus explicitly labelled failure simulator."""
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from unittest.mock import patch
from support import ROOT

path=ROOT/'mcp-server'
sys.path.insert(0,str(path))
spec=importlib.util.spec_from_file_location('campusclaw_test_mcp_service',path/'server.py')
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
sys.path.remove(str(path))


class FailureHandler(service.Handler):
    def do_POST(self):
        if self.server.mode=='real':return super().do_POST()
        message=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        method=message.get('method')
        self.server.sequence.append(method)
        if self.server.mode=='timeout':time.sleep(.25)
        if self.server.mode=='redirect':return self.reply(302,{}, {'Location':'http://127.0.0.1:5000/health'})
        if method=='notifications/initialized':return self.reply(202)
        if method=='initialize':
            result={'protocolVersion':'bad' if self.server.mode=='version' else service.VERSION,
                    'capabilities':{'tools':{}},'serverInfo':{'name':'explicit-failure-simulator','version':'1'}}
        else:
            tool={'name':'formula_hint','description':'模拟发现工具','inputSchema':{'type':'object','properties':{'query':{'type':'string'}}}}
            if self.server.mode=='schema':tool['inputSchema']={'type':'string'}
            if self.server.mode=='missing_schema':tool.pop('inputSchema')
            if self.server.mode=='leak':tool['description']=self.server.test_credential
            if self.server.mode=='ref':tool['inputSchema']={'type':'object','$ref':'file:///private'}
            result={'tools':[tool]}
            if self.server.mode=='duplicate':result['tools'].append(tool)
            if self.server.mode=='oversized':tool['description']='X'*2001
        self.reply(200,{'jsonrpc':'2.0','id':999 if self.server.mode=='id' else message.get('id'),'result':result})


class IsolatedMCP:
    def __init__(self):
        self.secret=secrets.token_hex(24)
        self.httpd=service.MCPServer(0,self.secret)
        self.httpd.RequestHandlerClass=FailureHandler
        self.httpd.mode='real';self.httpd.sequence=[];self.httpd.test_credential=self.secret
        self.base='http://127.0.0.1:'+str(self.httpd.server_port)
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        original=service.dispatch
        def captured(message):
            self.httpd.sequence.append(message.get('method') if isinstance(message,dict) else 'invalid')
            return original(message)
        self.capture=patch.object(service,'dispatch',captured);self.capture.start()
    def close(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join(2);self.capture.stop()
