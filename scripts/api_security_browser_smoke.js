'use strict';
// Real local UI/backend with a memory-only synthetic credential store.
// This does not execute native Windows credential APIs or a remote API.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict'),{spawn}=require('child_process');
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-key-ui-'));
const result={checks:[],live_API_called:false,native_Windows_tested:false,real_key_used:false};
const key='sk-synthetic-browser-fixture-123456789';
let child,browser;
(async()=>{
 try{
  child=spawn('python3',['-u','-c',`import sys
sys.path.insert(0,'tests')
from test_api_security import MemoryStore
from bbolprom_engine.app import make_server
server=make_server(sys.argv[1]);server.application.credentials=MemoryStore()
print(server.server_port,flush=True)
server.serve_forever()`,data],{cwd:root,stdio:['ignore','pipe','pipe']});
  let errors='';child.stderr.on('data',b=>errors+=b);
  const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture start timeout')),15000);child.stdout.once('data',b=>{clearTimeout(timer);resolve(Number(String(b).trim()))});child.once('exit',code=>{clearTimeout(timer);reject(Error('fixture exited '+code+' '+errors))})});
  const base='http://127.0.0.1:'+port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage(),external=[],pageErrors=[];
  page.on('pageerror',e=>pageErrors.push(e.message));
  await page.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  async function check(name,fn){await fn();result.checks.push(name);console.log(name)}
  await page.goto(base+'/');await page.waitForFunction(()=>state.api_key_storage!==undefined);
  await page.click('#settingsBtn');
  await check('key_masked_and_official_endpoint_locked',async()=>{
   assert.equal(await page.locator('#apiKey').getAttribute('type'),'password');
   assert(await page.locator('#endpoint').evaluate(e=>e.readOnly));
   assert.equal(await page.locator('#endpoint').inputValue(),'https://api.openai.com/v1/chat/completions');
   assert.equal(await page.locator('#model').inputValue(),'gpt-6.1-sol');
   assert.equal(await page.locator('#apiEnabled').isChecked(),false);
  });
  await check('save_key_clears_field_and_never_returns_secret_in_state',async()=>{
   await page.fill('#apiKey',key);await page.click('#saveKey');await page.waitForFunction(()=>state.api_key_present===true);
   assert.equal(await page.locator('#apiKey').inputValue(),'');
   assert.equal(await page.evaluate(k=>JSON.stringify(state).includes(k),key),false);
   assert.equal(await page.evaluate(k=>document.body.textContent.includes(k),key),false);
   assert.equal(await page.evaluate(k=>JSON.stringify(localStorage).includes(k)||JSON.stringify(sessionStorage).includes(k),key),false);
  });
  await check('close_or_escape_clears_unsaved_input',async()=>{
   await page.fill('#apiKey',key+'unsaved');await page.keyboard.press('Escape');
   await page.waitForFunction(()=>!document.querySelector('#settingsDialog').open);
   assert.equal(await page.locator('#apiKey').inputValue(),'');await page.click('#settingsBtn');
  });
  await check('replacement_and_delete_affect_vault_only_not_API_enablement',async()=>{
   await page.fill('#apiKey',key+'replaced');await page.click('#saveKey');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('저장했습니다'));
   assert.equal(await page.locator('#apiKey').inputValue(),'');await page.click('#deleteKey');
   await page.waitForFunction(()=>state.api_key_present===false);assert.equal(await page.locator('#apiEnabled').isChecked(),false);
   assert.equal(await page.evaluate(()=>state.cards.length),309);
  });
  await check('failed_save_also_clears_secret',async()=>{
   await page.fill('#apiKey','not-a-key');await page.click('#saveKey');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('키 형식'));
   assert.equal(await page.locator('#apiKey').inputValue(),'');
  });
  await check('zero_call_limit_is_preserved_after_settings_save',async()=>{
   await page.fill('#maxCalls','0');await page.click('#saveApi');
   await page.waitForFunction(()=>state.api.max_calls===0);
   assert.equal(await page.locator('#maxCalls').inputValue(),'0');
   assert.equal(await page.locator('#apiEnabled').isChecked(),false);
  });
  assert.deepEqual(external,[]);assert.deepEqual(pageErrors,[]);result.status='passed';
 }catch(e){result.status='failed';result.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();if(child)child.kill();fs.rmSync(data,{recursive:true,force:true});fs.writeFileSync(path.join(root,'evaluation/api-security-browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))}
})();
