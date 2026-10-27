"""OpenAPI for the actual standard-library handler routes."""
def specification():
    from teaching_openapi import add_teaching_docs
    string={'type':'string'}
    def obj(fields,required=()):
        return {'type':'object','properties':{key:(value if isinstance(value,dict) else string) for key,value in fields.items()},'required':list(required)}
    schemas={
        'Error':obj({'success':{'type':'boolean'},'message':string},('success','message')),
        'Login':obj({'username':string,'password':string},('username','password')),
        'LoginResult':obj({'success':{'type':'boolean'},'token':string,'expiresIn':{'type':'integer'},'username':string,'name':string,'role':string},('success','token')),
        'Class':obj({'id':string,'name':string,'teacher':string},('id','name')),
        'Student':obj({'username':string,'password':{'type':'string','minLength':6},'name':string,'classId':string},('username','password','name','classId')),
        'Prompt':obj({'id':string,'classId':string,'name':string,'content':string,'skill':{'type':'string','enum':['解题引导']},'teacher':string},('classId','name','content')),
        'ConversationInput':obj({'classId':string,'promptId':string},('classId','promptId')),
        'Question':obj({'question':{'type':'string','minLength':1,'maxLength':2000}},('question',)),
        'Source':obj({'ref':{'type':'integer'},'materialId':string,'classId':string,'sourceFile':string,'page':{'type':'integer','nullable':True},'chunkIndex':{'type':'integer'},'text':string}),
        'MaterialInput':obj({'classId':string,'title':string,'fileName':string,'type':string,'dataBase64':string,'replaceFile':{'type':'boolean'}},('classId','title','fileName','dataBase64')),
    }
    schemas['Conversation']=obj({'id':string,'student':string,'classId':string,'promptId':string,'skill':string,'createdAt':string})
    schemas['Message']=obj({'id':{'type':'integer'},'conversationId':string,'role':{'type':'string','enum':['user','assistant']},'content':string,'status':{'type':'string','enum':['complete','failed','interrupted','generating']},'sources':{'type':'array','items':{'$ref':'#/components/schemas/Source'}},'createdAt':string})
    schemas['Material']=obj({'id':string,'classId':string,'title':string,'fileName':string,'type':string,'size':{'type':'integer'},'time':string,'isMd':{'type':'boolean'},'knowledgeIndexed':{'type':'boolean'},'text':string})
    paths={}
    def operation(path,method,summary,body=None,query=(),public=False,code='200',response=None,stream=False):
        parameters=[{'name':name,'in':'path','required':True,'schema':string} for name in __import__('re').findall(r'\{(.*?)\}',path)]
        parameters += [{'name':name.rstrip('?'),'in':'query','required':not name.endswith('?'),'schema':string} for name in query]
        content={'application/json':{'schema':response or {'type':'object','properties':{'success':{'type':'boolean'}}}}}
        if stream:
            content={'text/event-stream':{'schema':{'type':'string'},'example':'event: start\ndata: {"messageId":1}\n\nevent: delta\ndata: {"text":"请思考 [1]"}\n\nevent: sources\ndata: {"sources":[]}\n\nevent: done\ndata: {"status":"complete"}\n\n'}}
        op={'summary':summary,'security':[] if public else [{'BearerAuth':[]}],'parameters':parameters,'responses':{code:{'description':'成功；流开始后错误使用 error 事件，失败回答不会标记完成。' if stream else '成功','content':content}}}
        for status,description in [('400','参数无效'),('401','Bearer 缺失、无效或过期'),('403','角色、班级或所有者权限不足'),('404','资源不存在'),('409','已存在或会话正在生成'),('502','模型或引用错误'),('503','服务未配置或不可用'),('504','模型超时')]:
            op['responses'][status]={'description':description,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Error'}}}}
        if body:
            schema={'$ref':'#/components/schemas/'+body} if isinstance(body,str) else body
            op['requestBody']={'required':True,'content':{'application/json':{'schema':schema}}}
        paths.setdefault(path,{})[method.lower()]=op
    def array_response(key,schema=None):
        return obj({'success':{'type':'boolean'},key:{'type':'array','items':{'$ref':'#/components/schemas/'+schema} if schema else {'type':'object'}}})
    operation('/login','POST','教师或学生登录','Login',public=True,response={'$ref':'#/components/schemas/LoginResult'})
    for p in ['/health','/app-version','/openapi.json','/docs']: operation(p,'GET','公开服务信息或接口文档',public=True)
    operation('/logout','POST','退出（客户端删除令牌）',public=True)
    operation('/session','GET','当前服务端身份')
    operation('/change-password','POST','教师修改密码',obj({'oldPassword':string,'newPassword':string},('oldPassword','newPassword')))
    operation('/classes','GET','本人管理或加入的班级',response=array_response('classes','Class'))
    operation('/classes','POST','教师创建或导入班级','Class',code='201')
    operation('/students','POST','教师创建学生并加入班级','Student',code='201')
    operation('/classes/{id}','POST','教师添加已有学生为班级成员',obj({'username':string},('username',)),code='201')
    for p in ['/prompts','/skills']: operation(p,'GET','当前班级提示词与解题引导技能',query=['classId'],response=array_response('prompts','Prompt'))
    operation('/prompts','POST','教师创建提示词','Prompt',code='201')
    operation('/prompts/{id}','GET','教师查看提示词',response=obj({'success':{'type':'boolean'},'prompt':{'$ref':'#/components/schemas/Prompt'}}))
    operation('/prompts/{id}','PUT','教师修改提示词（已有会话保留创建时快照）',obj({'name':string,'content':string},('name','content')))
    operation('/prompts/{id}','DELETE','教师删除提示词')
    operation('/conversations','POST','学生创建私有会话','ConversationInput',code='201')
    operation('/conversations','GET','学生本人会话历史',response=array_response('conversations'))
    for p in ['/conversations/{id}','/conversations/{id}/messages']:
        operation(p,'GET','本人会话与消息（status 标明 complete/failed/interrupted/generating）',response=array_response('messages'))
    operation('/conversations/{id}/messages','POST','学生提交问题；SSE start、delta、sources、done 或 error；fetch 携带 Bearer。无数据不调用模型。','Question',stream=True)
    operation('/knowledge/search','GET','本班混合检索',query=['classId','q'],response=array_response('results','Source'))
    operation('/knowledge/answer','POST','原有单次问答；无数据 answered=false',obj({'classId':string,'question':string},('classId','question')),response=obj({'success':{'type':'boolean'},'answered':{'type':'boolean'},'answer':string,'sources':{'type':'array','items':{'$ref':'#/components/schemas/Source'}}}))
    operation('/materials','GET','有权访问的班级材料',query=['classId?','q?'],response=array_response('materials'))
    operation('/materials','POST','教师上传材料','MaterialInput',code='201')
    operation('/materials','DELETE','教师删除指定班级材料',query=['classId'])
    operation('/materials/{id}','GET','读取有权访问的材料')
    operation('/materials/{id}','PUT','教师修改材料',obj({'title':string,'replaceFile':{'type':'boolean'},'fileName':string,'type':string,'dataBase64':string}))
    operation('/materials/{id}','DELETE','教师删除材料')
    operation('/materials/{id}/download','GET','下载有权访问的原文件')
    paths['/materials/{id}/download']['get']['responses']['200']['content']={'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}
    for p in ['/classes','/prompts','/conversations']:
        paths[p]['post']['responses']['201']['content']['application/json']['schema']=obj({'success':{'type':'boolean'},'id':string},('success','id'))
    paths['/students']['post']['responses']['201']['content']['application/json']['schema']=obj({'success':{'type':'boolean'},'username':string})
    for p in ['/conversations/{id}','/conversations/{id}/messages']:
        paths[p]['get']['responses']['200']['content']['application/json']['schema']=obj({'success':{'type':'boolean'},'conversation':{'$ref':'#/components/schemas/Conversation'},'messages':{'type':'array','items':{'$ref':'#/components/schemas/Message'}}})
    paths['/conversations']['get']['responses']['200']['content']['application/json']['schema']=array_response('conversations','Conversation')
    paths['/materials']['get']['responses']['200']['content']['application/json']['schema']=array_response('materials','Material')
    add_teaching_docs(schemas, paths)
    from mcp_openapi import add_mcp_docs
    add_mcp_docs(schemas,paths)
    schemas['ConversationInput']={'oneOf':[
        obj({'classId':string,'agentId':{'type':'integer','minimum':1}},('classId','agentId')),
        obj({'classId':string,'promptId':string},('classId','promptId'))],
        'description':'二选一；不得同时提交 agentId 和 promptId。班级必须是当前学生已加入的班级。'}
    schemas['Conversation']['properties'].update({'agentId':{'type':'integer','nullable':True},
        'title':{'type':'string','nullable':True},'updated_at':{'type':'string','nullable':True},
        'promptId':{'type':'string','nullable':True}})
    schemas['Source']['properties'].update({'title':string,'excerpt':string})
    schemas['Message']['properties']['skill_name']={'type':'string','nullable':True}
    stream=paths['/conversations/{id}/messages']['post']
    stream['summary']='学生提问：agentId 会话 meta/delta/done；旧 promptId 会话 start/delta/sources/done'
    stream['description']='智能体问题2至500字；旧promptId问题继续允许1至2000字。智能体每轮读取当前角色/技能/有效绑定，绑定范围内取前4片段后按学科过滤；未命中仍调用模型。旧会话无资料保持原提示。请求中 agentId/classId 不改变已存会话。流开始后失败发 error，不发 done。引用为本轮提供给模型的有效候选来源，不代表已核实模型每句话。'
    stream['description']+=' 命中MCP技能时使用受限工具决策循环；meta首个并含agent/skill/citations，每次调用后追加meta.tool_calls累计安全状态，未调用则省略tool_calls；兼容tool_status事件，均在delta正文前，持久化后done。knowledge_search保留前置RAG，不重复作为模型工具。'
    schemas['ToolStatus']=obj({'reference':string,'status':{'type':'string','enum':['ok','denied','error']},'description':string,'round':{'type':'integer'},'auditId':{'type':'integer'}})
    schemas['AgentMeta']=obj({'status':string,'agent':obj({'id':{'type':'integer'},'name':string}),
        'skill':{'type':'object','nullable':True,'properties':{'name':string}},
        'citations':{'type':'array','items':{'$ref':'#/components/schemas/Source'}},
        'tool_calls':{'type':'array','items':{'$ref':'#/components/schemas/ToolStatus'}}},('status','agent','skill','citations'))
    schemas['Message']['properties']['tool_calls']={'type':'array','items':{'$ref':'#/components/schemas/ToolStatus'}}
    stream['responses']['200']['content']['text/event-stream']['examples']={
        'agent':{'value':'event: meta\ndata: {"status":"ok","skill":null,"citations":[]}\n\nevent: delta\ndata: {"text":"请先分析条件"}\n\nevent: done\ndata: {"messageId":2,"status":"complete"}\n\n'},
        'legacy':{'value':stream['responses']['200']['content']['text/event-stream'].pop('example')}}
    stream['responses']['200']['content']['text/event-stream']['examples']['agent-tools']={'value':'event: meta\ndata: {"status":"ok","skill":{"name":"计算技能"},"citations":[]}\n\nevent: tool_status\ndata: {"reference":"calculator@local","status":"ok","description":"工具调用完成","round":1,"auditId":1}\n\nevent: delta\ndata: {"text":"依据工具结果分析"}\n\nevent: done\ndata: {"messageId":2,"status":"complete"}\n\n'}
    import json
    meta={'status':'ok','agent':{'id':1,'name':'计算助手'},'skill':{'name':'计算技能'},'citations':[]}
    call={'reference':'calculator@local','status':'ok','description':'工具调用完成','round':1,'auditId':1}
    frames=[('meta',meta),('meta',dict(meta,tool_calls=[call])),('tool_status',call),('delta',{'text':'依据工具结果分析'}),('done',{'messageId':2,'status':'complete'})]
    stream['responses']['200']['content']['text/event-stream']['examples']['agent-tools']['value']=''.join('event: '+event+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n' for event,data in frames)
    paths['/docs']['get']['responses']['200']['content']={'text/html':{'schema':string}}
    paths['/swagger'] = paths['/docs']
    paths['/swagger/'] = paths['/docs']
    for p,methods in [('/materials',['post']),('/materials/{id}',['get','put'])]:
        for method in methods:
            status='201' if method=='post' else '200'
            paths[p][method]['responses'][status]['content']['application/json']['schema']=obj({'success':{'type':'boolean'},'material':{'$ref':'#/components/schemas/Material'}})
    return {'openapi':'3.0.3','info':{'title':'CampusClaw API','version':'5.0','description':'现有教师管理浏览器班级仍兼容；学生必须由教师创建账号和服务端班级成员关系。Swagger 静态资源需要访问 unpkg.com。'},'servers':[{'url':'/'}],'components':{'securitySchemes':{'BearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'JWT'}},'schemas':schemas},'paths':paths}
