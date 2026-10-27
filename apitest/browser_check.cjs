// Requires optional Playwright. Fixture uses an explicit mock AI service.
const fs=require('fs');
const path=require('path');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const testPassword=process.env.CAMPUSCLAW_TEST_PASSWORD||JSON.parse(fs.readFileSync(path.join(__dirname,'reports','browser-fixture.json'),'utf8')).test_password;
if(!testPassword)throw Error('Use an isolated browser fixture');
const assert=require('node:assert/strict');
(async()=>{
 const report=path.join(__dirname,'reports');
 const {url}=JSON.parse(fs.readFileSync(path.join(report,'browser-fixture.json'),'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 const page=await browser.newPage({viewport:{width:1280,height:1000}});
 const failures=[];page.on('pageerror',e=>failures.push(e.message));
 async function login(username,password){await page.goto(url+'/assistant.html');await page.locator('#username').fill(username);await page.locator('#password').fill(password);await page.locator('#loginButton').click();await page.locator('#workspace').waitFor({state:'visible'});}
 try{
  await login('teacher',testPassword);
  await page.locator('#classSelect').selectOption('a');
  await page.waitForFunction(()=>document.querySelector('#skillSelect').options.length>0);
  await page.locator('#promptName').waitFor();
  await page.locator('#promptName').fill('浏览器验证引导技能');
  await page.locator('#promptContent').fill('请让学生先分析牛顿第二定律中的已知条件，再逐步给予提示。');
  await page.locator('#promptCreate').click();
  await page.waitForFunction(()=>Array.from(document.querySelector('#skillSelect').options).some(o=>o.text.includes('浏览器验证引导技能')));
  await page.locator('#logoutButton').click();
  await login('alice',testPassword);
  await page.waitForFunction(()=>Array.from(document.querySelector('#skillSelect').options).some(o=>o.text.includes('浏览器验证引导技能')));
  assert.equal(await page.locator('#teacher').isVisible(),false);
  await page.locator('#skillSelect').selectOption({label:'浏览器验证引导技能 · 解题引导'});
  await page.locator('#newButton').click();
  await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent.includes('解题引导'));
  await page.locator('#question').fill('请引导我理解牛顿第二定律');
  await page.locator('#sendButton').click();
  await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('请先想一想：'));
  // The first delta is observable while the stream is still open.
  assert.equal(await page.locator('#stopButton').isDisabled(),false);
  await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('physics.md'));
  await page.waitForFunction(()=>!document.querySelector('#sendButton').disabled);
  assert.equal(await page.locator('#question').inputValue(),'');
  await page.screenshot({path:path.join(report,'browser-chat.png'),fullPage:true});
  await page.locator('#history button').first().click();
  await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('physics.md'));
  assert.deepEqual(failures,[]);
  fs.writeFileSync(path.join(report,'browser-result.json'),JSON.stringify({passed:true,model:'mock',checks:['teacher prompt create','student login','role UI','conversation creation','first delta before completion','source display','history reload'],browserErrors:failures},null,2));
  console.log('Browser workflow passed (MOCK AI; not real model validation).');
 }catch(e){await page.screenshot({path:path.join(report,'browser-failure.png'),fullPage:true});console.error('Page error:',await page.locator('#error').textContent(),'skills:',await page.locator('#skillSelect').textContent(),failures);throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
