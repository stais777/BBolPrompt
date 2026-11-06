'use strict';
// Real local app/storage + synthetic provider. No real key, image, prompt or paid call.
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const {spawn}=require('child_process');
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-review-'));
const report={checks:[],external_API_called:false,real_key_used:false,native_Windows_tested:false};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));let browser,child;
async function check(name,fn){await fn();report.checks.push({name,status:'passed'});console.log(name)}
(async()=>{
 try{
  child=spawn('python3',['scripts/browser_fixture_server.py',dir,'--mock-review-engine'],{cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stderr.on('data',b=>logs+=b);const ready=path.join(dir,'runtime.json');
  for(let i=0;i<150&&!fs.existsSync(ready);i++){if(child.exitCode!==null)throw Error(logs);await sleep(100)}assert(fs.existsSync(ready));
  const base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(ready)).port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1560,height:1100}}),errors=[],external=[];let analyses=0,tagWrites=0;
  page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>{const r=route.request();if(!r.url().startsWith(base+'/')){external.push(r.url());return route.abort()}if(r.url()===base+'/api/analyze')analyses++;if(r.url()===base+'/api/tags')tagWrites++;return route.continue()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.cards.length===309);
  await page.setInputFiles('#hwpx',path.join(dir,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');await page.click('#baselineCommit');await page.waitForFunction(()=>state.baseline.complete);
  const baseline=await page.evaluate(()=>JSON.stringify(state.cards.filter(c=>c.approved)));
  const source='A person in a blue jacket waits at a subway station.';
  const id=await page.evaluate(async text=>{
   const d=await api('/api/engine/definitions',{});await api('/api/engine/definitions',{operation:'approve',definitions:d.definitions.map(x=>Object.fromEntries(['id','definition','include','exclude'].map(k=>[k,x[k]]))),expected_token:d.token});
   await api('/api/settings',{api:{enabled:true,consent:true,model:'fixture'}});const r=await api('/api/manual',{text,images:[],origin_filename:'neutral-review'});await refresh();selectCard(state.cards.find(c=>c.id===r.id));return r.id;
  },source);
  await check('partial_result_is_saved_and_explained_as_completed_with_pending_candidates',async()=>{
   await page.click('#analyzeBtn');await page.waitForFunction(()=>selected.analysis_status==='partial'&&document.querySelector('#cardState').textContent.includes('분석 완료 · 분류'));
   assert((await page.locator('#cardState').textContent()).includes('분석 완료 · 분류 1개 · 미분류 1개'));
   assert.equal(await page.evaluate(()=>selected.tags.length),2);assert.equal(analyses,1);
  });
  const saved=await page.evaluate(()=>JSON.stringify(selected.tags));
  await check('pending_reason_is_literal_redacted_text_and_reference_does_not_assign_category',async()=>{
   await page.locator('#taglist .tag').filter({hasText:/^지하철역$/}).click();const panel=page.locator('#tagReview');assert(await panel.isVisible());
   const text=await panel.textContent();assert(text.includes('분류 검토 필요 <img'));assert(text.includes('[키 비공개]'));assert(!text.includes('sk-synthetic'));
   assert(text.includes('장소·배경 (F)'));assert(text.includes('분류를 변경하지 않습니다'));assert.equal(await panel.locator('img').count(),0);assert.equal(await page.evaluate(()=>window.REVIEW_XSS),undefined);
   assert.equal(await page.evaluate(()=>selected.tags.find(t=>t.tag==='지하철역').category_id),null);assert.equal(tagWrites,0);
  });
  await check('validated_evidence_and_highlight_preserve_exact_source',async()=>{
   assert((await page.locator('#tagReview').textContent()).includes('subway station'));assert.equal(await page.locator('#source mark').textContent(),'subway station');assert.equal(await page.locator('#source').textContent(),source);
  });
  await check('classified_new_label_and_detailed_view_show_their_own_reason',async()=>{
   await page.locator('#taglist .tag').filter({hasText:/^푸른 재킷$/}).click();assert((await page.locator('#tagReview').textContent()).includes('원문에서 복장을 확인했습니다.'));assert((await page.locator('#tagReview').textContent()).includes('같은 이름의 기준 태그는 없습니다'));
   await page.click('#detailBtn');await page.locator('#detailTags .tag').filter({hasText:/^지하철역$/}).click();assert(await page.locator('#detailTagReview').isVisible());assert.equal(await page.locator('#detailSource mark').textContent(),'subway station');await page.click('#detailDialog [data-close="detailDialog"]');
  });
  await check('review_edit_button_opens_existing_editor_without_automatic_save',async()=>{
   await page.locator('#tagReview button').click();await page.waitForSelector('#tagsDialog[open]');assert.equal(tagWrites,0);await page.click('#tagsDialog [data-close="tagsDialog"]');assert.equal(await page.evaluate(()=>JSON.stringify(selected.tags)),saved);
  });
  await check('card_switch_and_refresh_reset_details_without_API_or_baseline_changes',async()=>{
   await page.evaluate(()=>selectCard(state.cards.find(c=>c.approved)));assert(await page.locator('#tagReview').isHidden());await page.locator('#taglist .tag').first().click();assert(await page.locator('#tagReview').isHidden());
   await page.evaluate(async id=>{selectCard(state.cards.find(c=>c.id===id));await refresh()},id);const status=await page.locator('#cardState').textContent();assert(status.includes('분석 완료')&&status.includes('미분류'));
   assert.equal(await page.evaluate(()=>JSON.stringify(state.cards.filter(c=>c.approved))),baseline);assert.equal(await page.evaluate(()=>JSON.stringify(selected.tags)),saved);assert.equal(analyses,1);assert.equal(tagWrites,0);assert.equal(await page.evaluate(()=>state.api_usage.calls),0);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  });
  report.status='passed';
 }catch(e){report.status='failed';report.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();if(child&&child.exitCode===null)child.kill();fs.rmSync(dir,{recursive:true,force:true});fs.writeFileSync(path.join(root,'evaluation/tag-review-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2))}
})();
