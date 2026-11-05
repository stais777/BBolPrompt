'use strict';
// Real local UI + SQLite + synthetic HWPX, no real user data or remote API.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict'),{spawn,spawnSync}=require('child_process');
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-manual-tags-'));
const result={checks:[],actual_PT_tested:false,live_API_called:false,native_Windows_tested:false};
let child,browser;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function check(name,fn){console.log(name);await fn();result.checks.push(name)}
function snapshot(){const p=spawnSync('python3',['-c',`import sqlite3,json,hashlib,sys
c=sqlite3.connect(sys.argv[1]);d={n:list(c.execute('SELECT * FROM '+n+' ORDER BY 1,2')) for n in ['baseline_cards','baseline_image_links','baseline_sources']}
print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest());c.close()`,path.join(data,'library.sqlite3')],{encoding:'utf8'});assert.equal(p.status,0,p.stderr);return p.stdout.trim()}
(async()=>{
 try{
  child=spawn('python3',['scripts/browser_fixture_server.py',data],{cwd:root,stdio:['ignore','pipe','pipe']});let stderr='';child.stderr.on('data',b=>stderr+=b);
  for(let i=0;i<100&&!fs.existsSync(path.join(data,'runtime.json'));i++){if(child.exitCode!==null)throw Error(stderr);await pause(100)}
  const base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(path.join(data,'runtime.json'))).port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1500,height:1040},acceptDownloads:true}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.ui!==undefined);
  let original,index,id,baselineHash;
  await check('registered_baseline_allows_manual_tags_and_history_only',async()=>{
   await page.setInputFiles('#hwpx',path.join(data,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');await page.click('#baselineCommit');await page.waitForFunction(()=>registeredCards().length===309);
   original=await page.evaluate(()=>state.cards.find(c=>c.approved&&c.tags.some(t=>t.spans?.length>1)));
   id=original.id;index=original.tags.findIndex(t=>t.spans?.length>1);baselineHash=snapshot();
   await page.locator('[data-card-id="'+id+'"] .thumb').click();assert.equal(await page.locator('#editTagsBtn').isDisabled(),false);assert.equal(await page.locator('#historyBtn').isDisabled(),false);
   assert.equal(await page.locator('#editCardBtn').isDisabled(),true);assert.equal(await page.locator('#analyzeBtn').isDisabled(),true);
  });
  const name='사용자_수동확정_화면시험';
  await check('manual_rename_preserves_original_multispan_highlighting',async()=>{
   await page.click('#editTagsBtn');await page.locator('#tagEditRows .review-card').nth(index).locator('input').fill(name);await page.click('#saveTags');
   await page.waitForFunction(()=>!document.querySelector('#tagsDialog').open&&selected.tag_revision===1);
   assert.deepEqual(await page.evaluate(i=>selected.tags[i].spans,index),original.tags[index].spans);
   assert.equal(await page.evaluate(i=>tagName(selected.tags[i]),index),name);
   await page.locator('#taglist .tag').filter({hasText:name}).click();assert(await page.locator('#source mark').count()>0);
   assert.equal(await page.locator('#source').textContent(),original.source_text);assert.equal(snapshot(),baselineHash);
  });
  await check('manual_edition_survives_reload',async()=>{
   await page.reload();await page.waitForFunction(()=>state.cards.length===309);await page.locator('[data-card-id="'+id+'"] .thumb').click();
   assert.equal(await page.evaluate(()=>selected.tag_revision),1);assert.equal(await page.evaluate(i=>tagName(selected.tags[i]),index),name);
  });
  await check('category_deactivation_cannot_reclassify_fixed_or_manually_edited_tags',async()=>{
   const cid=original.tags[index].category_column,before=await page.evaluate(()=>JSON.stringify(state.cards.map(c=>c.tags)));
   await page.evaluate(async cid=>{await api('/api/categories',{operation:'deactivate',id:cid});await refresh()},cid);
   assert.equal(await page.evaluate(()=>JSON.stringify(state.cards.map(c=>c.tags))),before);
   assert.equal(snapshot(),baselineHash);
  });
  await check('user_can_add_a_tag_without_fabricated_evidence',async()=>{
   await page.click('#editTagsBtn');await page.click('#addTagRow');await page.locator('#tagEditRows .review-card').last().locator('input').fill('사용자_새태그_근거없음');await page.click('#saveTags');
   await page.waitForFunction(()=>!document.querySelector('#tagsDialog').open&&selected.tag_revision===2);
   assert.deepEqual(await page.evaluate(()=>selected.tags.at(-1).spans),[]);
  });
  async function restore(target,expected){
   await page.click('#historyBtn');await page.waitForSelector('#baselineTagHistoryDialog[open]');
   const row=page.locator('#baselineTagVersions details[data-revision="'+target+'"]');await row.locator('summary').click();await row.locator('button').click();
   await page.waitForFunction(revision=>!document.querySelector('#baselineTagHistoryDialog').open&&selected.tag_revision===revision,expected);
  }
  await check('history_restores_prior_edit_original_and_edit_again',async()=>{
   await restore(1,3);assert.equal(await page.evaluate(()=>selected.tags.length),original.tags.length);
   await restore(0,4);assert.deepEqual(await page.evaluate(()=>selected.tags),original.tags);
   await restore(2,5);assert.equal(await page.evaluate(()=>selected.tags.length),original.tags.length+1);
   assert.equal(await page.evaluate(i=>tagName(selected.tags[i]),index),name);assert.equal(snapshot(),baselineHash);
  });
  await check('invalid_evidence_error_is_visible_without_saving',async()=>{
   await page.click('#editTagsBtn');await page.click('#addTagRow');const row=page.locator('#tagEditRows .review-card').last();await row.locator('input').fill('실패시험');await row.locator('textarea').fill('not_in_source_literal_778193724');await page.click('#saveTags');
   await page.waitForFunction(()=>document.querySelector('#tagEditError').textContent.length>0);
   assert.equal(await page.locator('#tagEditError').isVisible(),true);assert.equal(await page.evaluate(()=>selected.tag_revision),5);
   await page.locator('[data-close="tagsDialog"]').click();
  });
  await check('diagnostic_keeps_original_integrity_and_separate_user_revision_counts',async()=>{
   const pending=page.waitForEvent('download');await page.click('#localDiagnosticBtn');const download=await pending;
   const p=spawnSync('python3',['-c',`import json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:d=json.loads(z.read('report.json'))
assert d['acceptance']=='passed_integrity' and d['counts']['tag_mappings']==8471 and d['counts']['spans']==10358
assert d['manual_tag_edits']['edition_count']==5 and d['manual_tag_edits']['edited_card_count']==1
assert not d['manual_tag_edits']['errors']
assert '사용자_수동확정_화면시험' not in json.dumps(d,ensure_ascii=False)
print('Original309 and user edition audit passed')`,await download.path()],{encoding:'utf8'});assert.equal(p.status,0,p.stderr);
  });
  await check('API_reanalysis_stays_blocked_after_user_edit',async()=>{
   const rejected=await page.evaluate(async()=>{try{await api('/api/analyze',{id:selected.id});return false}catch(e){return e.message.includes('신규 등록 카드')}});
   assert(rejected);assert.equal(await page.evaluate(()=>selected.tag_revision),5);assert.equal(snapshot(),baselineHash);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);result.status='passed';
 }catch(e){result.status='failed';result.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();if(child)child.kill();fs.rmSync(data,{recursive:true,force:true});fs.writeFileSync(path.join(root,'evaluation/baseline-manual-browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))}
})();
