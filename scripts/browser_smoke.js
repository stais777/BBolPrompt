'use strict';
// Run with node scripts/browser_smoke.js. Uses a disposable profile and library.
// No external API requests are allowed or made by this regression.
const { chromium } = require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs = require('fs'), path = require('path'), os = require('os');
const { spawn, spawnSync } = require('child_process');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const data = fs.mkdtempSync(path.join(os.tmpdir(), 'bbol-browser-'));
const out = path.join(root, 'evaluation'); fs.mkdirSync(out,{recursive:true});
const result = {run_at:new Date().toISOString(),platform:process.platform,browser:'Chromium headless',actual_PT_tested:false,external_api_called:false,checks:[],failures:[]};
let browser, child;
const sleep = ms => new Promise(r=>setTimeout(r,ms));
async function check(name, fn) { console.log('Checking: '+name); await fn(); result.checks.push({name,status:'passed'}); }
(async()=>{
 try {
  child = spawn(process.env.BBOLPROM_PYTHON||'python3',['scripts/browser_fixture_server.py',data],{cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stdout.on('data',b=>logs+=b);child.stderr.on('data',b=>logs+=b);
  const runtime=path.join(data,'runtime.json');
  for(let i=0;i<100&&!fs.existsSync(runtime);i++){if(child.exitCode!==null)throw Error('App startup failed: '+logs);await sleep(100)}
  assert(fs.existsSync(runtime),'runtime.json created');
  const {port}=JSON.parse(fs.readFileSync(runtime));const base='http://127.0.0.1:'+port;
  browser = await chromium.launch({executablePath:process.env.BBOLPROM_CHROMIUM||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  const page=await context.newPage();const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url().split('?')[0]);return route.abort()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.cards.length===309);
  // The product import button now uses fixed-master baselining. Invoke the old
  // diagnostic UI function explicitly only for legacy regression coverage.
  async function diagnosticUpload(filename){const b64=fs.readFileSync(filename).toString('base64');await page.evaluate(async value=>{const a=Uint8Array.from(atob(value),c=>c.charCodeAt(0));await upload(new File([a],'diagnostic.hwpx',{type:'application/zip'}))},b64)}
  await check('approved_309_gallery_readonly',async()=>{
   assert.equal(await page.locator('#gallery article').count(),0);
   await page.setInputFiles('#hwpx',path.join(data,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');await page.click('#baselineCommit');await page.waitForFunction(()=>registeredCards().length===309);
   assert.equal(await page.locator('#gallery article').count(),309);
   await page.locator('#gallery article').first().locator('.thumb').click();assert(await page.locator('#analyzeBtn').isDisabled());
  });
  await check('four_views_and_five_themes',async()=>{
   for(const view of ['grid','basic','large','detail']){await page.click('[data-view="'+view+'"]');await page.waitForFunction(v=>ui.view===v,view);assert.equal(await page.locator('#gallery').getAttribute('class'),'cards mode-'+view)}
   const colors=new Set();for(const theme of ['workstation','vision','cloud','carbon','illustrated']){await page.selectOption('#theme',theme);colors.add(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--bg')))}assert.equal(colors.size,5);
  });
  await check('approved_examples_opt_in_setting_persists_without_enabling_API',async()=>{
   await page.click('#settingsBtn');assert.equal(await page.locator('#apiExamples').isChecked(),false);
   await page.locator('#apiExamples').check();await page.click('#saveApi');
   await page.waitForFunction(()=>state.api.use_approved_examples===true);
   assert.equal(await page.locator('#apiEnabled').isChecked(),false);assert.equal(await page.locator('#apiConsent').isChecked(),false);
   await page.locator('[data-close="settingsDialog"]').click();await page.reload();await page.waitForFunction(()=>state.cards.length===309);
   await page.click('#settingsBtn');assert.equal(await page.locator('#apiExamples').isChecked(),true);
   await page.locator('[data-close="settingsDialog"]').click();assert.equal(external.length,0);
  });
  const pair=await page.evaluate(()=>{for(const c of state.cards){const tags=c.tags.filter(t=>(t.spans||[]).length);if(tags.length>1){const names=tags.slice(0,2).map(tagName);return {names,count:state.cards.filter(x=>names.every(n=>x.tags.some(t=>tagName(t)===n))).length,card:c.id}}}});
  await check('substring_candidates_and_selected_tag_AND_filter',async()=>{
   assert(pair);for(const name of pair.names){await page.fill('#query',name.slice(0,2));await page.locator('#suggestions button').filter({hasText:name}).first().waitFor();
    const exact=page.locator('#suggestions button').filter({hasText:new RegExp('^'+name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'$')});await exact.click();}
   assert.equal(await page.locator('#filters button').count(),2);assert.equal(await page.locator('#gallery article').count(),309);await page.click('#applyTagsBtn');await page.waitForFunction(n=>visibleCards().length===n,pair.count);assert.equal(await page.locator('#gallery article').count(),pair.count);await page.click('#showAllBtn');await page.waitForFunction(()=>!ui.filter_active);assert.equal(await page.locator('#filters button').count(),2);await page.click('#clearTagsBtn');await page.waitForFunction(()=>selectedTags.length===0);
  });
  await check('approved_highlight_preserves_full_source',async()=>{
   await page.locator('#gallery article').first().locator('.thumb').click();
   const valid=await page.evaluate(()=>selected.tags.findIndex(t=>(t.spans||[]).length));assert(valid>=0);
   const before=await page.locator('#source').textContent();await page.locator('#taglist button').nth(valid*2).click();
   assert.equal(await page.locator('#source').textContent(),before);assert(await page.locator('#source mark').count()>0);
   assert(await page.evaluate(()=>{const t=selected.tags.find(t=>t.spans?.length);const cp=Array.from(selected.source_text);return t.spans.every(s=>cp.slice(s.start_cp,s.end_cp).join('')===s.evidence)}));
  });
  const prompt='🙂 한글 브라우저 회귀 검증\n푸른 실험실의 작은 모니터';
  await check('manual_image_and_emoji_prompt_persist',async()=>{
   await page.click('#manualBtn');await page.fill('#manualText',prompt);
   await page.setInputFiles('#manualImages',{name:'neutral.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNwaDjwHwAFBAKAPJ4DgAAAAABJRU5ErkJggg==','base64')});
   await page.click('#saveManual');await page.waitForSelector('#manualReviewDialog[open]');await page.click('#manualConfirm');await page.waitForFunction(()=>state.cards.length===310);await page.selectOption('#scope','new');await page.locator('#gallery article').locator('.thumb').click();
   assert.equal(await page.locator('#source').textContent(),prompt);assert.equal(await page.locator('#imageCount').textContent(),'1 / 1');
   await page.waitForFunction(()=>document.querySelector('#inspectImage').complete&&document.querySelector('#inspectImage').naturalWidth===1);
   await page.reload();await page.waitForFunction(()=>state.cards.length===310);assert.equal(await page.locator('#view').inputValue(),'detail');assert.equal(await page.locator('#theme').inputValue(),'illustrated');
   await page.selectOption('#scope','new');await page.locator('#gallery article').locator('.thumb').click();assert.equal(await page.locator('#source').textContent(),prompt);
  });
  await check('Unicode_codepoint_highlight_after_emoji',async()=>{
   await page.evaluate(()=>highlight({spans:[{start_cp:2,end_cp:4,evidence:'한글'}]}));assert.equal(await page.locator('#source mark').textContent(),'한글');assert.equal(await page.locator('#source').textContent(),prompt);
  });
  await check('manual_tag_edit_evidence_and_codepoint_highlight',async()=>{
   await page.click('#editTagsBtn');await page.waitForSelector('#tagsDialog[open]');await page.click('#addTagRow');
   const row=page.locator('#tagEditRows .review-card').last();await row.locator('input').fill('푸른 실험실');await row.locator('select').selectOption('F');await row.locator('textarea').fill('푸른 실험실');
   await page.click('#saveTags');await page.waitForFunction(()=>!document.querySelector('#tagsDialog').open);await page.waitForFunction(()=>selected.tags.some(t=>(t.tag||t.name)==='푸른 실험실'));
   await page.locator('#taglist button').filter({hasText:/^푸른 실험실$/}).click();assert.equal(await page.locator('#source mark').textContent(),'푸른 실험실');assert.equal(await page.locator('#source').textContent(),prompt);
   assert(await page.evaluate(()=>{const t=selected.tags.find(t=>(t.tag||t.name)==='푸른 실험실');return t.spans.length===1&&Array.from(selected.source_text).slice(t.spans[0].start_cp,t.spans[0].end_cp).join('')==='푸른 실험실'}));
   assert.equal(external.length,0);
  });
  await check('disabled_API_rejected_card_unchanged',async()=>{
   const before=await page.evaluate(()=>JSON.stringify(selected));await page.click('#analyzeBtn');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('API 활성화'));
   assert.equal(await page.evaluate(()=>JSON.stringify(selected)),before);assert.equal(external.length,0);
  });
  await check('legacy_diagnostic_review_and_commit',async()=>{
   await diagnosticUpload(path.join(root,'examples','smoke_2cards.hwpx'));await page.waitForSelector('#reviewDialog[open]');assert.equal(await page.locator('#reviewCards .review-card').count(),2);
   assert.equal(await page.locator('#gallery article').count(),1);await page.click('#commitBtn');await page.waitForFunction(()=>state.cards.length===312);assert.equal(await page.locator('#gallery article').count(),3);
   assert(await page.evaluate(()=>state.cards.filter(c=>!c.approved&&!c.source_text.includes('브라우저 회귀')).every(c=>c.tags.length===0)));
  });
  await check('legacy_diagnostic_duplicate_preserves_card_count',async()=>{
   const before=await page.evaluate(()=>state.cards.filter(c=>!c.approved).reduce((n,c)=>n+c.origins.length,0));
   const buffer=fs.readFileSync(path.join(root,'examples','smoke_2cards.hwpx'));
   const dt=await page.evaluateHandle(b64=>{const a=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));const d=new DataTransfer();d.items.add(new File([a],'dragged.hwpx',{type:'application/zip'}));return d;},buffer.toString('base64'));
   await page.evaluate(async d=>upload(d.files[0]),dt);await page.waitForSelector('#reviewDialog[open]');assert.equal(await page.locator('#reviewCards .review-card').count(),2);
   await page.click('#commitBtn');await page.waitForFunction(()=>!document.querySelector('#reviewDialog').open);await page.waitForFunction(n=>state.cards.filter(c=>!c.approved).reduce((s,c)=>s+c.origins.length,0)>n,before);assert.equal(await page.evaluate(()=>state.cards.length),312);
  });
  await check('duplicate_approved_source_review_guidance_and_diagnostic',async()=>{
   const groups=await page.evaluate(()=>{const map=new Map();for(const c of state.cards.filter(c=>c.approved)){const group=map.get(c.source_text)||[];group.push({id:c.id,card_id:c.card_id});map.set(c.source_text,group)}return [...map.entries()].filter(([,cards])=>cards.length>1).slice(0,2).map(([text,cards])=>({text,cards}))});assert.equal(groups.length,2);
   const fixture=path.join(data,'duplicate-approved.hwpx');const make=spawnSync(process.env.BBOLPROM_PYTHON||'python3',['-c',
    "import json,sys,zipfile,html,base64; groups=json.load(sys.stdin); texts=[groups[0]['text'],groups[0]['text'],groups[1]['text']]; blocks=''.join('<hp:p><hp:run><hp:t>'+html.escape(t)+'</hp:t><hp:pic binaryItemIDRef=\"image'+str(i)+'\"/></hp:run></hp:p>' for i,t in enumerate(texts,1)); z=zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED); z.writestr('Contents/section0.xml','<hp:sec xmlns:hp=\"urn:hancom:hwpml:2011:paragraph\">'+blocks+'</hp:sec>'); png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNwaDjwHwAFBAKAPJ4DgAAAAABJRU5ErkJggg=='); [z.writestr('BinData/image'+str(i)+'.png',png) for i in range(1,4)]; z.close()",fixture],{encoding:'utf8',input:JSON.stringify(groups)});assert.equal(make.status,0,make.stderr);
   await diagnosticUpload(fixture);await page.waitForSelector('#reviewDialog[open]');assert.equal(await page.locator('#reviewCards .review-card').count(),3);
   const summary=await page.locator('#reviewSummary').textContent();assert(summary.includes('3 검토 카드'));assert(summary.includes('3 이미지 참조'));assert(summary.includes('승인 309'));assert(summary.includes('등록 전'));
   assert((await page.locator('#reviewPending').textContent()).includes('3 검토 카드'));
   let posts=0;const countCommit=request=>{if(request.url()===base+'/api/commit')posts++};page.on('request',countCommit);
   await page.click('#commitBtn');assert((await page.locator('#reviewErrors').textContent()).includes('검토 카드 #1'));assert.equal(await page.evaluate(()=>document.activeElement.dataset.reviewIndex),'1');assert.equal(posts,0);assert(await page.locator('#review-card-1').evaluate(el=>el.classList.contains('needs-choice')));
   await page.locator('#review-card-1 .review-target').selectOption(groups[0].cards[0].id);
   assert.equal(await page.locator('#review-card-2 .review-target').inputValue(),groups[0].cards[0].id);assert.equal(await page.locator('#review-card-3 .review-target').inputValue(),'');assert((await page.locator('#reviewPending').textContent()).includes('1 검토 카드'));
   await page.click('#jumpUnresolvedBtn');assert.equal(await page.evaluate(()=>document.activeElement.dataset.reviewIndex),'3');assert((await page.locator('#reviewErrors').textContent()).includes('검토 카드 #3'));
   const downloadPromise=page.waitForEvent('download');await page.click('#diagnosticBtn');const diagnostic=await downloadPromise;const zipPath=await diagnostic.path();
   const verify=spawnSync(process.env.BBOLPROM_PYTHON||'python3',['-c',"import sys,json,zipfile; z=zipfile.ZipFile(sys.argv[1]); names=z.namelist(); assert z.testzip() is None; assert 'report.json' in names; assert 'source/Contents/section0.xml' in names; assert not any('bindata/' in n.lower() or n.lower().endswith(('.png','.jpg','.bmp')) for n in names); r=json.loads(z.read('report.json')); assert r['extraction']['card_count']==3; assert r['extraction']['image_reference_count']==3; assert r['actual_PT_quality_tested'] is False",zipPath],{encoding:'utf8'});assert.equal(verify.status,0,verify.stderr);
   assert.equal(posts,0);await page.locator('#review-card-3 .review-target').selectOption(groups[1].cards[0].id);assert(await page.locator('#jumpUnresolvedBtn').isHidden());
   await page.click('#commitBtn');await page.waitForFunction(()=>!document.querySelector('#reviewDialog').open);await page.waitForFunction(()=>state.cards.length===312);assert.equal(posts,1);page.off('request',countCommit);
   await diagnosticUpload(fixture);await page.waitForSelector('#reviewDialog[open]');assert(await page.locator('#jumpUnresolvedBtn').isHidden());assert.equal(await page.locator('#review-card-1 .review-target').inputValue(),groups[0].cards[0].id);assert.equal(await page.locator('#review-card-3 .review-target').inputValue(),groups[1].cards[0].id);await page.locator('#reviewDialog [data-close="reviewDialog"]').click();
  });
  for(const [button,label] of [['#backupBtn','backup_download'],['#exportBtn','xlsx_download']])await check(label,async()=>{
   const pending=page.waitForEvent('download');await page.click(button);const download=await pending;const p=await download.path();assert(fs.statSync(p).size>100);assert.equal(fs.readFileSync(p).subarray(0,2).toString(),'PK');const verify=spawnSync(process.env.BBOLPROM_PYTHON||'python3',['-c',
    'import sys,zipfile,sqlite3,tempfile,pathlib,xml.etree.ElementTree as E; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; names=z.namelist(); kind=sys.argv[2]; '+
    "assert ('library.sqlite3' in names) if kind=='backup_download' else ('xl/workbook.xml' in names); "+
    "E.fromstring(z.read('xl/worksheets/sheet1.xml')) if kind=='xlsx_download' else None",p,label],{encoding:'utf8'});assert.equal(verify.status,0,verify.stderr);
  });
  await check('reload_persists_three_new_cards',async()=>{await page.reload();await page.waitForFunction(()=>state.cards.length===312);await page.selectOption('#scope','new');assert.equal(await page.locator('#gallery article').count(),3)});
  await page.locator('#gallery article').filter({hasText:'브라우저 회귀'}).locator('.thumb').click();await page.locator('#taglist button').filter({hasText:/^푸른 실험실$/}).click();assert.equal(await page.locator('#source mark').textContent(),'푸른 실험실');
  await page.click('[data-view="grid"]');await page.screenshot({path:path.join(out,'browser-smoke.png'),fullPage:true});
  await check('no_javascript_errors_or_external_network',async()=>{assert.deepEqual(errors,[]);assert.deepEqual(external,[])});
  result.status='passed';
 } catch(e) {result.status='failed';result.failures.push({message:e.message,stack:e.stack});process.exitCode=1;}
 finally {if(browser)await browser.close();if(child){child.kill('SIGTERM');await sleep(150)}fs.rmSync(data,{recursive:true,force:true});fs.writeFileSync(path.join(out,'browser-smoke.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,passed:result.checks.length,failures:result.failures},null,2));}
})();
