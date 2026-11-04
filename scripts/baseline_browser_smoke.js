'use strict';
// Synthetic transport/UI regression only. The SHA patch exists solely in this
// disposable test process, never in the production app or a Windows build.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const {spawn}=require('child_process');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-baseline-browser-'));
const output={actual_PT_tested:false,external_api_called:false,fixture_source_sha_patched_in_test_process_only:true,checks:[]};
let child,browser;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function check(name,fn){await fn();output.checks.push(name);console.log('Passed: '+name)}
(async()=>{
 try{
  const python=`import sys,json,zipfile,hashlib,base64,struct
from pathlib import Path
from bbolprom_engine.app import make_server
import bbolprom_engine.baseline as baseline
folder=Path(sys.argv[1]);server=make_server(folder/'library')
fixture=folder/'synthetic.hwpx'
png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNwaDjwHwAFBAKAPJ4DgAAAAABJRU5ErkJggg==')
bmp=b'BM'+struct.pack('<IHHI',58,0,0,54)+struct.pack('<IiiHHIIiiII',40,1,1,1,24,0,4,2835,2835,0,0)+bytes([64,128,192,0])
with zipfile.ZipFile(fixture,'w',zipfile.ZIP_DEFLATED) as z:
 for name in server.application.baseline.paths:z.writestr(name,(bmp if name.endswith('.BMP') else png)+name.encode())
baseline.SOURCE_SHA=hashlib.sha256(fixture.read_bytes()).hexdigest()
(folder/'ready.json').write_text(json.dumps({'port':server.server_port}))
server.serve_forever()
`;
  child=spawn('python3',['-c',python,temp],{cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stderr.on('data',b=>logs+=b);
  for(let i=0;i<100&&!fs.existsSync(path.join(temp,'ready.json'));i++){
   if(child.exitCode!==null)throw Error('Startup failed: '+logs);await pause(100);
  }
  const {port}=JSON.parse(fs.readFileSync(path.join(temp,'ready.json'))),base='http://127.0.0.1:'+port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.cards.length===309);
  await check('fixed_IDs_and_188_zero_images_before_attachment',async()=>{
   assert.deepEqual(await page.evaluate(()=>state.cards.filter(c=>c.card_id===188).map(c=>c.images.length)),[0]);
   assert.equal(await page.evaluate(()=>state.baseline.registered_cards),309);
   assert.equal(await page.evaluate(()=>state.baseline.linked_image_references),0);
  });
  await check('unknown_source_rejected_by_product_import_button_without_registration',async()=>{
   await page.setInputFiles('#hwpx',{name:'unknown.hwpx',mimeType:'application/zip',buffer:Buffer.from('unknown document')});
   await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('SHA256'));
   assert.equal(await page.locator('#baselineDialog').isVisible(),false);
   assert.equal(await page.evaluate(()=>state.cards.length),309);
  });
  async function upload(){await page.setInputFiles('#hwpx',path.join(temp,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]')}
  await check('review_309_readonly_ids_with_109_110_ordered_refs_and_cancel',async()=>{
   await upload();assert.equal(await page.locator('#baselineCards details').count(),309);
   assert.equal(await page.locator('#baselineCards img').count(),531);
   assert.equal(await page.locator('#baselineCards textarea').count(),0);
   assert.equal(await page.locator('#baselineCards [data-card-id="109"] img').count(),1);
   assert.equal(await page.locator('#baselineCards [data-card-id="110"] img').count(),14);
   assert.deepEqual(await page.locator('#baselineCards [data-card-id="110"] img').evaluateAll(imgs=>imgs.map(i=>i.alt)),Array.from({length:14},(_,i)=>'image'+(196+i)));
   assert.equal(await page.locator('#baselineCards [data-card-id="188"] img').count(),0);
   const cancelled=page.waitForResponse(r=>r.url().endsWith('/api/cancel'));await page.click('#baselineCancel');await cancelled;
   assert.equal(await page.evaluate(()=>state.baseline.linked_image_references),0);
   assert.equal(fs.readdirSync(path.join(temp,'library/pending')).length,0);
  });
  await check('review_commit_and_repeat_keep_309_cards_and_531_links',async()=>{
   for(let i=0;i<2;i++){
    await upload();await page.click('#baselineCommit');await page.waitForFunction(()=>!document.querySelector('#baselineDialog').open);
    await page.waitForFunction(()=>state.baseline.complete===true);
    assert.equal(await page.evaluate(()=>state.cards.length),309);
    assert.equal(await page.evaluate(()=>state.cards.reduce((n,c)=>n+c.images.filter(i=>i.sha).length,0)),531);
    assert.equal(await page.evaluate(()=>state.baseline.source_imports),1);
   }
   await page.locator('#gallery article').first().click();await page.waitForFunction(()=>document.querySelector('#inspectImage')?.naturalWidth===1);
   assert.equal(await page.locator('#analyzeBtn').isDisabled(),true);
  });
  await check('reload_preserves_images_ids_and_approved_tags',async()=>{
   await page.reload();await page.waitForFunction(()=>state.baseline?.complete===true);
   assert.equal(await page.evaluate(()=>state.cards.length),309);
   assert.equal(await page.evaluate(()=>state.cards.reduce((n,c)=>n+c.tags.length,0)),8471);
   assert.equal(await page.evaluate(()=>state.cards.find(c=>c.card_id===188).images.length),0);
   assert.equal(await page.evaluate(()=>state.cards.find(c=>c.card_id===55).images[0].sha===state.cards.find(c=>c.card_id===82).images[0].sha),true);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);output.status='passed';
 }catch(e){output.status='failed';output.error=String(e.stack||e);process.exitCode=1}
 finally{
  if(browser)await browser.close();if(child)child.kill();
  fs.writeFileSync(path.join(root,'evaluation/baseline-browser-smoke.json'),JSON.stringify(output,null,2));
  fs.rmSync(temp,{recursive:true,force:true});console.log(JSON.stringify(output,null,2));
 }
})();
