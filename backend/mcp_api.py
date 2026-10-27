"""Teacher-only registry/discovery. Does not expose execution or alter chat."""
from datetime import datetime, timezone
import json
import re
import sqlite3
from urllib.parse import urlparse,parse_qs
import assistant_store as store
import mcp_models as models
from mcp_client import MCPClient,MCPError,SERVER_KEY,validate_url
from mcp_secrets import protect,unprotect,SecretError
from teaching_models import ValidationError


class HostError(Exception):
    def __init__(self,message='资源不存在',status=404):super().__init__(message);self.status=status


class MCPMixin:
    def mcp_route(self,method):
        parsed=urlparse(self.path)
        match=re.fullmatch(r'/api/mcp/servers(?:/([^/]+))?(?:/(connect|disconnect|tools))?',parsed.path)
        is_audit=parsed.path=='/api/mcp/tool-calls'
        if not match and not is_audit:return False
        if not self.require_login():return True
        try:
            if self.auth_payload['role']!='teacher':raise HostError('仅教师可管理MCP服务器',403)
            data=self.read_json() if method in ('POST','PUT') else {}
            if not isinstance(data,dict):raise ValidationError('请求体必须为对象')
            with store.connect() as db:
                if is_audit:self.mcp_audit_dispatch(db,method,parse_qs(parsed.query))
                else:self.mcp_dispatch(db,method,match.groups(),parse_qs(parsed.query),data)
        except HostError as error:self.send_json({'success':False,'message':str(error)},error.status)
        except (ValidationError,MCPError,SecretError) as error:self.send_json({'success':False,'message':str(error)},400)
        except sqlite3.IntegrityError:self.send_json({'success':False,'message':'服务器名称或稳定标识在本班已存在'},400)
        except (ValueError,TypeError):self.send_json({'success':False,'message':'请求参数格式无效'},400)
        except sqlite3.Error:self.send_json({'success':False,'message':'MCP存储暂不可用'},503)
        return True

    def mcp_audit_dispatch(self,db,method,query):
        if method!='GET':raise HostError('审计只允许查询',405)
        allowed={'classId','page','pageSize','status','serverId','userId','conversationId','messageId','tool_ref'}
        if set(query)-allowed or any(len(values)!=1 for values in query.values()):raise ValidationError('审计过滤参数无效')
        def value(key,default=''):return (query.get(key) or [default])[0]
        cid=value('classId');self.mcp_class(db,cid)
        def number(key,default,maximum):
            text=value(key,str(default))
            if not re.fullmatch(r'[1-9][0-9]{0,8}',text) or int(text)>maximum:raise ValidationError('审计分页或编号无效')
            return int(text)
        page=number('page',1,100000);size=number('pageSize',50,100)
        where=['class_id=?'];args=[cid]
        for key,column in [('status','status'),('serverId','server_id'),('userId','user_id'),('conversationId','conversation_id'),('messageId','message_id'),('tool_ref','tool_ref')]:
            item=value(key)
            if not item:continue
            if len(item)>200 or (key=='status' and item not in ('ok','denied','error')):raise ValidationError('审计过滤值无效')
            if key in ('serverId','messageId'):item=number(key,1,999999999)
            where.append(column+'=?');args.append(item)
        condition=' AND '.join(where)
        total=db.execute('SELECT count(*) FROM mcp_tool_calls WHERE '+condition,args).fetchone()[0]
        calls=store.rows(db,'SELECT * FROM mcp_tool_calls WHERE '+condition+' ORDER BY id DESC LIMIT ? OFFSET ?',args+[size,(page-1)*size])
        return self.send_json({'success':True,'calls':calls,'page':page,'pageSize':size,'total':total})

    def mcp_class(self,db,cid):
        if not isinstance(cid,str) or not cid:raise ValidationError('请先选择已准备的服务端班级')
        if not db.execute('SELECT 1 FROM classes WHERE id=? AND teacher=?',(cid,self.auth_payload['sub'])).fetchone():raise HostError()

    def mcp_item(self,db,ident):
        if not ident or not re.fullmatch(r'[1-9][0-9]{0,18}',ident) or int(ident)>2**63-1:raise HostError()
        row=db.execute('SELECT * FROM mcp_servers WHERE id=?',(int(ident),)).fetchone()
        if not row:raise HostError()
        self.mcp_class(db,row['class_id'])
        return row

    def mcp_dispatch(self,db,method,parts,query,data):
        ident,action=parts
        if action and not ident:raise HostError()
        row=self.mcp_item(db,ident) if ident else None
        cid=row['class_id'] if row else (data.get('classId') if method=='POST' else (query.get('classId') or [''])[0])
        self.mcp_class(db,cid)
        if method=='GET':
            if action=='tools':
                tools=[]
                if models.connected(row):
                    for tool in db.execute('SELECT * FROM mcp_tools WHERE server_id=? AND class_id=? ORDER BY name',(row['id'],cid)):
                        tools.append({'server_id':row['id'],'class_id':cid,'name':tool['name'],'description':tool['description'],
                                      'inputSchema':json.loads(tool['input_schema']),'enabled':bool(tool['enabled']),
                                      'available':bool(tool['enabled']),'reference':tool['name']+'@'+row['server_key']})
                return self.send_json({'success':True,'tools':tools})
            if action:raise HostError('方法不允许',405)
            if row:return self.send_json({'success':True,'server':models.public_server(row)})
            return self.send_json({'success':True,'servers':[models.public_server(r) for r in db.execute('SELECT * FROM mcp_servers WHERE class_id=? ORDER BY id',(cid,))]})
        if method=='DELETE' and row and not action:
            db.execute('DELETE FROM mcp_servers WHERE id=?',(row['id'],));db.commit()
            return self.send_json({'success':True})
        if action in ('connect','disconnect') and method=='POST':
            if data:raise ValidationError('连接和断开接口不接受自定义工具或其他参数')
            revision=row['revision']+1
            status='connecting' if action=='connect' else 'disconnected'
            db.execute("UPDATE mcp_servers SET status=?,error_summary='',process_epoch=?,revision=? WHERE id=?",(status,models.PROCESS_EPOCH,revision,row['id']))
            db.execute('DELETE FROM mcp_tools WHERE server_id=?',(row['id'],));db.commit()
            if action=='disconnect':return self.send_json({'success':True})
            try:
                tools=MCPClient(row['base_url'],unprotect(row['token_blob'])).discover()
            except (MCPError,SecretError) as error:
                db.execute("UPDATE mcp_servers SET status='error',error_summary=? WHERE id=? AND revision=?",(str(error),row['id'],revision));db.commit()
                raise HostError(str(error),502) from None
            stamp=datetime.now(timezone.utc).isoformat()
            if not db.execute("UPDATE mcp_servers SET status='connected',last_discovered_at=?,error_summary='' WHERE id=? AND revision=? AND status='connecting'",(stamp,row['id'],revision)).rowcount:
                raise HostError('连接期间服务器配置已改变，请重试',409)
            db.executemany('INSERT INTO mcp_tools(server_id,class_id,name,description,input_schema) VALUES(?,?,?,?,?)',[(row['id'],cid,t['name'],t['description'],json.dumps(t['inputSchema'],ensure_ascii=False)) for t in tools])
            db.commit()
            return self.send_json({'success':True,'server':models.public_server(db.execute('SELECT * FROM mcp_servers WHERE id=?',(row['id'],)).fetchone()),'tool_count':len(tools)})
        if (method=='POST' and not row and not action) or (method=='PUT' and row and not action):
            allowed={'classId','name','base_url','auth_token','server_key'}
            if set(data)-allowed:raise ValidationError('存在未允许的配置字段；工具清单只能来自发现')
            if row and 'classId' in data and data['classId']!=cid:raise ValidationError('不能更改服务器所属班级')
            name=data.get('name');key=data.get('server_key',row['server_key'] if row else '')
            if not isinstance(name,str) or not name.strip() or len(name.strip())>64:raise ValidationError('服务器名称不能为空且最多64字')
            if not isinstance(key,str) or not SERVER_KEY.fullmatch(key):raise ValidationError('稳定标识须为小写字母开头，最多64位小写字母数字下划线或连字符')
            if row and key!=row['server_key']:raise ValidationError('服务器稳定标识不可修改；显示名称可以修改')
            url=validate_url(data.get('base_url'))
            token=data.get('auth_token')
            blob=protect(token) if token is not None else (row['token_blob'] if row else None)
            if blob is None:raise ValidationError('登记服务器必须配置专用令牌')
            credential=token if token is not None else unprotect(row['token_blob'])
            if credential in name or credential in key or credential in url:raise ValidationError('公开配置不能包含认证凭据')
            if row:
                db.execute("UPDATE mcp_servers SET name=?,base_url=?,token_blob=?,status='disconnected',process_epoch=?,revision=revision+1,error_summary='' WHERE id=?",(name.strip(),url,blob,models.PROCESS_EPOCH,row['id']))
                db.execute('DELETE FROM mcp_tools WHERE server_id=?',(row['id'],));identifier=row['id']
            else:
                identifier=db.execute('INSERT INTO mcp_servers(class_id,server_key,name,base_url,token_blob,process_epoch) VALUES(?,?,?,?,?,?)',(cid,key,name.strip(),url,blob,models.PROCESS_EPOCH)).lastrowid
            db.commit()
            row=db.execute('SELECT * FROM mcp_servers WHERE id=?',(identifier,)).fetchone()
            return self.send_json({'success':True,'id':identifier,'server':models.public_server(row)},201 if method=='POST' else 200)
        raise HostError('方法不允许',405)
