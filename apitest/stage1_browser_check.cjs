const testPassword=process.env.CAMPUSCLAW_TEST_PASSWORD;
if(!testPassword)throw Error('Use an isolated browser fixture; no test password configured');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const reports=process.env.CAMPUSCLAW_BROWSER_REPORT_DIR||path.join(__dirname,'reports');
const {url}=JSON.parse(fs.readFileSync(path.join(reports,'stage1-browser-fixture.json'),'utf8'));
const checks=[];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 const waitFeedback=text=>page.waitForFunction(text=>document.querySelector('#teachingFeedback').textContent.includes(text),text);
 const skillSource=(name,words,subject)=>`名称：${name}\n适用条件：${words}\n资料：${subject}\n工具：knowledge_search\n启用：是\n\n只给下一步提示，不直接给出最终答案。`;
 async function request(p,method='GET',data){const token=await page.evaluate(()=>sessionStorage.getItem('campusclaw_assistant_token'));const response=await page.request.fetch(url+p,{method,headers:{Authorization:'Bearer '+token},data});assert.ok(response.ok(),await response.text());return response.json();}
 async function createClass(id,name){await page.locator('#classId').fill(id);await page.locator('#className').fill(name);await page.locator('#classButton').click();await page.waitForFunction(id=>Array.from(document.querySelector('#classSelect').options).some(o=>o.value===id),id);}
 async function createSkill(name,source,upload=false){await page.locator('#teachingSkillNew').click();if(upload){await page.locator('#teachingSkillFile').setInputFiles({name:'skill.txt',mimeType:'text/plain',buffer:Buffer.from(source)});await waitFeedback('文件已读取');}else await page.locator('#teachingSkillSource').fill(source);await page.locator('#teachingSkillSave').click();await waitFeedback('技能文件已解析并保存');assert.ok((await page.locator('#teachingSkillParsed').textContent()).includes(name));}
 try{
  await page.goto(url+'/assistant.html');await page.locator('#username').fill('teacher');await page.locator('#password').fill(testPassword);await page.locator('#loginButton').click();await page.locator('#workspace').waitFor({state:'visible'});
  await page.getByText('尚无服务端班级。',{exact:false}).waitFor();
  assert.equal((await request('/classes')).classes.length,0);checks.push('未导入班级时明确提示且未自动建班');
  await createClass('a','浏览器验收班');
  await createSkill('数学解题引导',skillSource('数学解题引导','方程,去括号','数学'));
  await createSkill('语文解题引导',skillSource('语文解题引导','阅读,作文','语文'),true);checks.push('粘贴及上传技能文件均经真实后端解析保存');
  await page.locator('#teachingSkillToggle').click();await waitFeedback('技能启停状态和原文已同步保存');assert.ok((await page.locator('#teachingSkillSource').inputValue()).includes('启用：否'));
  await page.locator('#teachingSkillToggle').click();await waitFeedback('技能启停状态和原文已同步保存');
  const chinese=skillSource('语文解题引导','阅读,作文,中心','语文');await page.locator('#teachingSkillSource').fill(chinese);await page.locator('#teachingSkillSave').click();await waitFeedback('技能文件已解析并保存');checks.push('技能原文编辑与启停同步');
  const upload=async(title,text)=>request('/materials','POST',{classId:'a',title,fileName:title+'.md',dataBase64:Buffer.from(text).toString('base64')});
  const math=(await upload('数学材料','方程两边应保持相等。')).material.id;
  const language=(await upload('语文材料','阅读时先找中心句。')).material.id;
  await page.locator('#teachingRefresh').click();await waitFeedback('管理数据已刷新');
  const skills=(await request('/teaching-skills?classId=a')).skills;
  await page.locator('#agentNew').click();await page.locator('#agentName').fill('数学助手');await page.locator('#agentSkillBindings input[value="'+skills[0].id+'"]').check();await page.locator('#agentMaterialBindings input[value="'+math+'"]').check();await page.locator('#agentSave').click();await waitFeedback('智能体及绑定已保存');
  assert.ok((await page.locator('#agentEffectivePrompt').textContent()).includes('耐心'));checks.push('智能体空提示词回退默认角色');
  await page.locator('#agentNew').click();await page.locator('#agentName').fill('语文助手');await page.locator('#agentPrompt').fill('你是一名语文辅导教师。');await page.locator('#agentSkillBindings input[value="'+skills[1].id+'"]').check();await page.locator('#agentMaterialBindings input[value="'+language+'"]').check();await page.locator('#agentSave').click();await waitFeedback('智能体及绑定已保存');
  let agents=(await request('/agents?classId=a')).agents;assert.equal(agents.length,2);assert.deepEqual(agents[0].material_ids,[math]);assert.deepEqual(agents[1].material_ids,[language]);checks.push('创建两个智能体并分别绑定不同技能和原材料ID');
  await page.locator('#teachingManagement').screenshot({path:path.join(reports,'stage1-teacher-management.png')});
  await page.locator('#agentToggle').click();await waitFeedback('智能体启停状态已保存');assert.equal((await request('/agents/'+agents[1].id)).agent.enabled,false);
  await page.locator('#agentToggle').click();await waitFeedback('智能体启停状态已保存');checks.push('智能体启用和停用真实保存');
  await page.locator('#agentName').fill('语文助手修改');await page.locator('#agentSkillBindings input:checked').uncheck();await page.locator('#agentMaterialBindings input:checked').uncheck();await page.locator('#agentSave').click();await waitFeedback('智能体及绑定已保存');const edited=(await request('/agents/'+agents[1].id)).agent;assert.equal(edited.name,'语文助手修改');assert.deepEqual(edited.skill_ids,[]);assert.deepEqual(edited.material_ids,[]);checks.push('修改智能体并即时解除技能和材料绑定');
  await page.locator('#agentNew').click();await page.locator('#agentName').fill('数学助手');await page.locator('#agentSave').click();await waitFeedback('名称在本班已存在');
  await page.locator('#teachingSkillNew').click();await page.locator('#teachingSkillSource').fill(skillSource('非法工具','方程','数学').replace('knowledge_search','mcp_tool@server'));await page.locator('#teachingSkillSave').click();await waitFeedback('MCP工具引用不可用');checks.push('同名智能体和非法工具提交明确失败');
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelector('#agentList').options.length===2);checks.push('刷新后管理配置持久化读取');
  await createSkill('可删除技能',skillSource('可删除技能','临时',''));
  await page.locator('#teachingSkillDelete').click();await waitFeedback('技能及其绑定已删除');assert.equal((await request('/teaching-skills?classId=a')).skills.length,2);checks.push('技能删除按钮实际删除并刷新列表');
  await page.locator('#agentNew').click();await page.locator('#agentName').fill('可删除助手');await page.locator('#agentSave').click();await waitFeedback('智能体及绑定已保存');await page.locator('#agentDelete').click();await waitFeedback('智能体已删除');assert.equal((await request('/agents?classId=a')).agents.length,2);checks.push('智能体删除按钮实际删除并刷新列表');
  // Old prompts remain independent and usable.
  await page.locator('#promptName').fill('旧提示词兼容');await page.locator('#promptCreate').click();await page.waitForFunction(()=>Array.from(document.querySelector('#skillSelect').options).some(o=>o.text.includes('旧提示词兼容')));checks.push('旧提示词管理保持可操作');
  const oldToken=await page.evaluate(()=>sessionStorage.getItem('campusclaw_assistant_token'));
  await page.goto(url+'/swagger');await page.locator('.auth-wrapper .authorize').click({timeout:30000});await page.locator('.auth-container input').fill(oldToken);await page.locator('.auth-btn-wrapper .authorize').click();await page.locator('.auth-btn-wrapper .btn-done').click();
  const op=page.locator('.opblock-get').filter({has:page.locator('.opblock-summary-path[data-path="/agents"]')});await op.locator('.opblock-summary').click();await op.getByRole('button',{name:'Try it out'}).click();await op.locator('input[placeholder="classId"]').fill('a');
  const swaggerRequest=page.waitForRequest(r=>r.url()===url+'/agents?classId=a');await op.getByRole('button',{name:'Execute',exact:true}).click();const sent=await swaggerRequest;assert.equal(sent.headers().authorization,'Bearer '+oldToken);const result=await sent.response();assert.equal(result.status(),200);assert.equal((await result.json()).agents.length,2);checks.push('Swagger 新增智能体接口实际携带 Bearer 调试成功');
  await page.goto(url+'/assistant.html');await page.locator('#workspace').waitFor({state:'visible'});
  await request('/classes/a','POST',{username:'alice'});
  await page.locator('#logoutButton').click();await page.locator('#username').fill('alice');await page.locator('#password').fill(testPassword);await page.locator('#loginButton').click();await page.locator('#workspace').waitFor({state:'visible'});assert.equal(await page.locator('#teachingManagement').isVisible(),false);
  assert.equal((await request('/agents?classId=a')).agents.length,2);checks.push('学生管理界面隐藏且后端可读授权启用智能体');
  await page.locator('#conversationMode').selectOption('legacy');await page.locator('#newButton').click();await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent.includes('解题引导'));await page.locator('#question').fill('完全没有相关资料的内容xyz');await page.locator('#sendButton').click();await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('当前班级资料中没有找到相关内容。'));checks.push('旧 promptId 聊天及无命中 SSE 行为不变');
  // Old local assignment page: browser-only isolated storage, no real user data.
  await page.goto(url+'/');await page.locator('#sid').fill('fixture-001');await page.locator('#sname').fill('隔离学生');await page.locator('#content').fill('浏览器作业兼容验证');await page.getByRole('button',{name:'提交作业',exact:true}).click();assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('courseSubmissionsV2')).length),1);checks.push('原作业提交仍写入隔离浏览器 localStorage');
  assert.deepEqual(errors,[]);checks.push('无浏览器 JavaScript 错误');
  fs.writeFileSync(path.join(reports,'stage1-browser-result.json'),JSON.stringify({passed:true,passedChecks:checks.length,model:'not called',checks},null,2));console.log('Stage1 browser: '+checks.length+' checks passed; isolated API/storage; no model calls.');
 }catch(e){await page.screenshot({path:path.join(reports,'stage1-browser-failure.png'),fullPage:true});console.error('Browser checks completed:',checks);throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
