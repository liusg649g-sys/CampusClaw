// Publish only empty-login/Swagger pages; never uses account files or tokens.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CAMPUSCLAW_PLAYWRIGHT_MODULE||'playwright');
const base=process.env.CAMPUSCLAW_PUBLIC_CAPTURE_URL||'http://127.0.0.1:18080';
const url=new URL(base);assert.equal(url.hostname,'127.0.0.1');assert.equal(url.protocol,'http:');assert.equal(url.username,'');assert.equal(url.password,'');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSCLAW_BROWSER_EXE||undefined});
 const page=await browser.newPage({viewport:{width:1320,height:950}});
 const output=path.resolve(__dirname,'../submission/evidence');fs.mkdirSync(output,{recursive:true});
 try{
  let response=await page.goto(base+'/assistant.html');assert.equal(response.status(),200);assert.equal(await page.title(),'CampusClaw · AI 解题助手');
  assert.equal(await page.locator('#username').inputValue(),'');assert.equal(await page.locator('#password').inputValue(),'');
  assert.equal(await page.locator('#workspace').isVisible(),false);
  await page.screenshot({path:path.join(output,'assistant-public.png'),fullPage:true});
  response=await page.goto(base+'/swagger');assert.equal(response.status(),200);assert.equal(await page.title(),'CampusClaw API');await page.locator('.swagger-ui .info').waitFor();
  assert.equal(await page.evaluate(()=>localStorage.length),0);
  await page.screenshot({path:path.join(output,'swagger-public.png'),fullPage:false});
  console.log('Captured two public pages after identity and empty-login checks; no authentication performed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exit(1);});
