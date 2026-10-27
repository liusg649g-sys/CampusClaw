'use strict';
const el=id=>document.getElementById(id);
let token=sessionStorage.getItem('campusclaw_assistant_token')||'', user=null, skills=[], conversation=null, controller=null;
function error(message=''){el('error').textContent=message;}
async function api(path,method='GET',data){
 const response=await fetch(path,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:data===undefined?undefined:JSON.stringify(data)});
 const payload=await response.json();
 if(!response.ok){if(response.status===401){token='';sessionStorage.removeItem('campusclaw_assistant_token');showLogin();}throw Error(payload.message||'请求失败');}return payload;
}
function showLogin(){el('login').classList.remove('hidden');el('workspace').classList.add('hidden');}
function bind(id,action){el(id).onclick=async()=>{error();el(id).disabled=true;try{await action();}catch(e){error(e.message);}finally{el(id).disabled=false;}};}
async function start(){user=await api('/session');el('identity').textContent=user.name+' · '+user.role;el('login').classList.add('hidden');for(const id of ['teacher','prompts'])el(id).classList.toggle('hidden',user.role!=='教师');el('student').classList.toggle('hidden',user.role!=='学生');await refresh();el('workspace').classList.remove('hidden');}
async function refresh(){const old=el('classSelect').value;const data=await api('/classes');el('classSelect').replaceChildren(...data.classes.map(c=>new Option(c.name,c.id)));if(data.classes.some(c=>c.id===old))el('classSelect').value=old;await loadSkills();if(user.role==='学生')await history();if(window.refreshTeachingManagement)await window.refreshTeachingManagement();}
async function loadSkills(){await loadAgents();skills=[];el('skillSelect').replaceChildren();if(!el('classSelect').value)return;const data=await api('/skills?classId='+encodeURIComponent(el('classSelect').value));skills=data.prompts;el('skillSelect').replaceChildren(...skills.map(p=>new Option(p.name+' · '+p.skill,p.id)));selectPrompt();}
function selectPrompt(){const p=skills.find(p=>p.id===el('skillSelect').value);if(p&&user.role==='教师'){el('promptName').value=p.name;el('promptContent').value=p.content;}}
el('classSelect').onchange=()=>loadSkills().then(()=>window.refreshTeachingManagement?.()).catch(e=>error(e.message));el('skillSelect').onchange=selectPrompt;
bind('loginButton',async()=>{const result=await api('/login','POST',{username:el('username').value,password:el('password').value});token=result.token;sessionStorage.setItem('campusclaw_assistant_token',token);el('password').value='';await start();});
bind('logoutButton',async()=>{if(controller)controller.abort();token='';user=null;conversation=null;sessionStorage.removeItem('campusclaw_assistant_token');showLogin();});
bind('refreshButton',refresh);
bind('importButton',async()=>{const classes=JSON.parse(localStorage.getItem('courseClassesV2')||'[{"id":"default","name":"互联网软件开发技术与实践"}]');for(const c of classes)await api('/classes','POST',{id:c.id,name:c.name});await refresh();error('已有班级已导入。');});
bind('classButton',async()=>{await api('/classes','POST',{id:el('classId').value,name:el('className').value});await refresh();el('workspace').classList.remove('hidden');});
bind('studentButton',async()=>{await api('/students','POST',{classId:el('classSelect').value,username:el('studentUsername').value,name:el('studentName').value,password:el('studentPassword').value});el('studentPassword').value='';error('学生账号创建成功。');});
bind('memberButton',async()=>{await api('/classes/'+encodeURIComponent(el('classSelect').value),'POST',{username:el('memberUsername').value});error('学生已加入所选班级。');});
function promptData(){return {classId:el('classSelect').value,name:el('promptName').value,content:el('promptContent').value,skill:'解题引导'};}
bind('promptCreate',async()=>{await api('/prompts','POST',promptData());await loadSkills();});
bind('promptEdit',async()=>{if(!el('skillSelect').value)throw Error('请选择提示词');await api('/prompts/'+el('skillSelect').value,'PUT',promptData());await loadSkills();});
bind('promptDelete',async()=>{if(!el('skillSelect').value)throw Error('请选择提示词');if(!confirm('删除此提示词？已有会话保留提示词快照。'))return;await api('/prompts/'+el('skillSelect').value,'DELETE');await loadSkills();});
async function history(){const data=await api('/conversations');const active=conversation&&data.conversations.find(c=>c.id===conversation.id);if(active?.agentId){conversation={...conversation,...active};el('conversationTitle').textContent=conversation.title+' · '+conversation.classId+' · 智能体 #'+conversation.agentId;}el('history').replaceChildren(...data.conversations.map(c=>{const b=document.createElement('button');b.textContent=(c.title||c.skill)+' · '+(c.updated_at||c.createdAt);b.onclick=()=>openConversation(c.id).catch(e=>error(e.message));return b;}));}
function append(role,content,status='complete'){const node=document.createElement('div');node.className='message';const label=document.createElement('strong');label.textContent=role==='user'?'你':'解题助手';const text=document.createElement('div');text.textContent=content;const meta=document.createElement('small');meta.textContent=status==='complete'?'':'状态：'+status;node.append(label,text,meta);el('messages').append(node);return {node,text,meta};}
function sources(node,items){const box=document.createElement('div');box.className='sources';for(const s of items){const p=document.createElement('p');p.textContent='['+s.ref+'] '+(s.title?s.title+' · ':'')+s.sourceFile+' · '+(s.page!=null?'第 '+s.page+' 页':'片段 '+s.chunkIndex)+'\n'+s.text;const b=document.createElement('button');b.textContent='下载原材料';b.onclick=async()=>{try{const r=await fetch('/materials/'+encodeURIComponent(s.materialId)+'/download',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error('下载失败或无权访问');const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=s.sourceFile;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e.message);}};p.append(b);box.append(p);}node.append(box);}
async function openConversation(id){if(controller)throw Error('请等待当前生成完成');const data=await api('/conversations/'+id+'/messages');conversation=data.conversation;el('conversationTitle').textContent=(conversation.title||conversation.skill)+' · '+conversation.classId+(conversation.agentId?' · 智能体 #'+conversation.agentId:' · 旧提示词');el('messages').replaceChildren();for(const m of data.messages){const view=append(m.role,m.content,m.status);if(m.role==='assistant'&&conversation.agentId)view.meta.textContent+=(m.skill_name?' · 技能：'+m.skill_name:' · 未命中技能');sources(view.node,m.sources);for(const call of m.tool_calls||[])toolStatus(view.node,call);}el('classSelect').value=conversation.classId;await loadSkills();if(!conversation.agentId){if(!skills.some(p=>p.id===conversation.promptId))el('skillSelect').add(new Option(conversation.skill+' · 历史提示词',conversation.promptId));el('skillSelect').value=conversation.promptId;}}
bind('newButton',async()=>{if(controller)throw Error('请等待当前生成完成');const input={classId:el('classSelect').value};if(el('conversationMode').value==='agent'){if(!el('studentAgentSelect').value)throw Error('本班暂无可用智能体，请联系教师启用智能体');input.agentId=Number(el('studentAgentSelect').value);}else input.promptId=el('skillSelect').value;const result=await api('/conversations','POST',input);await openConversation(result.id);await history();});
bind('sendButton',async()=>{
 if(!conversation)throw Error('请先创建或选择会话');const question=el('question').value.trim();if(!question)throw Error('请输入问题');if(conversation.agentId&&(question.length<2||question.length>500))throw Error('智能体问题须为2至500字');
 controller=new AbortController();const requestController=controller;el('stopButton').disabled=false;append('user',question);const view=append('assistant','','generating');let ended=false;
 const timeout=setTimeout(()=>requestController.abort(),150000);
 try{
  const response=await fetch('/conversations/'+conversation.id+'/messages',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({question}),signal:controller.signal});
  if(!response.ok){const data=await response.json();throw Error(data.message);}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done}).replace(/\r\n/g,'\n');let pos;
   while((pos=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,pos);buffer=buffer.slice(pos+2);const lines=block.split('\n'),event=lines.find(l=>l.startsWith('event:'))?.slice(6).trim();const data=JSON.parse(lines.filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trim()).join('\n')||'{}');
    if(event==='meta'){view.meta.textContent=data.skill?'技能：'+data.skill.name:'未命中技能';for(const box of view.node.querySelectorAll(':scope > .sources'))box.remove();sources(view.node,data.citations||[]);for(const call of data.tool_calls||[])toolStatus(view.node,call);}
    if(event==='delta')view.text.textContent+=data.text;
    if(event==='sources')sources(view.node,data.sources);
    if(event==='tool_status')toolStatus(view.node,data);
    if(event==='error')throw Error(data.message);
    if(event==='done'){ended=true;if(!conversation.agentId)view.meta.textContent='';el('question').value='';}
   }if(done)break;
  }if(!ended)throw Error('连接提前结束，回答未完成');
 }catch(e){view.meta.textContent='回答失败或中断，不能作为完整回答';throw Error(e.name==='AbortError'?'已停止或生成超时':e.message);}
 finally{clearTimeout(timeout);controller=null;el('stopButton').disabled=true;await history();}
});
el('stopButton').onclick=()=>controller?.abort();
if(token)start().catch(e=>{showLogin();error(e.message);});

async function loadAgents(){el('studentAgentSelect').replaceChildren();if(user?.role!=='学生'||!el('classSelect').value)return;const data=await api('/agents?classId='+encodeURIComponent(el('classSelect').value));el('studentAgentSelect').replaceChildren(...data.agents.map(a=>new Option(a.name,a.id)));el('agentHint').textContent=data.agents.length?'所选智能体仅用于新建会话':'本班暂无可用智能体，请联系教师完成配置并启用。';}

function toolStatus(node,data){let box=node.querySelector('.tool-status-list');if(!box){box=document.createElement('div');box.className='tool-status-list';node.insertBefore(box,node.children[1]);}const key=String(data.auditId??(data.reference+':'+data.round));let row=[...box.children].find(p=>p.dataset.callKey===key);if(!row){row=document.createElement('p');row.className='tool-status sources';row.dataset.callKey=key;box.append(row);}row.textContent='工具 '+data.reference+' · '+data.status+(data.description?' · '+data.description:'');}
