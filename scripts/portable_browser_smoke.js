'use strict';
// Portable data with synthetic HWPX/media. No remote API or native Windows.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict'),{spawn,spawnSync}=require('child_process');
const root=path.resolve(__dirname,'..'),sandbox=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-portable-ui-'));
let data=path.join(sandbox,'첫 PC #1','data'),base,child,browser,page;
const result={checks:[],actual_PT_tested:false,live_API_called:false,native_Windows_tested:false};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function check(name,fn){console.log(name);await fn();result.checks.push(name)}
async function start(reuse=false){
 fs.mkdirSync(data,{recursive:true});fs.rmSync(path.join(data,'runtime.json'),{force:true});
 child=spawn('python3',['scripts/browser_fixture_server.py',data,'--portable',...(reuse?['--reuse-source']:[])],{cwd:root,stdio:['ignore','pipe','pipe']});let errors='';child.stderr.on('data',b=>errors+=b);
 for(let i=0;i<150&&!fs.existsSync(path.join(data,'runtime.json'));i++){if(child.exitCode!==null)throw Error(errors);await pause(100)}
 base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(path.join(data,'runtime.json'))).port;
}
async function stop(){if(child&&child.exitCode===null){const ended=new Promise(r=>child.once('exit',r));child.kill();await ended}child=null}
(async()=>{
 try{
  await start();browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  page=await browser.newPage({viewport:{width:1500,height:1040},acceptDownloads:true});const external=[],errors=[],allowed=new Set([base]);
  page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>{if([...allowed].some(origin=>route.request().url().startsWith(origin+'/')))return route.continue();external.push(route.request().url());return route.abort()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.storage!==undefined);
  let source,sha,cardId;
  await check('first_registration_copies_PT_into_data_before_showing_registered309',async()=>{
   assert.equal(await page.evaluate(()=>state.storage.mode),'portable');assert.equal(await page.locator('#gallery article').count(),0);
   source=fs.readFileSync(path.join(data,'synthetic.hwpx'));sha=require('crypto').createHash('sha256').update(source).digest('hex');
   await page.setInputFiles('#hwpx',path.join(data,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');await page.click('#baselineCommit');
   await page.waitForFunction(()=>registeredCards().length===309&&state.storage.baseline_source_saved===true);
   assert.deepEqual(fs.readFileSync(path.join(data,'sources','PT.hwpx')),source);assert((await page.locator('#storageInfo').textContent()).includes('PT 원본 보관됨'));
  });
  await check('registered_library_can_store_PT_again_without_reopening_mapping_review',async()=>{
   await page.setInputFiles('#hwpx',{name:'같은 원본 다른 위치.hwpx',mimeType:'application/zip',buffer:source});
   await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('기존 카드·태그·이미지 연결은 유지'));
   assert.equal(await page.locator('#baselineDialog').evaluate(e=>e.open),false);assert.equal(await page.evaluate(()=>state.cards.length),309);
   assert.equal(require('crypto').createHash('sha256').update(fs.readFileSync(path.join(data,'sources','PT.hwpx'))).digest('hex'),sha);
  });
  await check('wrong_PT_does_not_replace_retained_source',async()=>{
   await page.setInputFiles('#hwpx',{name:'wrong.hwpx',mimeType:'application/zip',buffer:Buffer.from('wrong')});await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('SHA256'));
   assert.deepEqual(fs.readFileSync(path.join(data,'sources','PT.hwpx')),source);
  });
  const prompt='새 카드 원문 😀\n줄바꿈과  공백',png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNwaDjwHwAFBAKAPJ4DgAAAAABJRU5ErkJggg==','base64');
  await check('new_card_keeps_readable_original_text_and_image_in_its_own_folder',async()=>{
   await page.click('#manualBtn');await page.fill('#manualText',prompt);await page.setInputFiles('#manualImages',{name:'한글 원본.PNG',mimeType:'image/png',buffer:png});
   await page.click('#saveManual');await page.waitForSelector('#manualReviewDialog[open]');await page.click('#manualConfirm');await page.waitForFunction(()=>state.cards.length===310);
   cardId=await page.evaluate(()=>state.cards.find(c=>!c.approved).id);
   const folder=path.join(data,'new_cards',cardId),files=fs.readdirSync(folder),text=files.find(n=>n.startsWith('원문-')&&n.endsWith('.txt'));
   assert.equal(fs.readFileSync(path.join(folder,text),'utf8'),prompt);
   const original=fs.readdirSync(path.join(folder,'originals')).find(n=>n.endsWith('한글 원본.PNG'));
   assert.deepEqual(fs.readFileSync(path.join(folder,'originals',original)),png);
   await page.locator('[data-card-id="'+cardId+'"] .thumb').click();assert.equal(await page.locator('#cardFolderBtn').isDisabled(),false);
   await page.locator('#inspectImage').click();
   if(await page.locator('#zoomDialog').evaluate(e=>e.open))await page.locator('[data-close="zoomDialog"]').click();
  });
  await check('explicit_baseline_tag_edit_is_saved_before_portable_move',async()=>{
   await page.locator('[data-card-id="approved-1"] .thumb').click();await page.click('#editTagsBtn');
   await page.locator('#tagEditRows .review-card').first().locator('input').fill('휴대형_사용자확정태그');await page.click('#saveTags');
   await page.waitForFunction(()=>!document.querySelector('#tagsDialog').open&&selected.tag_revision===1);
  });
  await check('move_to_a_new_path_preserves_mapping_originals_and_user_editions',async()=>{
   // The external selected document is no longer present.
   fs.unlinkSync(path.join(data,'synthetic.hwpx'));await stop();
   const destination=path.join(sandbox,'새 PC 다른 사용자 #2','data');fs.cpSync(data,destination,{recursive:true});data=destination;
   await start(true);allowed.add(base);await page.goto(base+'/');await page.waitForFunction(()=>state.storage!==undefined);
   assert.equal(await page.evaluate(()=>registeredCards().length),310);
   assert.equal(await page.evaluate(()=>state.storage.baseline_source_saved),true);
   assert.equal(await page.evaluate(()=>state.storage.data_path),data);
   const original=await page.evaluate(()=>state.cards.find(c=>c.id==='approved-1'));
   assert.equal(original.tag_revision,1);assert.equal(original.tags[0].tag,'휴대형_사용자확정태그');
   await page.locator('[data-card-id="'+cardId+'"] .thumb').click();assert.equal(await page.locator('#source').textContent(),prompt);
   await page.waitForFunction(()=>document.querySelector('#inspectImage').complete&&document.querySelector('#inspectImage').naturalWidth===1);
   assert.deepEqual(fs.readFileSync(path.join(data,'sources','PT.hwpx')),source);
  });
  await check('moved_library_diagnostic_rechecks_source_and_original_files',async()=>{
   const pending=page.waitForEvent('download');await page.click('#localDiagnosticBtn');const download=await pending;
   const proc=spawnSync('python3',['-c',`import sys,json,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:d=json.loads(z.read('report.json'))
assert d['acceptance']=='passed_integrity'
assert d['counts']['fixed_cards']==309 and d['counts']['linked_image_references']==531
assert d['original_storage']['source_document_count']==1 and d['original_storage']['new_card_original_files']==2
assert not d['original_storage']['errors'] and d['manual_tag_edits']['edited_card_count']==1
assert '휴대형_사용자확정태그' not in json.dumps(d,ensure_ascii=False)
print('moved original storage checks passed')`,await download.path()],{encoding:'utf8'});assert.equal(proc.status,0,proc.stderr);
  });
  await check('full_backup_includes_PT_and_per_card_originals',async()=>{
   const pending=page.waitForEvent('download');await page.click('#backupBtn');const download=await pending;
   const proc=spawnSync('python3',['-c',`import sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
 assert 'sources/PT.hwpx' in z.namelist() and 'library.sqlite3' in z.namelist()
 assert any(n.startswith('new_cards/') for n in z.namelist())
 assert 'api-safety.sqlite3' not in z.namelist()
 assert z.testzip() is None`,await download.path()],{encoding:'utf8'});assert.equal(proc.status,0,proc.stderr);
  });
  assert.deepEqual(external,[]);assert.deepEqual(errors,[]);result.status='passed';
 }catch(e){result.status='failed';result.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();await stop();fs.rmSync(sandbox,{recursive:true,force:true});fs.writeFileSync(path.join(root,'evaluation/portable-browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))}
})();
