"""Bounded JSON MCP discovery client. Exact numeric-address allowlist, no redirects/proxies."""
import http.client
import ipaddress
import json
import math
import os
import re
import time
from urllib.parse import urlsplit

VERSION='2025-03-26'
TIMEOUT=3
MAX_RESPONSE=131072
NAME=re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
SERVER_KEY=re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')


class MCPError(ValueError): pass


def canonical_url(value):
    try:
        if not isinstance(value,str) or len(value)>256 or re.search(r'[\s\\%]',value):raise ValueError()
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or parsed.username is not None or parsed.password is not None or '?' in value or '#' in value or parsed.path not in ('','/'):
            raise ValueError()
        host=parsed.hostname
        if host=='localhost':host='127.0.0.1'
        if host=='mcp' and os.environ.get('CAMPUSCLAW_CONTAINER_MODE')=='1' and parsed.scheme=='http' and parsed.port==8090:
            return 'http://mcp:8090'
        address=ipaddress.ip_address(host)
        if address.version!=4 or address.is_unspecified or address.is_multicast or address.is_link_local:raise ValueError()
        port=parsed.port if parsed.port is not None else (443 if parsed.scheme=='https' else 80)
        if not 1<=port<=65535:raise ValueError()
        return '%s://%s:%d'%(parsed.scheme,address,port)
    except (ValueError,TypeError):raise MCPError('MCP地址格式不允许；仅接受无路径、无凭据的明确IPv4地址') from None


def validate_url(value):
    canonical=canonical_url(value)
    # Empty configuration retains safe defaults; custom entries replace defaults.
    configured=os.environ.get('CAMPUSCLAW_MCP_ALLOWED_URLS','').strip()
    entries=configured.split(',') if configured else ['http://127.0.0.1:8090']
    try:allowed={canonical_url(entry.strip()) for entry in entries if entry.strip()}
    except MCPError:raise MCPError('MCP地址白名单配置无效') from None
    if canonical not in allowed:raise MCPError('MCP地址不在服务端精确白名单内')
    return canonical


def _constant(value):raise ValueError()
def _object(pairs):
    output={}
    for key,value in pairs:
        if key in output:raise ValueError()
        output[key]=value
    return output


def validate_schema(schema):
    """Supported JSON Schema subset, bounded; reject refs/regex/unknown constructs."""
    if not isinstance(schema,dict) or schema.get('type')!='object':raise MCPError('工具inputSchema必须是对象结构')
    count=0
    def visit(node,depth=0):
        nonlocal count
        count+=1
        if depth>8 or count>128 or not isinstance(node,dict):raise MCPError('工具Schema结构超限')
        allowed={'type','description','title','properties','required','additionalProperties','items','enum','minimum','maximum','minLength','maxLength','minItems','maxItems','pattern'}
        if set(node)-allowed:raise MCPError('工具Schema包含不支持的关键字')
        kind=node.get('type')
        if kind not in ('object','string','number','integer','array','boolean','null'):raise MCPError('工具Schema类型无效')
        for key in ('description','title'):
            if key in node and (not isinstance(node[key],str) or len(node[key])>2000):raise MCPError('工具Schema说明无效')
        # Only the fixed calculator character allowlist is accepted as a regex.
        if 'pattern' in node and node['pattern']!=r'^[0-9. +*/()\-]+$':raise MCPError('工具Schema正则表达式不受支持')
        if kind=='object':
            properties=node.get('properties',{})
            required=node.get('required',[])
            if not isinstance(properties,dict) or len(properties)>32 or not isinstance(required,list) or any(not isinstance(x,str) for x in required) or len(set(required))!=len(required) or not set(required)<=set(properties):raise MCPError('工具Schema字段无效')
            if 'additionalProperties' in node and type(node['additionalProperties']) is not bool:raise MCPError('工具Schema额外字段规则无效')
            for key,item in properties.items():
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',key):raise MCPError('工具Schema参数名无效')
                visit(item,depth+1)
        elif 'properties' in node or 'required' in node or 'additionalProperties' in node:raise MCPError('工具Schema对象字段放置错误')
        if kind=='array':
            if 'items' not in node:raise MCPError('工具Schema数组缺少items')
            visit(node['items'],depth+1)
        elif 'items' in node:raise MCPError('工具Schema数组字段放置错误')
        for low,high in [('minLength','maxLength'),('minItems','maxItems')]:
            expected='string' if low=='minLength' else 'array'
            if (low in node or high in node) and kind!=expected:raise MCPError('工具Schema长度字段放置错误')
            for key in (low,high):
                if key in node and (type(node[key]) is not int or not 0<=node[key]<=10000):raise MCPError('工具Schema长度限制无效')
            if low in node and high in node and node[low]>node[high]:raise MCPError('工具Schema长度范围无效')
        for key in ('minimum','maximum'):
            if key in node and (kind not in ('number','integer') or type(node[key]) not in (float,int) or abs(node[key])>1e100 or not math.isfinite(node[key])):raise MCPError('工具Schema数值限制无效')
        if 'minimum' in node and 'maximum' in node and node['minimum']>node['maximum']:raise MCPError('工具Schema数值范围无效')
        if 'enum' in node and (not isinstance(node['enum'],list) or not 1<=len(node['enum'])<=64 or any(type(x) not in (str,int,float,bool,type(None)) for x in node['enum'])):raise MCPError('工具Schema枚举无效')
        if 'enum' in node:
            for item in node['enum']:
                if type(item) in (int,float) and (abs(item)>1e100 or not math.isfinite(item)):raise MCPError('工具Schema枚举数值无效')
            if len({json.dumps(x) for x in node['enum']})!=len(node['enum']):raise MCPError('工具Schema枚举重复')
        if 'pattern' in node and kind!='string':raise MCPError('工具Schema正则字段放置错误')
    visit(schema)
    if len(json.dumps(schema,ensure_ascii=False,allow_nan=False))>16000:raise MCPError('工具Schema过长')
    return schema


def validate_tools(result):
    if not isinstance(result,dict) or result.get('nextCursor') is not None or not isinstance(result.get('tools'),list) or len(result['tools'])>64:
        raise MCPError('工具清单无效或超限；当前不支持分页')
    output=[];seen=set()
    for tool in result['tools']:
        if not isinstance(tool,dict):raise MCPError('工具描述无效')
        name=tool.get('name');description=tool.get('description')
        if not isinstance(name,str) or not NAME.fullmatch(name) or name in seen:raise MCPError('工具名称无效或重复')
        if not isinstance(description,str) or not description.strip() or len(description)>2000:raise MCPError('工具说明缺失或过长')
        validate_schema(tool.get('inputSchema'))
        seen.add(name);output.append({'name':name,'description':description,'inputSchema':tool['inputSchema']})
    return output


class MCPClient:
    def __init__(self,base_url,token):
        self.base_url=validate_url(base_url)
        self.token=token
        self.session=None
        self.deadline=time.monotonic()+TIMEOUT*3

    def request(self,method,params=None,notification=False,ident=1):
        target=urlsplit(validate_url(self.base_url))
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise MCPError('MCP连接超时')
        cls=http.client.HTTPSConnection if target.scheme=='https' else http.client.HTTPConnection
        connection=cls(target.hostname,target.port,timeout=min(TIMEOUT,remaining))
        payload={'jsonrpc':'2.0','method':method}
        if not notification:payload['id']=ident
        if params is not None:payload['params']=params
        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':VERSION}
        if self.session:headers['Mcp-Session-Id']=self.session
        try:
            connection.request('POST','/mcp',body=json.dumps(payload).encode(),headers=headers)
            response=connection.getresponse()
            if response.status==401:raise MCPError('MCP认证失败，请重新配置专用令牌')
            if notification:
                if response.status!=202:raise MCPError('MCP初始化通知未被接受')
                if response.read(1):raise MCPError('MCP通知响应必须为空')
                return None
            if response.status!=200:raise MCPError('MCP握手或发现失败（HTTP响应异常）')
            if response.getheader('Content-Type','').split(';')[0].strip()!='application/json':raise MCPError('MCP只支持JSON响应模式')
            session=response.getheader('Mcp-Session-Id')
            if session:
                if not re.fullmatch(r'[!-~]{1,128}',session):raise MCPError('MCP会话标识无效')
                self.session=session
            chunks=[];total=0
            while True:
                if time.monotonic()>self.deadline:raise MCPError('MCP连接超时')
                chunk=response.read1(min(8192,MAX_RESPONSE+1-total))
                if not chunk:break
                total+=len(chunk)
                if total>MAX_RESPONSE:raise MCPError('MCP响应过大')
                chunks.append(chunk)
            result=json.loads(b''.join(chunks).decode('utf-8'),parse_constant=_constant,object_pairs_hook=_object)
            if not isinstance(result,dict) or result.get('jsonrpc')!='2.0' or type(result.get('id')) is not int or result['id']!=ident or 'error' in result or 'result' not in result:
                raise MCPError('MCP协议响应不匹配')
            # Remote descriptions must not smuggle our credential back to UI/cache.
            if self.token in json.dumps(result,ensure_ascii=False):raise MCPError('MCP响应包含敏感凭据，已拒绝')
            return result['result']
        except MCPError:raise
        except (OSError,TimeoutError):raise MCPError('MCP服务不可达或连接超时') from None
        except (ValueError,UnicodeError,RecursionError,http.client.HTTPException):raise MCPError('MCP响应格式无效') from None
        finally:connection.close()

    def discover(self):
        result=self.request('initialize',{'protocolVersion':VERSION,'capabilities':{},'clientInfo':{'name':'CampusClaw','version':'6.2'}},ident=1)
        if (not isinstance(result,dict) or result.get('protocolVersion')!=VERSION or not isinstance(result.get('capabilities'),dict)
            or not isinstance(result['capabilities'].get('tools'),dict) or not isinstance(result.get('serverInfo'),dict)
            or any(not isinstance(result['serverInfo'].get(k),str) or not 1<=len(result['serverInfo'][k])<=128 for k in ('name','version'))):raise MCPError('MCP协议版本或工具能力不匹配')
        tools_capability=result['capabilities']['tools']
        if 'listChanged' in tools_capability and type(tools_capability['listChanged']) is not bool:raise MCPError('MCP工具能力声明无效')
        self.request('notifications/initialized',notification=True)
        return validate_tools(self.request('tools/list',{},ident=2))
