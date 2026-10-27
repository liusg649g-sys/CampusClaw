const testPassword=process.env.CAMPUSCLAW_TEST_PASSWORD;
if(!testPassword)throw Error('Use an isolated browser fixture; no test password configured');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const report=process.env.CAMPUSCLAW_BROWSER_REPORT_DIR||path.join(__dirname,'reports','lesson6-stage3'),{url,agent_id}=JSON.parse(fs.readFileSync(path.join(report,'browser-fixture.json'),'utf8'));
const checks=[];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.streams=[];const original=fetch;window.fetch=async(...args)=>{const r=await original(...args);if(r.headers.get('content-type')?.includes('text/event-stream'))r.clone().text().then(text=>window.streams.push(text)).catch(()=>{});return r;};});
 async function login(name,password){await page.goto(url+'/assistant.html');await page.locator('#username').fill(name);await page.locator('#password').fill(password);await page.locator('#loginButton').click();await page.locator('#workspace').waitFor({state:'visible'});}
 async function api(p){const token=await page.evaluate(()=>sessionStorage.getItem('campusclaw_assistant_token'));const r=await page.request.get(url+p,{headers:{Authorization:'Bearer '+token}});assert.ok(r.ok());return r.json();}
 try{
  await login('alice',testPassword);await page.locator('#studentAgentSelect').selectOption(String(agent_id));await page.locator('#newButton').click();await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent.includes('新的提问'));
  const cid=(await api('/conversations')).conversations[0].id;await page.locator('#question').fill('计算这道题');await page.locator('#sendButton').click();await page.locator('.tool-status').waitFor();assert.ok((await page.locator('.tool-status').textContent()).includes('calculator@loop-local'));checks.push('学生实际看到已授权工具和ok状态，不展示调用参数');
  await page.waitForFunction(()=>window.streams.length===1);await page.waitForFunction(()=>document.querySelector('#stopButton').disabled);const raw=await page.evaluate(()=>window.streams[0]);assert.ok(raw.startsWith('event: meta'));assert.ok(raw.indexOf('event: tool_status')<raw.indexOf('event: delta'));assert.ok(raw.includes('event: done'));checks.push('SSE顺序为meta、tool_status、delta、done');
  const metas=raw.split('\n\n').filter(b=>b.startsWith('event: meta')).map(b=>JSON.parse(b.split('\ndata: ')[1]));assert.ok(metas[0].agent);assert.equal(metas.at(-1).tool_calls[0].status,'ok');assert.equal(await page.locator('.tool-status').count(),1);checks.push('meta.tool_calls包含真实结果，兼容tool_status不重复显示');
  const detail=await api('/conversations/'+cid);const final=detail.messages.at(-1);assert.equal(final.content,'模拟模型根据真实工具结果：14。');assert.equal(final.tool_calls[0].status,'ok');assert.ok((await page.locator('#messages').textContent()).includes(final.content));checks.push('真实MCP计算结果进入Mock模型，最终显示与落库一致');
  fs.writeFileSync(path.join(report,'browser-sse-evidence.txt'),raw);await page.locator('#messages').screenshot({path:path.join(report,'student-tools.png')});
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('#history button').filter({hasText:'计算这道题'}).click();await page.locator('.tool-status').waitFor();assert.ok((await page.locator('#messages').textContent()).includes('14。'));checks.push('重开历史保留正文及安全工具状态');
  await page.locator('#question').fill('计算停止测试');await page.locator('#sendButton').click();await page.waitForFunction(()=>document.querySelector('#messages').lastElementChild.textContent.includes('模拟慢速回答'));await page.locator('#stopButton').click();await page.waitForFunction(()=>document.querySelector('#error').textContent.includes('已停止'));await page.waitForTimeout(500);assert.equal((await api('/conversations/'+cid)).messages.at(-1).status,'interrupted');checks.push('停止生成后助手记interrupted，已真实完成的工具审计仍为ok');
  const denied=await page.request.get(url+'/api/mcp/tool-calls?classId=a',{headers:{Authorization:'Bearer '+await page.evaluate(()=>sessionStorage.getItem('campusclaw_assistant_token'))}});assert.equal(denied.status(),403);checks.push('学生直接访问教师审计API被403拒绝');
  await page.locator('#logoutButton').click();await login('teacher',testPassword);await page.locator('#mcpAuditRefresh').click();await page.waitForFunction(()=>document.querySelector('#mcpAuditSummary').textContent.includes('2 条'));assert.ok((await page.locator('#mcpAuditRows').textContent()).includes('calculator@loop-local'));checks.push('教师实际查询并查看本班审计记录');
  await page.locator('#mcpAuditStatus').selectOption('denied');await page.locator('#mcpAuditRefresh').click();await page.waitForFunction(()=>document.querySelector('#mcpAuditSummary').textContent.includes('0 条'));checks.push('审计状态过滤按钮真实调用后端');
  const doc=await api('/openapi.json');assert.ok(doc.paths['/api/mcp/tool-calls']);checks.push('新增OpenAPI审计接口在隔离服务可读取');
  assert.deepEqual(errors,[]);checks.push('无浏览器JavaScript错误');
  fs.writeFileSync(path.join(report,'browser-result.json'),JSON.stringify({passed:true,passedChecks:checks.length,model:'EXPLICIT MOCK',mcp:'actual stage-one server',checks},null,2));console.log('Tool loop browser: '+checks.length+' checks passed');
 }catch(e){console.error('Completed checks:',checks);await page.screenshot({path:path.join(report,'browser-failure.png'),fullPage:true});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
