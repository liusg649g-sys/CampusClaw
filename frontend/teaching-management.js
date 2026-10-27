'use strict';
(() => {
 const get=id=>document.getElementById(id);
 const sample='名称：数学解题引导\n适用条件：方程,去括号,分数,通分\n资料：数学\n工具：knowledge_search\n启用：是\n\n先了解学生卡在哪一步，只提示下一步应检查什么，不直接给出最终答案。';
 let agents=[], independentSkills=[], materials=[], agentId=null, skillId=null, version=0;
 const cid=()=>get('classSelect').value;
 function feedback(text,failed=false){const node=get('teachingFeedback');node.textContent=text;node.style.color=failed?'#8e2635':'#20633a';}
 function checkClass(){if(!cid())throw Error('请先在上方创建或导入服务端班级，再进行管理。');}
 function selectedAgent(){const item=agents.find(a=>a.id===agentId);if(!item)throw Error('请先选择智能体');return item;}
 function selectedSkill(){const item=independentSkills.find(s=>s.id===skillId);if(!item)throw Error('请先选择独立技能');return item;}
 function checks(container,items,selected){get(container).replaceChildren(...items.map(item=>{const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=String(item.id);input.checked=selected.map(String).includes(String(item.id));input.style.width='auto';label.append(input,document.createTextNode(' '+item.name));return label;}));}
 function checked(container,numeric){return Array.from(get(container).querySelectorAll('input:checked')).map(i=>numeric?Number(i.value):i.value);}
 function bindOptions(agent){checks('agentSkillBindings',independentSkills.map(s=>({id:s.id,name:s.name+(s.enabled?'':'（已停用）')})),agent?.skill_ids||[]);checks('agentMaterialBindings',materials.map(m=>({id:m.id,name:m.title+' · '+m.fileName})),agent?.material_ids||[]);}
 function editAgent(id){agentId=id;const item=agents.find(a=>a.id===id);get('agentFormTitle').textContent=item?'编辑智能体 #'+item.id:'新建智能体';get('agentName').value=item?.name||'';get('agentPrompt').value=item?.prompt||'';get('agentEnabled').checked=item?item.enabled:true;get('agentEffectivePrompt').textContent=item?'当前有效角色：'+item.effective_prompt:'留空时将在服务端回退默认角色。';get('agentList').value=item?String(id):'';bindOptions(item);}
 function editSkill(id){skillId=id;const item=independentSkills.find(s=>s.id===id);get('teachingSkillFormTitle').textContent=item?'编辑独立技能 #'+item.id:'新建独立技能';get('teachingSkillSource').value=item?.source_text||sample;get('teachingSkillList').value=item?String(id):'';get('teachingSkillFile').value='';get('teachingSkillParsed').textContent=item?JSON.stringify({名称:item.name,适用条件:item.trigger_text,资料范围:item.subject_text,工具:item.tools,启用:item.enabled?'是':'否',说明:item.description},null,2):'保存后显示服务端解析结果。';}
 async function load(keep=true){
  const stamp=++version, classId=cid();
  get('teachingManagement').classList.toggle('hidden',!user||user.role!=='教师');
  if(!user||user.role!=='教师')return;
  if(!classId){agents=[];independentSkills=[];materials=[];get('agentList').replaceChildren();get('teachingSkillList').replaceChildren();editAgent(null);editSkill(null);get('teachingPreparation').textContent='尚无服务端班级。请先使用上方“保存班级”或“导入本浏览器已有班级”，本管理区不会自动创建班级。';return;}
  get('teachingPreparation').textContent='当前班级：'+get('classSelect').selectedOptions[0].textContent+'。配置立即保存；学生智能体会话下一轮使用最新角色、技能及有效材料绑定。';
  const responses=await Promise.all([api('/agents?classId='+encodeURIComponent(classId)),api('/teaching-skills?classId='+encodeURIComponent(classId)),api('/materials?classId='+encodeURIComponent(classId))]);
  if(stamp!==version||cid()!==classId||user?.role!=='教师')return;
  agents=responses[0].agents;independentSkills=responses[1].skills;materials=responses[2].materials;
  get('agentList').replaceChildren(...agents.map(a=>new Option(a.name+(a.enabled?'（启用）':'（停用）'),a.id)));
  get('teachingSkillList').replaceChildren(...independentSkills.map(s=>new Option(s.name+(s.enabled?'（启用）':'（停用）'),s.id)));
  editAgent(keep&&agents.some(a=>a.id===agentId)?agentId:null);
  editSkill(keep&&independentSkills.some(s=>s.id===skillId)?skillId:null);
 }
 function action(id,fn){get(id).onclick=async()=>{const classId=cid();get(id).disabled=true;feedback('');try{checkClass();await fn(classId);}catch(e){feedback(e.message,true);}finally{get(id).disabled=false;}};}
 function agentData(item){return item?{name:item.name,prompt:item.prompt,enabled:item.enabled,skill_ids:item.skill_ids,material_ids:item.material_ids}:{name:get('agentName').value,prompt:get('agentPrompt').value,enabled:get('agentEnabled').checked,skill_ids:checked('agentSkillBindings',true),material_ids:checked('agentMaterialBindings',false)};}
 window.refreshTeachingManagement=()=>load(false);
 get('agentList').onchange=()=>editAgent(Number(get('agentList').value));
 get('teachingSkillList').onchange=()=>editSkill(Number(get('teachingSkillList').value));
 get('agentNew').onclick=()=>{editAgent(null);feedback('请填写新智能体，保存后生效。');};
 get('teachingSkillNew').onclick=()=>{editSkill(null);feedback('请粘贴或上传技能文件，保存后生效。');};
 action('teachingRefresh',async()=>{await load();feedback('管理数据已刷新。');});
 action('agentSave',async classId=>{const result=await api('/agents'+(agentId?'/'+agentId:''),agentId?'PUT':'POST',{classId,...agentData()});agentId=result.id;await load();feedback('智能体及绑定已保存。');});
 action('agentToggle',async()=>{const item=selectedAgent();await api('/agents/'+item.id,'PUT',{...agentData(item),enabled:!item.enabled});await load();feedback('智能体启停状态已保存。');});
 action('agentDelete',async()=>{const item=selectedAgent();if(!confirm('删除智能体“'+item.name+'”及其绑定？旧提示词会话不受影响。'))return;await api('/agents/'+item.id,'DELETE');agentId=null;await load();feedback('智能体已删除。');});
 action('teachingSkillSave',async classId=>{const result=await api('/teaching-skills'+(skillId?'/'+skillId:''),skillId?'PUT':'POST',{classId,source:get('teachingSkillSource').value});skillId=result.id;await load();feedback('技能文件已解析并保存。');});
 action('teachingSkillToggle',async()=>{const item=selectedSkill();await api('/teaching-skills/'+item.id,'PUT',{enabled:!item.enabled});await load();feedback('技能启停状态和原文已同步保存。');});
 action('teachingSkillDelete',async()=>{const item=selectedSkill();if(!confirm('删除技能“'+item.name+'”？其智能体绑定将同时解除。'))return;await api('/teaching-skills/'+item.id,'DELETE');skillId=null;await load();feedback('技能及其绑定已删除。');});
 get('teachingSkillFile').onchange=async()=>{try{checkClass();const file=get('teachingSkillFile').files[0];if(!file)return;if(file.size>32003)throw Error('技能文件过大，请使用不超过8000字的 UTF-8 文本');const source=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());if(source.length>8000)throw Error('技能文件不能超过8000字');get('teachingSkillSource').value=source;feedback('文件已读取，请点击“保存技能文件”进行服务端校验。');}catch(e){feedback('文件读取失败：'+e.message,true);}};
 if(user)load(false).catch(e=>feedback(e.message,true));
})();
