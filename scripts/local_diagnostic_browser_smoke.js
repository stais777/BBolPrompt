'use strict';
// Exercise the actual shareable-report buttons with synthetic local input.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),{spawn,spawnSync}=require('child_process'),assert=require('assert/strict');
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-diagnostic-browser-'));
const result={actual_PT_tested:false,external_API_called:false,native_Windows_tested:false,checks:[]};
let browser,child;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function check(name,fn){console.log('Checking: '+name);await fn();result.checks.push(name)}
(async()=>{
 try{
  child=spawn('python3',['scripts/browser_fixture_server.py',data],{cwd:root,stdio:['ignore','pipe','pipe']});let errors='';child.stderr.on('data',b=>errors+=b);
  for(let i=0;i<100&&!fs.existsSync(path.join(data,'runtime.json'));i++){if(child.exitCode!==null)throw Error(errors);await pause(100)}
  const base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(path.join(data,'runtime.json'))).port;
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1500,height:1040},acceptDownloads:true}),jsErrors=[],external=[];
  page.on('pageerror',e=>jsErrors.push(e.message));await page.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  await page.goto(base+'/');await page.waitForFunction(()=>state.ui!==undefined);
  async function report(button){
   const pending=page.waitForEvent('download');await page.click(button);const download=await pending;const filename=await download.path();assert(fs.statSync(filename).size<2*1024*1024);
   const proc=spawnSync('python3',['-c',`import sys,json,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
 assert z.testzip() is None and set(z.namelist())=={'report.json','SUMMARY.txt'}
 d=json.loads(z.read('report.json'))
 assert all(v is False for v in d['disclosure'].values())
 print(json.dumps({'acceptance':d['acceptance'],'counts':d['counts'],'latest_status':d['import_attempts'][0]['status'] if d['import_attempts'] else None,'integrity':d['integrity'],'version':d['application']['version'],'media_errors':len(d['integrity']['media_errors'])}))`,filename],{encoding:'utf8'});
   assert.equal(proc.status,0,proc.stderr);return JSON.parse(proc.stdout);
  }
  await check('not_imported_export_is_available_and_not_marked_success',async()=>{const d=await report('#localDiagnosticBtn');assert.equal(d.acceptance,'not_imported');assert.equal(d.counts.linked_image_references,0);assert.equal(d.version,'0.3.4-security')});
  await check('wrong_file_failure_has_exportable_history',async()=>{
   await page.setInputFiles('#hwpx',{name:'wrong.hwpx',mimeType:'application/zip',buffer:Buffer.from('wrong file')});await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('SHA256'));
   const d=await report('#localDiagnosticBtn');assert.equal(d.latest_status,'failed');assert.equal(d.acceptance,'not_imported');
  });
  async function upload(){await page.setInputFiles('#hwpx',path.join(data,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]')}
  await check('review_export_button_does_not_register_or_remove_pending_source',async()=>{await upload();const d=await report('#baselineDiagnosticBtn');assert.equal(d.latest_status,'review_ready');assert.equal(d.counts.linked_image_references,0);assert.equal(await page.locator('#gallery article').count(),0);await page.click('#baselineCancel')});
  await check('committed_export_rechecks_531_links_522_paths_and_all_image_hashes',async()=>{
   await upload();await page.click('#baselineCommit');await page.waitForFunction(()=>registeredCards().length===309);
   const d=await report('#localDiagnosticBtn');assert.equal(d.latest_status,'committed');assert.equal(d.acceptance,'passed_integrity');assert.equal(d.counts.linked_image_references,531);assert.equal(d.counts.unique_source_paths,522);assert.equal(d.counts.tag_mappings,8471);assert.equal(d.media_errors,0);assert(d.integrity.source_image_hashes_available);
  });
  await check('corruption_is_detected_despite_completed_import_count',async()=>{
   const sha=await page.evaluate(()=>state.cards[0].images[0].sha);fs.writeFileSync(path.join(data,'vault',sha),'corrupted bytes');
   const d=await report('#localDiagnosticBtn');assert.equal(d.counts.linked_image_references,531);assert.equal(d.acceptance,'failed_integrity');assert(d.media_errors>0);
  });
  assert.deepEqual(jsErrors,[]);assert.deepEqual(external,[]);result.status='passed';
 }catch(e){result.status='failed';result.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();if(child)child.kill();fs.writeFileSync(path.join(root,'evaluation/local-diagnostic-browser.json'),JSON.stringify(result,null,2));fs.rmSync(data,{recursive:true,force:true});console.log(JSON.stringify(result,null,2))}
})();
