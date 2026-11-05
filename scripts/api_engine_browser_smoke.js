'use strict';
// Actual browser UI, disposable source/DB, injected mock provider; no real API.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict'),{spawn,spawnSync}=require('child_process');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-api-engine-ui-'));
const result={checks:[],live_API_called:false,native_Windows_tested:false,actual_PT_tested:false,provider:'injected synthetic mock'};
let child,browser,page,base,baselineSnapshot;const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function check(name,fn){console.log(name);await fn();result.checks.push(name)}
async function create(text){await page.click('#manualBtn');await page.fill('#manualText',text);await page.click('#saveManual');await page.waitForSelector('#manualReviewDialog[open]');await page.click('#manualConfirm');await page.waitForFunction(t=>state.cards.some(c=>!c.approved&&c.source_text===t),text);return page.evaluate(t=>state.cards.find(c=>!c.approved&&c.source_text===t).id,text)}
async function select(id){await page.locator('[data-card-id="'+id+'"] .thumb').click()}
async function status(){return page.locator('#status').textContent()}
(async()=>{
 try{
  child=spawn('python3',['scripts/browser_fixture_server.py',dir,'--mock-api-engine'],{cwd:root,stdio:['ignore','pipe','pipe']});let stderr='';child.stderr.on('data',b=>stderr+=b);
  const ready=path.join(dir,'runtime.json');for(let i=0;i<150&&!fs.existsSync(ready);i++){if(child.exitCode!==null)throw Error(stderr);await pause(100)}
  base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(ready)).port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});page=await browser.newPage({viewport:{width:1550,height:1000},acceptDownloads:true});
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>{if(r.request().url().startsWith(base+'/'))return r.continue();external.push(r.request().url());return r.abort()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.cards.length===309);
  await check('baseline_registration_stays_fixed_and_api_reanalysis_disabled',async()=>{
   await page.setInputFiles('#hwpx',path.join(dir,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');await page.click('#baselineCommit');await page.waitForFunction(()=>state.baseline.complete);
   assert.equal(await page.locator('#gallery article').count(),309);await select('approved-1');assert(await page.locator('#analyzeBtn').isDisabled());assert(await page.locator('#engineTagHistoryBtn').isDisabled());
   baselineSnapshot=await page.evaluate(()=>JSON.stringify(state.cards.filter(c=>c.approved)));
  });
  await check('drafts_require_explicit_confirmation_without_reclassifying_baseline',async()=>{
   await page.click('#settingsBtn');assert.equal(await page.locator('#apiCorrections').isChecked(),false);await page.click('#loadEngineBtn');await page.waitForSelector('#engineDefinitions details');
   assert.equal(await page.locator('#engineDefinitions details').count(),7);assert((await page.locator('#engineStatus').textContent()).includes('정의 확정 0 / 7'));
   await page.click('#approveEngineDefinitions');await page.waitForFunction(()=>document.querySelector('#engineStatus').textContent.includes('정의 확정 7 / 7'));
   await page.locator('#apiEnabled').check();await page.locator('#apiConsent').check();await page.locator('#apiCorrections').check();await page.click('#saveApi');await page.waitForFunction(()=>state.api.enabled&&state.api.use_user_corrections);
   await page.locator('[data-close="settingsDialog"]').click();
  });
  let first,second;
  await check('new_card_mock_analysis_has_exact_highlight_and_engine_history',async()=>{
   first=await create('A person waits at a subway station.');await select(first);await page.click('#analyzeBtn');await page.waitForFunction(()=>selected.tags.some(t=>t.tag==='지하철역'));
   await page.locator('#taglist button.tag').filter({hasText:/^지하철역$/}).click();assert.equal(await page.locator('#source mark').textContent(),'subway station');
   await page.click('#engineTagHistoryBtn');await page.waitForSelector('#engineTagHistoryDialog[open]');assert((await page.locator('#engineTagVersions').textContent()).includes('api_result'));await page.locator('[data-close="engineTagHistoryDialog"]').click();
  });
  await check('manual_rename_and_exclusion_survive_reanalysis_without_full_archive_per_tag',async()=>{
   await page.click('#editTagsBtn');await page.waitForSelector('#tagsDialog[open]');await page.locator('#tagEditRows input').first().fill('사용자 확정 역');await page.click('#saveTags');await page.waitForFunction(()=>!document.querySelector('#tagsDialog').open);
   const before=fs.readdirSync(path.join(dir,'backup')).filter(n=>n.endsWith('.zip')).length;
   await page.click('#analyzeBtn');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('API 상태:'));
   assert.deepEqual(await page.evaluate(()=>selected.tags.map(t=>t.tag)),['사용자 확정 역']);assert.equal(fs.readdirSync(path.join(dir,'backup')).filter(n=>n.endsWith('.zip')).length,before);
  });
  await check('correction_can_be_withdrawn_while_current_manual_tags_remain',async()=>{
   await page.click('#settingsBtn');await page.click('#loadEngineBtn');await page.locator('#engineCorrections').locator('..').locator('summary').click();await page.waitForSelector('#engineCorrections button');
   assert((await page.locator('#engineCorrections').textContent()).includes('사용자 확정 역'));await page.locator('#engineCorrections button').first().click();await page.waitForFunction(()=>document.querySelector('#engineCorrections button').textContent.includes('다시 참고'));
   await page.locator('[data-close="settingsDialog"]').click();assert.deepEqual(await page.evaluate(()=>selected.tags.map(t=>t.tag)),['사용자 확정 역']);
  });
  await check('repeated_evidence_needs_context_and_never_colors_every_ambiguous_position',async()=>{
   second=await create('A station beside another station.');await select(second);await page.click('#analyzeBtn');await page.waitForFunction(()=>selected.tags.length===1);
   assert.equal(await page.evaluate(()=>selected.tags[0].spans.length),0);assert.equal(await page.evaluate(()=>selected.tags[0].category_id),null);
  });
  await check('tag_history_restores_user_version_and_survives_reload',async()=>{
   await select(first);await page.click('#engineTagHistoryBtn');await page.waitForSelector('#engineTagHistoryDialog[open]');
   const version=page.locator('#engineTagVersions details').filter({hasText:'user_edit'}).first();await version.locator('summary').click();await version.locator('button').click();await page.waitForFunction(()=>!document.querySelector('#engineTagHistoryDialog').open);
   await page.reload();await page.waitForFunction(()=>state.cards.length===311);await select(first);assert.deepEqual(await page.evaluate(()=>selected.tags.map(t=>t.tag)),['사용자 확정 역']);
   assert.equal(await page.evaluate(()=>state.cards.filter(c=>c.approved).reduce((n,c)=>n+c.tags.length,0)),8471);
   assert.equal(await page.evaluate(()=>JSON.stringify(state.cards.filter(c=>c.approved))),baselineSnapshot);
  });
  await check('API_engine_audits_are_mock_and_no_external_calls_or_JS_errors',async()=>{
   const response=await page.evaluate(()=>api('/api/engine/status',{}));assert.equal(response.counts.api_runs,3);
   const proof=spawnSync('python3',['-c',"import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); assert c.execute(\"SELECT count(*) FROM api_runs WHERE mode!='mock'\").fetchone()[0]==0; c.close()",path.join(dir,'library.sqlite3')],{encoding:'utf8'});assert.equal(proof.status,0,proof.stderr);
   assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
  });
  result.status='passed';
 }catch(e){result.status='failed';result.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();if(child&&child.exitCode===null)child.kill();fs.rmSync(dir,{recursive:true,force:true});fs.writeFileSync(path.join(root,'evaluation/api-engine-browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))}
})()
