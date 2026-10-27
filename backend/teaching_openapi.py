"""Stage-one configuration API definitions. Existing paths are preserved."""
def add_teaching_docs(schemas, paths):
    string = {'type':'string'}
    integer = {'type':'integer','minimum':1}
    bindings = {'skill_ids':{'type':'array','maxItems':1000,'items':integer},
                'material_ids':{'type':'array','maxItems':1000,'items':string}}
    def obj(properties, required=()):
        return {'type':'object','properties':properties,'required':list(required)}
    fields = {'name':{'type':'string','minLength':1,'maxLength':64},
              'prompt':{'type':'string','maxLength':2000,'default':''},
              'enabled':{'type':'boolean','default':True}, **bindings}
    schemas['AgentInput'] = obj({'classId':string,**fields},('classId','name','skill_ids','material_ids'))
    schemas['AgentUpdate'] = obj(fields,('name','skill_ids','material_ids'))
    schemas['AgentBindings'] = obj(bindings,('skill_ids','material_ids'))
    schemas['Agent'] = obj({'id':integer,'class_id':string,**fields,'effective_prompt':string})
    schemas['TeachingSkillInput'] = obj({'classId':string,'source':{'type':'string','maxLength':8000}},('classId','source'))
    schemas['TeachingSkillUpdate'] = {'oneOf':[
        obj({'source':{'type':'string','maxLength':8000}},('source',)),
        obj({'enabled':{'type':'boolean'}},('enabled',))]}
    schemas['TeachingSkill'] = obj({'id':integer,'class_id':string,'name':{'type':'string','maxLength':32},
        'trigger_text':{'type':'string','maxLength':120},'description':{'type':'string','maxLength':2000},
        'subject_text':{'type':'string','maxLength':32},'source_text':{'type':'string','maxLength':8000},
        'enabled':{'type':'boolean'},'tools':{'type':'array','items':{'type':'string','enum':['knowledge_search']}},
        'tools_json':string,'seed_key':{'type':'string','nullable':True}})
    def result(key, schema, many=False, ident=False):
        ref={'$ref':'#/components/schemas/'+schema}
        props={'success':{'type':'boolean'},key:({'type':'array','items':ref} if many else ref)}
        if ident: props['id']=integer
        return obj(props)
    def op(path, method, summary, response=None, body=None, create=False, query=False):
        parameters=[]
        if '{id}' in path: parameters.append({'name':'id','in':'path','required':True,'schema':integer})
        if query: parameters.append({'name':'classId','in':'query','required':True,'schema':string})
        value={'tags':['智能体与独立技能（第一阶段）'],'summary':summary,'security':[{'BearerAuth':[]}],
               'parameters':parameters,'responses':{}}
        value['responses']['201' if create else '200']={'description':'成功','content':{'application/json':{'schema':response or obj({'success':{'type':'boolean'}})}}}
        for code,desc in [('400','字段或文件无效、班内同名'),('401','令牌缺失或无效'),('403','仅教师可写'),('404','不存在、他班或学生访问未启用智能体，响应一致'),('405','方法不允许')]:
            value['responses'][code]={'description':desc,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Error'}}}}
        if body: value['requestBody']={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/'+body}}}}
        paths.setdefault(path,{})[method]=value
    op('/agents','get','列出班级智能体；学生仅见启用项',result('agents','Agent',True),query=True)
    op('/agents','post','教师创建智能体及本班绑定；空提示词回退默认角色',result('agent','Agent',ident=True),'AgentInput',True)
    op('/agents/{id}','get','读取智能体及实时有效绑定',result('agent','Agent'))
    op('/agents/{id}','put','教师修改名称、角色、启停及完整绑定',result('agent','Agent',ident=True),'AgentUpdate')
    op('/agents/{id}','delete','教师删除智能体及绑定；不修改旧聊天')
    op('/agents/{id}/bindings','get','读取智能体及实时有效技能/材料绑定',result('agent','Agent'))
    op('/agents/{id}/bindings','put','教师原子替换绑定；空数组表示解绑',result('agent','Agent',ident=True),'AgentBindings')
    op('/teaching-skills','get','列出独立技能（保留旧 GET /skills 的 prompts 返回）',result('skills','TeachingSkill',True),query=True)
    op('/teaching-skills','post','教师提交粘贴或 UTF-8 文件原文创建技能',result('skill','TeachingSkill',ident=True),'TeachingSkillInput',True)
    op('/teaching-skills/{id}','get','读取本班技能及 source_text 原文',result('skill','TeachingSkill'))
    op('/teaching-skills/{id}','put','教师替换 source，或仅提交 enabled 启停并同步原文',result('skill','TeachingSkill',ident=True),'TeachingSkillUpdate')
    op('/teaching-skills/{id}','delete','教师删除技能并级联解绑')
