"""Loopback-only MCP Streamable HTTP JSON response server, Python stdlib."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sys
from urllib.parse import urlsplit
from tools import DEFINITIONS, InvalidArguments, call_result

VERSION='2025-03-26'
MAX_BODY=16384


def rpc_error(ident,code,message):
    return {'jsonrpc':'2.0','id':ident,'error':{'code':code,'message':message}}


def dispatch(message):
    if not isinstance(message,dict): return rpc_error(None,-32600,'无效请求')
    ident=message.get('id')
    has_id='id' in message
    if (message.get('jsonrpc')!='2.0' or not isinstance(message.get('method'),str)
        or not message['method'] or (has_id and (type(ident) not in (str,int) or len(str(ident))>128))
        or set(message)-{'jsonrpc','id','method','params'}):
        return rpc_error(None,-32600,'无效请求')
    # Notifications never produce a JSON-RPC response, including unknown ones.
    if not has_id: return None
    params=message.get('params',{})
    if not isinstance(params,dict): return rpc_error(ident,-32602,'参数必须为对象')
    method=message['method']
    try:
        if method=='initialize':
            if (not isinstance(params.get('protocolVersion'),str) or not params['protocolVersion']
                or not isinstance(params.get('capabilities'),dict)
                or not isinstance(params.get('clientInfo'),dict)
                or any(not isinstance(params['clientInfo'].get(k),str) or not params['clientInfo'][k] for k in ['name','version'])):
                raise InvalidArguments('初始化参数无效')
            result={'protocolVersion':VERSION,'capabilities':{'tools':{'listChanged':False}},
                    'serverInfo':{'name':'campusclaw-tools','version':'1.0.0'}}
        elif method=='tools/list':
            if params: raise InvalidArguments('工具清单无需参数，不支持分页游标')
            result={'tools':DEFINITIONS}
        elif method=='tools/call':
            if set(params)!={'name','arguments'} or not isinstance(params['name'],str): raise InvalidArguments('工具调用参数无效')
            result=call_result(params['name'],params['arguments'])
        elif method=='ping':
            if params: raise InvalidArguments('ping无需参数')
            result={}
        else: return rpc_error(ident,-32601,'方法不存在')
        return {'jsonrpc':'2.0','id':ident,'result':result}
    except InvalidArguments as error: return rpc_error(ident,-32602,str(error))
    except Exception: return rpc_error(ident,-32603,'内部错误')


def reject_constant(value): raise ValueError('non-finite')
def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate key')
        result[key]=value
    return result


class Handler(BaseHTTPRequestHandler):
    server_version='CampusClawMCP/1.0'
    def log_message(self,*args): pass  # No URLs, bodies, headers or token-bearing IDs in logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def reply(self,status,body=None,headers=None):
        payload=b'' if body is None else json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
        if self.server.auth_token in payload:
            status=400
            payload=json.dumps(rpc_error(None,-32600,'请求不得包含认证凭据'),ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(payload)))
        for key,value in (headers or {}).items():self.send_header(key,value)
        self.end_headers()
        try:self.wfile.write(payload)
        except OSError:pass

    def safe_origin(self):
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if os.environ.get('CAMPUSCLAW_CONTAINER_MODE')=='1':allowed.add(f'mcp:{self.server.server_port}')
        origin=self.headers.get('Origin')
        return host in allowed and (origin is None or origin in {'http://'+h for h in allowed})

    def authorized(self):
        values=self.headers.get_all('Authorization',[])
        if len(values)!=1:return False
        match=re.fullmatch(r'Bearer ([!-~]+)',values[0],re.IGNORECASE)
        return bool(match and hmac.compare_digest(match[1].encode(),self.server.auth_token))

    def do_GET(self):
        if not self.safe_origin():return self.reply(403,{'error':'请求来源不允许'})
        if self.path=='/health':return self.reply(200,{'status':'ok'})
        if self.path=='/mcp':
            if not self.authorized():return self.reply(401,{'error':'认证失败'},{'WWW-Authenticate':'Bearer'})
            return self.reply(405,{'error':'不支持服务器推送流'},{'Allow':'POST'})
        self.reply(404,{'error':'不存在'})

    def do_POST(self):
        if not self.safe_origin():return self.reply(403,{'error':'请求来源不允许'})
        if self.path!='/mcp':return self.reply(404,{'error':'不存在'})
        if not self.authorized():return self.reply(401,{'error':'认证失败'},{'WWW-Authenticate':'Bearer'})
        if self.headers.get_content_type()!='application/json':return self.reply(415,{'error':'需要application/json'})
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
            return self.reply(400,{'error':'需要单一Content-Length'})
        try:
            size=int(self.headers['Content-Length'])
            if not 0<size<=MAX_BODY:return self.reply(413,{'error':'请求正文长度超限'})
            raw=self.rfile.read(size)
            if len(raw)!=size:raise ValueError()
            if self.server.auth_token in raw:
                return self.reply(400,rpc_error(None,-32600,'请求不得包含认证凭据'))
            data=json.loads(raw.decode('utf-8'),parse_constant=reject_constant,object_pairs_hook=unique_object)
        except (ValueError,UnicodeError,RecursionError):return self.reply(400,rpc_error(None,-32700,'JSON解析失败'))
        except OSError:return self.reply(408,{'error':'读取请求超时'})
        if isinstance(data,list):
            if not data or len(data)>20 or any(isinstance(x,dict) and x.get('method')=='initialize' for x in data):
                return self.reply(400,rpc_error(None,-32600,'无效批量请求'))
            responses=[response for item in data if (response:=dispatch(item)) is not None]
            return self.reply(200,responses) if responses else self.reply(202)
        response=dispatch(data)
        self.reply(202) if response is None else self.reply(200,response)


class MCPServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,port,token):
        if not isinstance(token,str) or not re.fullmatch(r'[!-~]{16,256}',token):
            raise ValueError('MCP_AUTH_TOKEN未配置或格式无效（须16至256位无空格ASCII字符）')
        self.auth_token=token.encode('ascii')
        host='0.0.0.0' if os.environ.get('CAMPUSCLAW_CONTAINER_MODE')=='1' else '127.0.0.1'
        super().__init__((host,port),Handler)
    def handle_error(self,*args):
        print('MCP 请求异常；详情已抑制，避免泄露请求内容。',file=sys.stderr)


def main():
    parser=argparse.ArgumentParser(description='仅监听127.0.0.1的独立MCP工具服务器')
    parser.add_argument('--port',type=int,default=8090)
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('端口必须在1至65535之间')
    try:server=MCPServer(args.port,os.environ.get('MCP_AUTH_TOKEN',''))
    except ValueError as error:print(str(error),file=sys.stderr);return 1
    except OSError:print('MCP端口无法监听，请检查端口占用。',file=sys.stderr);return 1
    print('MCP工具服务器已启动，监听'+server.server_address[0]+':'+str(args.port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=='__main__':raise SystemExit(main())
