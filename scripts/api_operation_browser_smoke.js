'use strict';
// Delayed/rejected local responses only; no real key, provider, image or paid request.
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const {spawn}=require('child_process');
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-operations-'));
const report={checks:[],external_API_called:false,real_key_used:false,native_Windows_tested:false};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));let child,browser,releaseManual,releaseAnalyze;
async function check(name,fn){await fn();report.checks.push({name,status:'passed'});console.log(name)}
(async()=>{
 try{
  child=spawn('python3',['scripts/browser_fixture_server.py',dir,'--mock-api-engine'],{cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stderr.on('data',b=>logs+=b);
  const ready=path.join(dir,'runtime.json');for(let i=0;i<150&&!fs.existsSync(ready);i++){if(child.exitCode!==null)throw Error(logs);await sleep(100)}assert(fs.existsSync(ready));
  const base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(ready)).port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1560,height:1050}});const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  let holdManual=false,holdAnalyze=false,failStateOnce=false,failAnalysis=false,rejectManual=false,loseManualResponse=false,manualRequests=0,analysisRequests=0,statusRequests=0;
  const registered=[];
  await page.route('**/*',async route=>{
   const r=route.request(),u=r.url();if(!u.startsWith(base+'/')){external.push(u);return route.abort()}
   if(u===base+'/api/analysis-status')statusRequests++;
   if(u===base+'/api/state'&&failStateOnce){failStateOnce=false;return route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'시험용 목록 갱신 실패'})})}
   if(u===base+'/api/manual'&&r.method()==='POST'){
    manualRequests++;
    if(rejectManual)return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'시험용 등록 거절'})});
    const response=await route.fetch();registered.push((await response.json()).id);
    if(loseManualResponse)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'시험용 응답 유실'})});
    if(holdManual)await new Promise(resolve=>{releaseManual=resolve});
    return route.fulfill({response});
   }
   if(u===base+'/api/analyze'&&r.method()==='POST'){
    analysisRequests++;
    if(failAnalysis)return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'api_unavailable',warnings:['시험용 출력 토큰 한도에 도달했습니다.'],tags:[],unclassified:[]})});
    const response=await route.fetch();if(holdAnalyze)await new Promise(resolve=>{releaseAnalyze=resolve});return route.fulfill({response});
   }
   return route.continue();
  });
  await page.goto(base+'/');await page.waitForFunction(()=>state.cards.length===309);
  await page.setInputFiles('#hwpx',path.join(dir,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');await page.click('#baselineCommit');await page.waitForFunction(()=>state.baseline.complete);
  const baseline=await page.evaluate(()=>JSON.stringify(state.cards.filter(c=>c.approved)));
  await page.evaluate(async()=>{const d=await api('/api/engine/definitions',{});await api('/api/engine/definitions',{operation:'approve',definitions:d.definitions.map(x=>Object.fromEntries(['id','definition','include','exclude'].map(k=>[k,x[k]]))),expected_token:d.token});await api('/api/settings',{api:{enabled:true,consent:true,model:'fixture'}})});
  const longText='A person waits at a subway station.\n'+'A neutral supplemental scene description with unchanged source text. '.repeat(60);
  async function review(text){await page.click('#manualBtn');await page.fill('#manualText',text);await page.click('#saveManual');await page.waitForSelector('#manualReviewDialog[open]')}
  await check('registration_shows_progress_and_prevents_false_cancellation',async()=>{
   holdManual=true;await review(longText);await page.click('#manualConfirm');
   for(let i=0;i<150&&!releaseManual;i++)await sleep(30);assert(releaseManual);
   assert((await page.locator('#manualReviewStatus').textContent()).includes('등록 중'));
   assert(await page.locator('#manualConfirm').isDisabled());assert(await page.locator('[data-close="manualReviewDialog"]').isDisabled());
   await page.keyboard.press('Escape');assert(await page.locator('#manualReviewDialog').isVisible());
   assert.equal(await page.evaluate(async()=>{const s=await api('/api/state');return s.cards.filter(c=>!c.approved).length}),1);
   releaseManual();releaseManual=null;holdManual=false;
   await page.waitForFunction(()=>!document.querySelector('#manualReviewDialog').open&&selected&&!selected.approved);
   assert.equal(await page.evaluate(()=>selected.source_text),longText);assert.equal(manualRequests,1);
  });
  await check('card_selection_reuses_gallery_image_elements',async()=>{
   assert(await page.evaluate(()=>{const im=document.querySelector('#gallery img');const a=state.cards.find(c=>c.approved);selectCard(a);const same=document.querySelector('#gallery img')===im;selectCard(state.cards.find(c=>!c.approved));return same&&document.querySelector('#gallery img')===im}));
  });
  const first=registered[0];
  await check('analysis_progress_prevents_duplicate_clicks_and_hide_stays_usable',async()=>{
   holdAnalyze=true;await page.click('#analyzeBtn');for(let i=0;i<150&&!releaseAnalyze;i++)await sleep(30);assert(releaseAnalyze);
   assert(await page.locator('#analyzeBtn').isDisabled());assert((await page.locator('#cardState').textContent()).includes('API 분석 중'));
   await page.evaluate(()=>{document.querySelector('#analyzeBtn').click();void runCardAnalysis()});await sleep(150);assert.equal(analysisRequests,1);
   await page.click('#hideCard');assert.equal(await page.locator('[data-card-id="'+first+'"]').count(),0);
   await page.evaluate(()=>uiSave);await page.click('#hiddenBtn');await page.waitForSelector('[data-card-id="'+first+'"]');await page.locator('[data-card-id="'+first+'"]').click();
   assert((await page.locator('#cardState').textContent()).includes('API 분석 중'));
   releaseAnalyze();releaseAnalyze=null;holdAnalyze=false;
   await page.waitForFunction(()=>document.querySelector('#cardState').textContent.includes('API 상태: ok'));
   assert.equal(analysisRequests,1);assert((await page.evaluate(()=>selected.tags.map(t=>t.tag))).includes('지하철역'));
   await page.click('#hideCard');await page.evaluate(()=>uiSave);await page.click('#hiddenBtn');await page.waitForSelector('[data-card-id="'+first+'"]');
  });
  await check('analysis_status_read_does_not_resend_model_request',async()=>{
   await page.locator('[data-card-id="'+first+'"]').click();const before=analysisRequests;await page.click('#analysisStatusBtn');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('추가 모델 호출'));
   assert.equal(analysisRequests,before);assert(statusRequests>0);
  });
  await check('analysis_failure_is_visible_next_to_button_and_keeps_tags',async()=>{
   const tags=await page.evaluate(()=>JSON.stringify(selected.tags));failAnalysis=true;await page.click('#analyzeBtn');
   await page.waitForFunction(()=>document.querySelector('#cardState').textContent.includes('시험용 출력 토큰 한도'));
   assert.equal(await page.evaluate(()=>JSON.stringify(selected.tags)),tags);assert(await page.locator('#analyzeBtn').isEnabled());failAnalysis=false;
  });
  await check('committed_registration_with_failed_refresh_can_recover_without_reposting',async()=>{
   await review('A second person at a station.');failStateOnce=true;const before=manualRequests;await page.click('#manualConfirm');
   await page.waitForFunction(()=>document.querySelector('#manualReviewStatus').textContent.includes('등록은 완료'));
   assert(await page.locator('#manualReviewDialog').isVisible());assert(await page.locator('#manualConfirm').isHidden());
   await page.click('#manualResultRefresh');await page.waitForFunction(()=>!document.querySelector('#manualReviewDialog').open);
   assert.equal(manualRequests,before+1);
  });
  await check('lost_registration_response_recovers_new_card_without_reposting',async()=>{
   await review('A third person at a station.');loseManualResponse=true;const before=manualRequests;await page.click('#manualConfirm');
   await page.waitForFunction(()=>document.querySelector('#manualReviewStatus').textContent.includes('등록은 완료'));
   loseManualResponse=false;await page.click('#manualResultRefresh');await page.waitForFunction(()=>!document.querySelector('#manualReviewDialog').open);
   assert.equal(manualRequests,before+1);assert.equal(await page.evaluate(()=>selected.source_text),'A third person at a station.');
  });
  await check('existing_same_source_card_does_not_prove_a_failed_registration_succeeded',async()=>{
   await review(longText);rejectManual=true;await page.click('#manualConfirm');
   await page.waitForFunction(()=>document.querySelector('#manualReviewStatus').textContent.includes('등록 결과를 확인하지 못했습니다'));
   assert(!(await page.locator('#manualReviewStatus').textContent()).includes('등록은 완료'));
   assert(await page.locator('#manualConfirm').isVisible());assert(await page.locator('#manualConfirm').isEnabled());
   rejectManual=false;await page.click('[data-close="manualReviewDialog"]');
  });
  await check('baseline_and_quota_are_preserved_and_no_external_provider_is_used',async()=>{
   const current=await page.evaluate(()=>api('/api/state'));assert.equal(JSON.stringify(current.cards.filter(c=>c.approved)),baseline);
   assert.equal(current.api_usage.calls,0);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
  });
  report.status='passed';
 }catch(e){report.status='failed';report.error=String(e.stack||e);process.exitCode=1}
 finally{
  if(releaseManual)releaseManual();if(releaseAnalyze)releaseAnalyze();if(browser)await browser.close();if(child&&child.exitCode===null)child.kill();fs.rmSync(dir,{recursive:true,force:true});
  fs.writeFileSync(path.join(root,'evaluation/api-operation-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
 }
})();
