const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const testPassword=process.env.CAMPUSCLAW_TEST_PASSWORD||JSON.parse(fs.readFileSync(path.join(__dirname,'reports','browser-fixture.json'),'utf8')).test_password;
if(!testPassword)throw Error('Use an isolated browser fixture');
(async()=>{
 const report=path.join(__dirname,'reports'),{url}=JSON.parse(fs.readFileSync(path.join(report,'browser-fixture.json'),'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 try{
  const page=await browser.newPage();
  const login=await page.request.post(url+'/login',{data:{username:'teacher',password:testPassword}});
  const {token}=await login.json();
  await page.goto(url+'/docs');
  await page.locator('.auth-wrapper .authorize').click({timeout:25000});
  await page.locator('.auth-container input').fill(token);
  await page.locator('.auth-btn-wrapper .authorize').click();
  await page.locator('.auth-btn-wrapper .btn-done').click();
  const op=page.locator('.opblock-get').filter({has:page.locator('.opblock-summary-path[data-path="/classes"]')});
  await op.locator('.opblock-summary').click();
  await op.getByRole('button',{name:'Try it out'}).click();
  const request=page.waitForRequest(r=>r.url()===url+'/classes');
  await op.getByRole('button',{name:'Execute',exact:true}).click();
  const actual=await request;
  assert.equal(actual.headers().authorization,'Bearer '+token);
  await op.locator('.responses-inner .response-col_status').filter({hasText:'200'}).first().waitFor();
  const response=await actual.response();assert.equal(response.status(),200);
  assert.ok((await response.json()).classes.length>0);
  fs.writeFileSync(path.join(report,'swagger-result.json'),JSON.stringify({passed:true,checks:['Swagger UI loaded','Authorize bearer','GET /classes carries Authorization','200 response contains authorized classes']},null,2));
  console.log('Swagger UI Authorize and live request passed (through Nginx).');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
