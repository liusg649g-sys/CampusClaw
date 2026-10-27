const testPassword=process.env.CAMPUSCLAW_TEST_PASSWORD;
if(!testPassword)throw Error('Use an isolated browser fixture; no test password configured');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const reports=process.env.CAMPUSCLAW_BROWSER_REPORT_DIR||path.join(__dirname,'reports'),{url}=JSON.parse(fs.readFileSync(path.join(reports,'stage2-browser-fixture.json'),'utf8'));
const checks=[],errors=[],evidence=[];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 const page=await browser.newPage({viewport:{width:1400,height:1000}});await page.addInitScript(()=>{window.stage2Streams=[];const original=window.fetch;window.fetch=async(...args)=>{const response=await original(...args);if(response.headers.get('content-type')?.includes('text/event-stream'))response.clone().text().then(raw=>window.stage2Streams.push(raw)).catch(()=>{});return response;};});page.on('pageerror',e=>errors.push(e.message));
 async function login(name,password){await page.goto(url+'/assistant.html');await page.locator('#username').fill(name);await page.locator('#password').fill(password);await page.locator('#loginButton').click();await page.locator('#workspace').waitFor({state:'visible'});}
 async function api(p,method='GET',data){const token=await page.evaluate(()=>sessionStorage.getItem('campusclaw_assistant_token'));const r=await page.request.fetch(url+p,{method,headers:{Authorization:'Bearer '+token},data});assert.equal(r.ok(),true,await r.text());return r.json();}
 async function fresh(aid){await page.locator('#studentAgentSelect').selectOption(String(aid));await page.locator('#newButton').click();await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent.includes('新的提问'));return (await api('/conversations')).conversations[0].id;}
 async function ask(question){const before=await page.evaluate(()=>window.stage2Streams.length);await page.locator('#question').fill(question);await page.locator('#sendButton').click();await page.waitForFunction(n=>window.stage2Streams.length>n,before);await page.waitForFunction(()=>document.querySelector('#stopButton').disabled);return page.evaluate(()=>window.stage2Streams.at(-1));}
 try{
  await login('alice',testPassword);const agents=(await api('/agents?classId=a')).agents;
  assert.equal(agents.length,2);assert.equal(await page.locator('#teachingManagement').isVisible(),false);checks.push('学生仅看到本班已启用智能体，教师管理区隐藏');
  const math=await fresh(agents[0].id);checks.push('通过页面选择数学智能体创建会话');
  let raw=await ask('方程怎么去括号');let detail=await api('/conversations/'+math+'/messages');
  assert.ok(raw.startsWith('event: meta'));assert.ok(raw.includes('event: delta'));assert.ok(raw.includes('event: done'));checks.push('浏览器真实HTTP收到 meta → delta → done');
  assert.ok((await page.locator('#messages').textContent()).includes('数学解题引导'));assert.equal(detail.messages.at(-1).sources[0].title,'数学材料');assert.equal(detail.messages.at(-1).skill_name,'数学解题引导');checks.push('数学技能和数学材料引用实际展示并持久化');
  evidence.push({scenario:'数学专用智能体',raw,detail});await page.screenshot({path:path.join(reports,'stage2-math.png'),fullPage:true});
  const loginResponse=await page.request.post(url+'/login',{data:{username:'teacher',password:testPassword}});const teacher=(await loginResponse.json()).token;
  const management=(await (await page.request.get(url+'/teaching-skills?classId=a',{headers:{Authorization:'Bearer '+teacher}})).json()).skills;
  await page.request.put(url+'/teaching-skills/'+management[0].id,{headers:{Authorization:'Bearer '+teacher},data:{enabled:false}});raw=await ask('方程');detail=await api('/conversations/'+math+'/messages');assert.equal(detail.messages.at(-1).skill_name,null);checks.push('教师停用技能后同一学生会话下一轮立即生效');evidence.push({scenario:'技能停用立即生效',raw,detail});await page.request.put(url+'/teaching-skills/'+management[0].id,{headers:{Authorization:'Bearer '+teacher},data:{enabled:true}});
  await page.locator('#studentAgentSelect').selectOption(String(agents[1].id));raw=await ask('方程');detail=await api('/conversations/'+math+'/messages');assert.equal(detail.conversation.agentId,agents[0].id);checks.push('切换下拉框不改变已建会话智能体');
  const chinese=await fresh(agents[1].id);raw=await ask('阅读作文');detail=await api('/conversations/'+chinese+'/messages');assert.equal(detail.messages.at(-1).sources[0].title,'语文材料');assert.equal(detail.messages.at(-1).skill_name,'语文解题引导');checks.push('语文智能体只引用语文材料');evidence.push({scenario:'语文专用智能体',raw,detail});
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('#history button').filter({hasText:'阅读作文'}).click();await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('语文解题引导'));checks.push('刷新并重开历史后保留技能与引用');
  raw=await ask('unmatched-zzzz-no-hit');detail=await api('/conversations/'+chinese+'/messages');assert.deepEqual(detail.messages.at(-1).sources,[]);assert.equal(detail.messages.at(-1).content,'模拟教学提示：先想一想条件。');checks.push('无命中仍调用模拟模型且跨分片虚假引用已消除');evidence.push({scenario:'无命中仍调用模型（Mock）',raw,detail});
  await page.locator('#question').fill('停止测试');await page.locator('#sendButton').click();await page.waitForFunction(()=>document.querySelector('#messages').lastElementChild.textContent.includes('模拟慢速片段'));await page.locator('#stopButton').click();await page.waitForFunction(()=>document.querySelector('#error').textContent.includes('已停止'));await page.waitForTimeout(700);detail=await api('/conversations/'+chinese+'/messages');assert.equal(detail.messages.at(-1).status,'interrupted');checks.push('停止按钮真实中断fetch，数据库记录 interrupted');
  await page.locator('#conversationMode').selectOption('legacy');await page.locator('#newButton').click();await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent.includes('旧提示词'));raw=await ask('unmatched-zzzz-no-hit');assert.ok(raw.startsWith('event: start'));assert.ok(raw.includes('当前班级资料中没有找到相关内容'));checks.push('旧提示词创建和旧SSE无命中行为兼容');
  assert.deepEqual(errors,[]);checks.push('浏览器无JavaScript异常');
  fs.writeFileSync(path.join(reports,'stage2-browser-evidence.json'),JSON.stringify({model:'EXPLICIT MOCK',evidence},null,2));
  fs.writeFileSync(path.join(reports,'stage2-browser-result.json'),JSON.stringify({passed:true,passedChecks:checks.length,checks,model:'EXPLICIT MOCK'},null,2));console.log('Stage2 browser: '+checks.length+' checks passed');
 }catch(e){await page.screenshot({path:path.join(reports,'stage2-browser-failure.png'),fullPage:true});console.error(checks);throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
