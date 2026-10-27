"""Teacher MCP registry documentation; never defines a model-execution endpoint."""
def add_mcp_docs(schemas,paths):
    string={'type':'string'};integer={'type':'integer','minimum':1}
    def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required)}
    fields={'classId':string,'server_key':{'type':'string','pattern':'^[a-z][a-z0-9_-]{0,63}$'},
            'name':{'type':'string','minLength':1,'maxLength':64},'base_url':string,
            'auth_token':{'type':'string','minLength':16,'maxLength':256,'writeOnly':True}}
    schemas['MCPServerCreate']=obj(fields,('classId','server_key','name','base_url','auth_token'))
    schemas['MCPServerUpdate']=obj(fields,('name','base_url'))
    schemas['MCPServer']=obj({'id':integer,'class_id':string,'server_key':string,'name':string,'base_url':string,
        'status':{'type':'string','enum':['disconnected','connecting','connected','error']},'connected':{'type':'boolean'},
        'auth_token_set':{'type':'boolean'},'last_discovered_at':{'type':'string','nullable':True},'error_summary':string})
    schemas['MCPTool']=obj({'server_id':integer,'class_id':string,'name':string,'description':string,'inputSchema':{'type':'object'},
        'reference':string,'enabled':{'type':'boolean'},'available':{'type':'boolean'}})
    operations=[('', 'get','列出本班服务器',None,'servers',True),('', 'post','登记服务器','MCPServerCreate','server',False),
        ('/{id}','get','读取本班服务器',None,'server',False),('/{id}','put','修改显示名称、地址或令牌；清除连接和缓存','MCPServerUpdate','server',False),
        ('/{id}','delete','删除服务器及工具缓存',None,None,False),('/{id}/connect','post','初始化、通知并发现；整体替换缓存',None,'server',False),
        ('/{id}/disconnect','post','断开并删除可用工具缓存',None,None,False),('/{id}/tools','get','查看当前进程有效连接发现的工具',None,'tools',True)]
    for suffix,method,summary,body,key,many in operations:
        properties={'success':{'type':'boolean'}}
        if key:
            schema={'$ref':'#/components/schemas/'+('MCPTool' if key=='tools' else 'MCPServer')}
            properties[key]={'type':'array','items':schema} if many else schema
        code='201' if suffix=='' and method=='post' else '200'
        parameters=[]
        if '{id}' in suffix:parameters.append({'name':'id','in':'path','required':True,'schema':integer})
        elif method=='get':parameters.append({'name':'classId','in':'query','required':True,'schema':string})
        operation={'tags':['MCP主机管理'],'summary':summary,'security':[{'BearerAuth':[]}],'parameters':parameters,
                   'responses':{code:{'description':'成功','content':{'application/json':{'schema':obj(properties)}}}}}
        for status,description in [('400','参数、地址或白名单无效'),('401','未登录'),('403','仅教师可访问'),('404','资源不存在或非本人班级'),('409','连接期间配置发生改变'),('502','远端握手/发现失败'),('503','存储不可用')]:operation['responses'][status]={'description':description}
        if body:operation['requestBody']={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/'+body}}}}
        paths.setdefault('/api/mcp/servers'+suffix,{})[method]=operation
    if 'TeachingSkill' in schemas:
        schemas['TeachingSkill']['properties']['tools']['items']={'type':'string','pattern':'^(knowledge_search|[a-z][a-z0-9_]{0,63}@[a-z][a-z0-9_-]{0,63})$'}
        schemas['TeachingSkill']['properties'].update({key:{'type':'array','items':string} for key in ('available_tools','unavailable_tools')})
    audit_fields={'id':integer,'class_id':string,'user_id':string,'conversation_id':string,'message_id':integer,
        'server_id':{'type':'integer','nullable':True},'server_name':string,'tool_name':string,'tool_ref':string,
        'status':{'type':'string','enum':['ok','denied','error']},'round':integer,'started_at':string,
        'duration_ms':{'type':'integer'},'error_summary':string,'arguments_hash':string}
    schemas['MCPAudit']=obj(audit_fields)
    parameters=[{'name':key,'in':'query','required':key=='classId','schema':
        ({'type':'integer','minimum':1,'maximum':100,'default':50} if key=='pageSize' else integer if key in ('page','serverId','messageId') else string)}
        for key in ('classId','page','pageSize','status','serverId','userId','conversationId','messageId','tool_ref')]
    paths['/api/mcp/tool-calls']={'get':{'summary':'教师查询本班工具调用审计；默认最近50条，支持过滤和分页',
        'tags':['MCP主机管理'],'security':[{'BearerAuth':[]}],'parameters':parameters,
        'responses':{'200':{'description':'成功；不包含原始参数或工具结果','content':{'application/json':{'schema':obj({
            'success':{'type':'boolean'},'calls':{'type':'array','items':{'$ref':'#/components/schemas/MCPAudit'}},
            'page':integer,'pageSize':integer,'total':{'type':'integer'}})}}},
            **{code:{'description':text} for code,text in [('400','过滤无效'),('401','未登录'),('403','非教师'),('404','班级不存在或不属于教师'),('503','审计不可用')]}}}}
