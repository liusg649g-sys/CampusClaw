const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),url=process.env.CAMPUSCLAW_ACCEPTANCE_URL||'http://127.0.0.1:18080';
const accounts=JSON.parse(fs.readFileSync(path.join(root,'temp/acceptance-site-20261027/TEST_ACCOUNTS.json'),'utf8'));
const report=process.env.CAMPUSCLAW_SITE_REPORT_DIR||path.join(__dirname,'reports/final-20261027-site');fs.mkdirSync(report,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),checks=[];
 await page.addInitScript(()=>{window.acceptanceStreams=[];const original=window.fetch;window.fetch=async(...args)=>{const r=await original(...args);if(r.headers.get('content-type')?.includes('text/event-stream'))r.clone().text().then(text=>window.acceptanceStreams.push(text));return r;};});
 try{
  const identity=[];
  for(const [route,title] of [['/assistant.html','CampusClaw · AI 解题助手'],['/swagger','CampusClaw API']]){
   const response=await page.goto(url+route);assert.equal(response.status(),200);assert.equal(response.request().redirectedFrom(),null);assert.equal(page.url(),url+route);
   assert.ok((await response.headerValue('server')).startsWith('CampusClawBackend/'));
   assert.ok((await response.headerValue('content-type')).includes('text/html'));
   assert.equal(await page.title(),title);
   if(route==='/assistant.html'){await page.locator('#loginButton').waitFor();assert.ok((await page.locator('body').textContent()).includes('隔离验收站'));await page.screenshot({path:path.join(report,'assistant-entry.png'),fullPage:true});}
   else {await page.locator('.swagger-ui .info').waitFor();await page.screenshot({path:path.join(report,'swagger.png'),fullPage:true});}
   identity.push({route,status:response.status(),headers:await response.allHeaders(),url:page.url(),title:await page.title(),redirected:false});
  }
  fs.writeFileSync(path.join(report,'browser-identity.json'),JSON.stringify({verified:true,pages:identity},null,2));
  checks.push('两个页面的响应头、HTML、标题、实际URL及无重定向均确认为CampusClaw');
  for(const route of ['/assistant.html?campusclaw=routefix','/assistant.html/']){
   const response=await page.goto(url+route);assert.equal(response.status(),200);assert.equal(await page.title(),'CampusClaw · AI 解题助手');await page.locator('#loginButton').waitFor();
  }
  checks.push('助手查询参数和尾斜杠入口均正常展示CampusClaw');
  assert.equal((await page.request.get(url+'/health')).status(),200);checks.push('隔离服务健康200');
  checks.push('/swagger真实渲染Swagger UI');
  async function login(account){await page.goto(url+'/assistant.html');await page.locator('#username').fill(account.username);await page.locator('#password').fill(account.password);await page.locator('#loginButton').click();await page.locator('#workspace').waitFor({state:'visible'});}
  await login(accounts.teacher);assert.ok((await page.locator('#agentList option').count())>=2);checks.push('教师界面可见两个预置测试智能体');
  await page.screenshot({path:path.join(report,'teacher.png'),fullPage:true});
  await page.locator('#logoutButton').click();await login(accounts.student);
  const option=page.locator('#studentAgentSelect option').filter({hasText:'计算验证'});await page.locator('#studentAgentSelect').selectOption(await option.getAttribute('value'));
  await page.locator('#newButton').click();await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent.includes('新的提问'));
  await page.locator('#question').fill('计算验收');await page.locator('#sendButton').click();
  await page.waitForFunction(()=>window.acceptanceStreams.length===1);const raw=await page.evaluate(()=>window.acceptanceStreams[0]);assert.ok(raw.includes('"tool_calls"'));assert.ok(raw.includes('event: done'));fs.writeFileSync(path.join(report,'sse.txt'),raw);checks.push('学生请求真实MCP，meta.tool_calls和done实际返回');
  await page.waitForFunction(()=>document.querySelector('#stopButton').disabled);assert.equal(await page.locator('.tool-status').count(),1);assert.ok((await page.locator('#messages').textContent()).includes('Mock'));checks.push('Mock标记明确，工具状态无重复');
  await page.screenshot({path:path.join(report,'student.png'),fullPage:true});
  const token=await page.evaluate(()=>sessionStorage.getItem('campusclaw_assistant_token'));
  assert.equal((await page.request.get(url+'/api/mcp/tool-calls?classId=a',{headers:{Authorization:'Bearer '+token}})).status(),403);checks.push('学生访问教师审计403');
  fs.writeFileSync(path.join(report,'result.json'),JSON.stringify({passed:true,passedChecks:checks.length,url,model:'EXPLICIT MOCK',mcp:'real local server',checks},null,2));console.log('Acceptance site: '+checks.length+' checks passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
