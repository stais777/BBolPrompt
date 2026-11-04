'use strict';
// Approved UI acceptance on Linux/Chromium with synthetic media. No live API,
// Windows/Hancom DnD or actual PT success is inferred from this run.
const {chromium}=require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const {spawn}=require('child_process'),assert=require('assert/strict');
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'bbol-ui-acceptance-'));
const result={platform:process.platform,actual_PT_tested:false,external_API_called:false,native_Windows_tested:false,Hancom_DnD_tested:false,checks:[]};
let child,browser,page,base;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const catalogueBefore=hash(fs.readFileSync(path.join(root,'assets/approved_catalog.json')));
async function check(name,fn){console.log('Checking: '+name);await fn();result.checks.push(name)}
async function launch(){
 const ready=path.join(data,'runtime.json');fs.rmSync(ready,{force:true});
 child=spawn('python3',['scripts/browser_fixture_server.py',data],{cwd:root,stdio:['ignore','pipe','pipe']});let logs='';child.stderr.on('data',b=>logs+=b);
 for(let i=0;i<150&&!fs.existsSync(ready);i++){if(child.exitCode!==null)throw Error(logs);await pause(100)}
 base='http://127.0.0.1:'+JSON.parse(fs.readFileSync(ready)).port;
 await page.goto(base+'/');await page.waitForFunction(()=>state.ui!==undefined);
}
async function stop(){if(!child)return;if(child.exitCode!==null){child=null;return}const exited=new Promise(r=>child.once('exit',r));child.kill();await exited;child=null}
async function select(id){await page.locator('#gallery article[data-card-id="'+id+'"]').locator('.thumb').click();await page.waitForFunction(value=>selected?.id===value,id)}
async function saved(){await page.evaluate(()=>uiSave)}
(async()=>{
 try{
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext({viewport:{width:1540,height:1040},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']});
  page=await context.newPage();const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  await launch();
  await check('UI01_empty_gallery_and_separate_309_reference',async()=>{
   assert.equal(await page.locator('#gallery article').count(),0);assert.equal(await page.evaluate(()=>state.baseline.registered_cards),309);
   assert.equal(await page.locator('#stCards').textContent(),'0');assert(await page.locator('#galleryEmpty').isVisible());
  });
  await check('UI13_review_before_real_commit',async()=>{
   await page.setInputFiles('#hwpx',path.join(data,'synthetic.hwpx'));await page.waitForSelector('#baselineDialog[open]');
   assert.equal(await page.locator('#baselineCards details').count(),309);assert.equal(await page.locator('#gallery article').count(),0);
   await page.click('#baselineCommit');await page.waitForFunction(()=>registeredCards().length===309);assert.equal(await page.locator('#gallery article').count(),309);
  });
  await check('UI02_four_views_zero_two_three_twenty_tag_limits',async()=>{
   for(const mode of ['grid','basic','large','detail']){
    await page.click('[data-view="'+mode+'"]');await saved();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
    const shape=await page.locator('#gallery article').first().evaluate(el=>{const tags=[...el.querySelectorAll('.cardtag')].filter(e=>!e.hidden);return {count:tags.length,lines:new Set(tags.map(e=>e.offsetTop)).size,more:!!el.querySelector('.tag-more:not([hidden])')}});
    if(mode==='grid')assert.equal(shape.count,0);else if(mode==='detail')assert(shape.count<=20);else assert(shape.lines<=(mode==='basic'?2:3));
   }
   assert.equal(await page.evaluate(()=>state.cards.reduce((n,c)=>n+c.tags.length,0)),8471);
   const more=page.locator('#gallery .tag-more:not([hidden])').first();await more.click();assert(await page.locator('#detailDialog').isVisible());await page.locator('#detailDialog [data-close]').click();
  });
  await check('UI03_image_then_categories_then_entire_prompt',async()=>{
   await select('approved-1');const boxes=await page.evaluate(()=>['imageBox','tagPanel','source'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return {y:r.y,b:r.bottom}}));
   assert(boxes[0].y<boxes[1].y&&boxes[1].y<boxes[2].y);
   assert.equal(await page.locator('#source').textContent(),await page.evaluate(()=>selected.source_text));
  });
  await check('UI07_UI08_zero_multi_images_wheel_ratio_and_original_save',async()=>{
   await select('approved-188');assert.equal(await page.locator('#imageCount').textContent(),'0 / 0');assert(await page.locator('#prevImage').isDisabled());
   await select('approved-110');assert.equal(await page.locator('#imageCount').textContent(),'1 / 14');await page.locator('#imageBox').dispatchEvent('wheel',{deltaY:120});assert.equal(await page.locator('#imageCount').textContent(),'2 / 14');
   const expected=await page.evaluate(()=>currentImage().sha),pending=page.waitForEvent('download');await page.click('#saveImage');const downloaded=await pending;assert.equal(hash(fs.readFileSync(await downloaded.path())),expected);
   const ratios=new Set();for(let id=1;id<=12&&ratios.size<3;id++){
    await select('approved-'+id);await page.waitForFunction(()=>document.querySelector('#inspectImage')?.complete&&document.querySelector('#inspectImage')?.naturalWidth>0);
    const shape=await page.locator('#inspectImage').evaluate(img=>{const b=img.getBoundingClientRect();return {ratio:img.naturalWidth/img.naturalHeight,display:b.width/b.height,fit:getComputedStyle(img).objectFit}});
    assert.equal(shape.fit,'contain');assert(Math.abs(shape.ratio-shape.display)<0.015);ratios.add(shape.ratio.toFixed(3));
   }assert.equal(ratios.size,3);
   await page.locator('#inspectImage').click();await page.waitForSelector('#zoomDialog[open]');await page.click('#zoomActual');assert(await page.locator('#zoomViewport').evaluate(e=>e.classList.contains('actual')));await page.locator('#zoomDialog [data-close]').click();
  });
  let resizeWidth,hiddenId,orderFirst;
  await check('UI09_resize_preserves_selection_and_persists_width',async()=>{
   const id=await page.evaluate(()=>selected.id),box=await page.locator('#inspectorGrip').boundingBox();await page.mouse.move(box.x+3,box.y+120);await page.mouse.down();await page.mouse.move(box.x-65,box.y+120,{steps:8});await page.mouse.up();await saved();
   resizeWidth=await page.evaluate(()=>ui.inspector_width);assert(resizeWidth>385);assert.equal(await page.evaluate(()=>selected.id),id);
   assert.equal(await page.locator('#tagPanel').evaluate(e=>getComputedStyle(e).overflowY),'auto');assert.equal(await page.locator('#source').evaluate(e=>getComputedStyle(e).overflowY),'auto');
  });
  await check('UI10_five_themes_accents_modals_and_reset',async()=>{
   const colors=new Set();for(const theme of ['workstation','vision','cloud','carbon','illustrated']){await page.selectOption('#theme',theme);await saved();await page.click('#manualBtn');colors.add(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--bg')));const expected=await page.evaluate(()=>{const e=document.createElement('div');e.style.background='var(--surface)';document.body.append(e);const value=getComputedStyle(e).backgroundColor;e.remove();return value});assert.equal(await page.locator('#manualDialog').evaluate(e=>getComputedStyle(e).backgroundColor),expected);await page.locator('#manualDialog [data-close]').click()}assert.equal(colors.size,5);
   for(const tone of ['blue','mint','violet']){await page.selectOption('#tone',tone);await saved();assert.equal(await page.evaluate(()=>ui.tone),tone)}
   await page.click('#themeReset');await saved();assert.equal(await page.evaluate(()=>ui.theme),'workstation');assert.equal(await page.evaluate(()=>ui.inspector_width),385);
   await page.selectOption('#theme','carbon');await page.selectOption('#tone','mint');await saved();await page.locator('#inspectorGrip').focus();await page.keyboard.press('ArrowLeft');await saved();resizeWidth=await page.evaluate(()=>ui.inspector_width);assert(resizeWidth>385);
  });
  await check('UI11_hide_show_restore_is_separate_from_filter_selection',async()=>{
   await select('approved-1');hiddenId='approved-1';await page.click('#hideCard');await saved();await page.waitForFunction(()=>visibleCards().length===308);assert.equal(await page.locator('#gallery article').count(),308);
   await page.click('#hiddenBtn');await page.waitForFunction(()=>ui.show_hidden===true);assert.equal(await page.locator('#gallery article').count(),1);await select(hiddenId);await page.click('#hideCard');await saved();assert.equal(await page.locator('#gallery article').count(),0);
   await page.click('#hiddenBtn');await page.waitForFunction(()=>ui.show_hidden===false);assert.equal(await page.locator('#gallery article').count(),309);
  });
  await check('UI12_drag_user_order_and_original_order_remain_separate',async()=>{
   await page.selectOption('#sort','user');await saved();const ids=await page.locator('#gallery article').evaluateAll(es=>es.slice(0,2).map(e=>e.dataset.cardId));await page.locator('#gallery article').nth(1).dragTo(page.locator('#gallery article').first());await saved();
   orderFirst=ids[1];await page.waitForFunction(id=>visibleCards()[0].id===id,orderFirst);assert.equal(await page.locator('#gallery article').first().getAttribute('data-card-id'),orderFirst);
   await page.selectOption('#sort','source');await saved();assert.equal(await page.locator('#gallery article').first().getAttribute('data-card-id'),'approved-1');await page.selectOption('#sort','user');await saved();
  });
  const prompt='😀 푸른 실험실에서 푸른 실험실을 관찰한다.';
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNwaDjwHwAFBAKAPJ4DgAAAAABJRU5ErkJggg==','base64');let newId;
  await check('UI14_manual_edit_review_preserves_raw_text_and_origins',async()=>{
   await page.click('#manualBtn');await page.fill('#manualText',prompt);await page.fill('#manualOrigin','새 출처.hwpx');await page.setInputFiles('#manualImages',[{name:'a.png',mimeType:'image/png',buffer:png},{name:'b.png',mimeType:'image/png',buffer:Buffer.concat([png,Buffer.from('second')])}]);await page.click('#saveManual');await page.waitForSelector('#manualReviewDialog[open]');assert.equal(await page.locator('#manualReviewText').textContent(),prompt);assert.equal(await page.evaluate(()=>registeredCards().length),309);await page.click('#manualConfirm');await page.waitForFunction(()=>registeredCards().length===310);await page.selectOption('#scope','new');await page.locator('#gallery article .thumb').click();newId=await page.evaluate(()=>selected.id);assert.equal(await page.locator('#source').textContent(),prompt);assert.equal(await page.locator('#imageCount').textContent(),'1 / 2');assert((await page.locator('#origins').textContent()).includes('새 출처.hwpx'));
  });
  await check('UI04_multiple_codepoint_spans_copy_prompt_and_image_pixels',async()=>{
   await page.click('#editTagsBtn');await page.click('#addTagRow');const row=page.locator('#tagEditRows .review-card').last();await row.locator('input').fill('푸른 실험실');await row.locator('select').selectOption('F');await row.locator('textarea').fill('푸른 실험실');await page.click('#saveTags');await page.waitForFunction(()=>selected.tags.length===1);await page.locator('#taglist button.tag').click();assert.equal(await page.locator('#source mark').count(),2);assert.equal(await page.locator('#source').textContent(),prompt);
   await page.click('#copyPrompt');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('전체 원문을 복사'));assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),prompt);
   await page.click('#copyImage');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('이미지 픽셀을 복사'));assert(await page.evaluate(async()=>{const items=await navigator.clipboard.read();const blob=await items[0].getType('image/png');const bitmap=await createImageBitmap(blob);return bitmap.width===1&&bitmap.height===1}));
  });
  await check('UI14_card_revision_diff_restore_text_images_and_tag_spans',async()=>{
   await page.click('#editCardBtn');await page.fill('#editCardText','수정한 원문');await page.locator('#editCardImages input').first().check();await page.setInputFiles('#editCardFiles',{name:'new.png',mimeType:'image/png',buffer:Buffer.concat([png,Buffer.from('third')])});await page.click('#editToReview');await page.waitForSelector('#editCardReview:not([hidden])');assert.equal(await page.locator('#editBefore').textContent(),prompt);assert.equal(await page.locator('#editAfter').textContent(),'수정한 원문');await page.click('#saveCardEdit');await page.waitForFunction(()=>selected.source_text==='수정한 원문');assert.equal(await page.evaluate(()=>selected.id),newId);assert.equal(await page.evaluate(()=>selected.tags[0].spans.length),0);
   await page.click('#historyBtn');await page.waitForSelector('#historyDialog[open]');await page.locator('#historyRows summary').first().click();await page.locator('#historyRows button').first().click();await page.waitForFunction(value=>selected.source_text===value,prompt);assert.equal(await page.evaluate(()=>selected.images.length),2);assert.equal(await page.evaluate(()=>selected.tags[0].spans.length),2);
  });
  let pinnedName;
  await check('UI_representative_tags_are_preferences_not_master_edits',async()=>{
   await page.locator('#taglist button.tag').click({button:'right'});await saved();pinnedName='푸른 실험실';assert.deepEqual(await page.evaluate(id=>ui.pinned_tags[id],newId),[pinnedName]);
  });
  await check('UI19_restart_with_new_port_preserves_theme_view_hidden_order_pins',async()=>{
   await page.selectOption('#scope','all');await page.click('[data-view="large"]');await saved();await select('approved-3');await page.click('#hideCard');await saved();await stop();await launch();
   assert.equal(await page.evaluate(()=>ui.theme),'carbon');assert.equal(await page.evaluate(()=>ui.tone),'mint');assert.equal(await page.evaluate(()=>ui.view),'large');assert.equal(await page.evaluate(()=>ui.inspector_width),resizeWidth);assert((await page.evaluate(()=>ui.hidden_cards)).includes('approved-3'));assert.equal(await page.evaluate(()=>ui.order[0]),orderFirst);assert.deepEqual(await page.evaluate(id=>ui.pinned_tags[id],newId),[pinnedName]);assert.equal(await page.evaluate(()=>registeredCards().length),310);
  });
  await check('UI16_no_master_mutation_no_external_calls_or_JS_errors',async()=>{
   assert.equal(hash(fs.readFileSync(path.join(root,'assets/approved_catalog.json'))),catalogueBefore);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
  });
  await page.selectOption('#scope','new');await page.locator('#gallery article .thumb').click();await page.locator('#taglist button.tag').click();await page.screenshot({path:path.join(root,'evaluation/ui-handoff-applied.png'),fullPage:true});
  result.status='passed';
 }catch(e){result.status='failed';result.error=String(e.stack||e);process.exitCode=1}
 finally{if(browser)await browser.close();await stop();fs.writeFileSync(path.join(root,'evaluation/ui-handoff-browser.json'),JSON.stringify(result,null,2));fs.rmSync(data,{recursive:true,force:true});console.log(JSON.stringify(result,null,2))}
})();
