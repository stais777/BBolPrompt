'use strict';
// Synthetic local-only regression: cold engine initialization and visible modal errors.
// --baseline-js=<git-ref> reproduces the hidden-error defect using the old app.js.
const fs=require('fs'),path=require('path'),os=require('os');
const {spawn,spawnSync}=require('child_process');
const assert=require('assert/strict');
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-feedback-'));
const baselineArg=process.argv.find(x=>x.startsWith('--baseline-js='));
const baseline=baselineArg?.slice('--baseline-js='.length);
const report={checks:[],platform:process.platform,real_key_used:false,external_API_called:false,native_windows_tested:false,baseline_js:baseline||null};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let child,browser,release;
async function check(name,fn){await fn();report.checks.push({name,status:'passed'});console.log(name)}
(async()=>{
 try{
  // Deliberately no --mock-api-engine: first button click initializes the real local repository.
  child=spawn('python3',['scripts/browser_fixture_server.py',dir],{cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stdout.on('data',b=>logs+=b);child.stderr.on('data',b=>logs+=b);
  const ready=path.join(dir,'runtime.json');
  for(let i=0;i<150&&!fs.existsSync(ready);i++){if(child.exitCode!==null)throw Error(logs);await pause(100)}
  assert(fs.existsSync(ready),'fixture started');
  const base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(ready)).port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1500,height:1050}});
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  let failLoad=true,failApprove=false,pendingLoad=false;
  const loadError='시험용 정의 불러오기 실패',approveError='시험용 정의 확정 실패';
  let oldJS;
  if(baseline){const r=spawnSync('git',['show',baseline+':bbolprom_engine/web/app.js'],{cwd:root,encoding:'utf8'});assert.equal(r.status,0,r.stderr);oldJS=r.stdout}
  await page.route('**/*',async route=>{
   const request=route.request(),url=request.url();
   if(!url.startsWith(base+'/')){external.push(url);return route.abort()}
   if(oldJS&&url===base+'/app.js')return route.fulfill({status:200,contentType:'application/javascript',body:oldJS});
   if(url===base+'/api/engine/definitions'&&request.method()==='POST'){
    const payload=request.postDataJSON();
    if(failLoad&&Object.keys(payload).length===0){
     pendingLoad=true;await new Promise(r=>{release=r});pendingLoad=false;
     return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:loadError})});
    }
    if(failApprove&&payload.operation==='approve')return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:approveError})});
   }
   return route.continue();
  });
  await page.goto(base+'/');await page.waitForFunction(()=>state.cards.length===309);
  const original=await page.evaluate(()=>JSON.stringify(state.cards.filter(c=>c.approved)));
  await page.click('#settingsBtn');
  if(baseline){
   await page.click('#loadEngineBtn');for(let i=0;i<100&&!pendingLoad;i++)await pause(20);assert(pendingLoad);
   release();release=null;
   await page.waitForFunction(text=>document.querySelector('#status').textContent.includes(text),loadError);
   report.observed={settings_open:await page.locator('#settingsDialog').isVisible(),inside:await page.locator('#engineStatus').textContent(),outside:await page.locator('#status').textContent()};
   assert(report.observed.inside.includes(loadError),'definition failure must be visible inside settings modal');
  }else{
   await check('loading_is_visible_and_repeat_click_is_disabled',async()=>{
    await page.click('#loadEngineBtn');for(let i=0;i<100&&!pendingLoad;i++)await pause(20);assert(pendingLoad);
    assert(await page.locator('#loadEngineBtn').isDisabled());
    assert((await page.locator('#engineStatus').textContent()).length>0);
    assert(await page.locator('#engineStatus').isVisible());
   });
   await check('load_failure_is_visible_in_modal_and_can_be_retried',async()=>{
    release();release=null;
    await page.waitForFunction(text=>document.querySelector('#engineStatus').textContent.includes(text),loadError);
    assert(await page.locator('#settingsDialog').isVisible());assert(await page.locator('#engineStatus').isVisible());
    assert(await page.locator('#loadEngineBtn').isEnabled());
   });
   await check('retry_cold_repository_displays_seven_drafts_without_paid_call',async()=>{
    failLoad=false;await page.click('#loadEngineBtn');await page.waitForSelector('#engineDefinitions details');
    assert.equal(await page.locator('#engineDefinitions details').count(),7);
    assert((await page.locator('#engineStatus').textContent()).includes('정의 확정 0 / 7'));
    assert.equal(await page.evaluate(async()=>{const s=await api('/api/engine/status',{});return s.counts.api_runs}),0);
   });
   await check('failed_reload_preserves_previously_displayed_definitions',async()=>{
    await page.locator('#engineDefinitions details').first().locator('summary').click();
    await page.locator('#engineDefinitions textarea').first().fill('실패 중에도 보존할 사용자 편집 정의');
    const before=await page.locator('#engineDefinitions').innerHTML();
    const values=await page.locator('#engineDefinitions textarea').evaluateAll(nodes=>nodes.map(n=>n.value));failLoad=true;
    await page.click('#loadEngineBtn');for(let i=0;i<100&&!pendingLoad;i++)await pause(20);assert(pendingLoad);
    release();release=null;
    await page.waitForFunction(text=>document.querySelector('#engineStatus').textContent.includes(text),loadError);
    assert.equal(await page.locator('#engineDefinitions').innerHTML(),before);
    assert.deepEqual(await page.locator('#engineDefinitions textarea').evaluateAll(nodes=>nodes.map(n=>n.value)),values);
    failLoad=false;await page.click('#loadEngineBtn');await page.waitForFunction(()=>document.querySelector('#engineStatus').textContent.includes('정의 확정 0 / 7'));
   });
   await check('approval_failure_is_visible_and_retry_confirms_definitions',async()=>{
    failApprove=true;await page.click('#approveEngineDefinitions');
    await page.waitForFunction(text=>document.querySelector('#engineStatus').textContent.includes(text),approveError);
    assert(await page.locator('#settingsDialog').isVisible());assert(await page.locator('#approveEngineDefinitions').isEnabled());
    failApprove=false;await page.click('#approveEngineDefinitions');await page.waitForFunction(()=>document.querySelector('#engineStatus').textContent.includes('정의 확정 7 / 7'));
   });
   await check('baseline_keys_budgets_and_provider_are_untouched',async()=>{
    const current=await page.evaluate(()=>api('/api/state'));
    assert.equal(JSON.stringify(current.cards.filter(c=>c.approved)),original);
    assert.equal(current.api_usage.calls,0);assert.equal(current.api_key_present,false);
    assert.equal(current.cards.filter(c=>c.approved).reduce((n,c)=>n+c.tags.length,0),8471);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
   });
  }
  report.status='passed';
 }catch(e){report.status='failed';report.error=String(e.stack||e);process.exitCode=1}
 finally{
  if(release)release();if(browser)await browser.close();if(child&&child.exitCode===null)child.kill();
  fs.rmSync(dir,{recursive:true,force:true});
  const filename='api-engine-feedback-browser'+(baseline?'-before':'')+'.json';
  fs.writeFileSync(path.join(root,'evaluation',filename),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
 }
})();
