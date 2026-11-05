'use strict';
const token=window.BBOLPROM_TOKEN;
const $=id=>document.getElementById(id);
const tagName=t=>t.tag??t.name;
const catId=t=>t.category_id===undefined?t.category_column:t.category_id;
let state={cards:[],categories:[]},ui={},selected=null,selectedTags=[],imageIndex=0;
let tagEditContext=null;
let review=null,baselineReview=null,editingTags=[],manualDraft=null,categoryFocus='',uiSave=Promise.resolve();
const cardImages=new Map();
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function msg(s){$('status').textContent=s}
async function api(route,data){
 const r=await fetch(route,{method:data===undefined?'GET':'POST',headers:{'X-Bbolprom-Token':token,...(data===undefined?{}:{'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data)});
 const out=await r.json();if(!r.ok){const e=Error(out.error||'요청 실패');e.details=out;throw e}return out;
}
async function busy(fn){try{msg('처리 중…');await fn();if($('status').textContent==='처리 중…')msg('준비됨')}catch(e){msg('오류: '+e.message)}}
function saveUI(patch){Object.assign(ui,patch);const value=structuredClone(patch);uiSave=uiSave.catch(()=>{}).then(()=>api('/api/ui',value));return uiSave}
function registeredCards(){return state.cards.filter(c=>!c.approved||(c.origins||[]).length>0)}
function visibleCards(){
 const hidden=new Set(ui.hidden_cards||[]);
 let cards=registeredCards().filter(c=>!!ui.show_hidden===hidden.has(c.id));
 cards=cards.filter(c=>$('scope').value==='all'||(c.approved?'approved':'new')===$('scope').value);
 if(ui.filter_active)cards=cards.filter(c=>(ui.applied_tags||[]).every(n=>c.tags.some(t=>tagName(t)===n)));
 if(ui.sort==='title')cards.sort((a,b)=>a.source_text.localeCompare(b.source_text,'ko'));
 if(ui.sort==='user'){const order=new Map((ui.order||[]).map((id,i)=>[id,i]));cards.sort((a,b)=>(order.get(a.id)??1e9)-(order.get(b.id)??1e9))}
 return cards;
}
async function refresh(){
 await uiSave.catch(()=>{});state=await api('/api/state');ui=state.ui;selectedTags=[...ui.selected_tags];
 $('limits').replaceChildren(...state.limitations.map(x=>node('p',x)));
 const storage=state.storage||{};$('storageInfo').textContent=(storage.data_path||'자료 폴더')+' · '+(storage.baseline_source_saved?'PT 원본 보관됨':'PT 원본 보관 필요')+(storage.warning?' · '+storage.warning:'');
 $('importBtn').textContent=state.baseline?.complete?'PT.hwpx 원본 보관':'＋ PT.hwpx 등록';applyDisplay();render();
 if(selected){selected=state.cards.find(c=>c.id===selected.id)||null;inspect()}
}
function applyDisplay(){
 const root=document.documentElement;root.dataset.theme=ui.theme;$('theme').value=ui.theme;$('tone').value=ui.tone;$('view').value=ui.view;$('sort').value=ui.sort;
 root.style.setProperty('--inspector-width',ui.inspector_width+'px');
 const tones={blue:['#285edb','#eaf0ff','#2851b9'],mint:['#119f88','#e4f8f3','#0a826e'],violet:['#845dd7','#f1eaff','#7251b8']};
 for(const k of ['--accent','--accentsoft','--accent-text','--accent-pressed'])root.style.removeProperty(k);
 if(tones[ui.tone]){const [a,b,c]=tones[ui.tone];root.style.setProperty('--accent',a);root.style.setProperty('--accentsoft',b);root.style.setProperty('--accent-text',c);root.style.setProperty('--accent-pressed',c)}
 document.querySelectorAll('[data-view]').forEach(b=>{const on=b.dataset.view===ui.view;b.classList.toggle('is-active',on);b.setAttribute('aria-pressed',String(on))});
}
function selectTag(name){selectedTags=selectedTags.includes(name)?selectedTags.filter(x=>x!==name):[...selectedTags,name];saveUI({selected_tags:[...selectedTags]}).catch(e=>msg(e.message));render();inspect()}
function suggest(){
 const q=$('query').value.trim().toLocaleLowerCase();$('suggestions').replaceChildren();
 if(!q)return;
 const names=[...new Set(registeredCards().flatMap(c=>c.tags.map(tagName)))];
 for(const n of names.filter(n=>n.toLocaleLowerCase().includes(q)).slice(0,40)){const b=node('button',n,'tag'+(selectedTags.includes(n)?' picked':''));b.onclick=()=>selectTag(n);$('suggestions').append(b)}
}
function sidebar(){
 const cards=registeredCards();$('categoryNav').replaceChildren();
 for(const cat of state.categories){const count=new Set(cards.flatMap(c=>c.tags.filter(t=>catId(t)===cat.id).map(tagName))).size;
  const b=node('button',cat.name+' · '+count,'navbutton'+(categoryFocus===cat.id?' active':''));b.onclick=()=>{categoryFocus=categoryFocus===cat.id?'':cat.id;sidebar()};$('categoryNav').append(b)}
 $('categoryTags').replaceChildren();if(categoryFocus){const names=[...new Set(cards.flatMap(c=>c.tags.filter(t=>catId(t)===categoryFocus).map(tagName)))];
  for(const name of names){const b=node('button',name,'tag'+(selectedTags.includes(name)?' picked':''));b.onclick=()=>selectTag(name);$('categoryTags').append(b)}}
}
function selectCard(card){selected=card;imageIndex=cardImages.get(card.id)??Math.max(0,card.images.findIndex(i=>i.sha));render();inspect()}
function render(){
 const cards=visibleCards(),registered=registeredCards(),hidden=new Set(ui.hidden_cards||[]);
 const tagLayouts=[];
 if(selected&&!cards.some(c=>c.id===selected.id)){selected=null;inspect()}
 $('stCards').textContent=registered.length;$('stTags').textContent=registered.reduce((n,c)=>n+c.tags.length,0);$('stImages').textContent=registered.reduce((n,c)=>n+c.images.filter(i=>i.sha).length,0);$('stReady').textContent=state.baseline?.complete?'연결됨':'대기';
 $('count').textContent='표시 '+cards.length+' / 등록 '+registered.length+' · 최초 정답 보존 309개';
 $('hiddenBtn').textContent=(ui.show_hidden?'일반 카드 보기':'숨긴 카드 보기')+' ('+registered.filter(c=>hidden.has(c.id)).length+')';
 $('applyTagsBtn').textContent=ui.filter_active?'전체 카드 보기':'태그 적용';
 $('applyTagsBtn').classList.toggle('active',!!ui.filter_active);$('applyTagsBtn').setAttribute('aria-pressed',String(!!ui.filter_active));
 $('filterHint').textContent=ui.filter_active?'적용 중: '+(ui.applied_tags||[]).join(' AND '):'태그를 선택한 뒤 ‘태그 적용’을 누르세요. 선택은 전체 보기에서도 유지됩니다.';
 $('filters').replaceChildren();for(const name of selectedTags){const b=node('button',name+' ×','chip');b.onclick=()=>selectTag(name);$('filters').append(b)}
 $('gallery').className='cards mode-'+(ui.view||'basic');$('gallery').replaceChildren();$('galleryEmpty').hidden=cards.length>0;
 if(!cards.length){$('galleryEmpty').querySelector('h2').textContent=registered.length?'조건에 맞는 카드가 없습니다':'확정 PT.hwpx를 불러와 주세요';$('emptyImport').hidden=registered.length>0}
 for(const card of cards){
  const article=node('article',undefined,'card'+(selected?.id===card.id?' selected':''));article.dataset.cardId=card.id;
  const thumb=node('div',undefined,'thumb'),index=Math.min(cardImages.get(card.id)??Math.max(0,card.images.findIndex(i=>i.sha)),Math.max(0,card.images.length-1));cardImages.set(card.id,index);
  galleryPicture(card,thumb,index);article.append(thumb);
  const content=node('div',undefined,'cardcontent');content.append(node('div',card.approved?'카드 '+String(card.card_id).padStart(3,'0'):'신규 '+card.id.slice(0,8),'cardname'),node('div',card.tags.length+' 태그 · '+card.images.length+' 이미지'+(card.approved?' · 승인 기준':' · 사용자 등록'),'cardmeta'));
  if(ui.view!=='grid'){
   const area=node('div',undefined,'cardtagarea'),list=node('div',undefined,'cardtaglist');const pins=ui.pinned_tags?.[card.id]||[];
   const ordered=[...card.tags].sort((a,b)=>Number(pins.includes(tagName(b)))-Number(pins.includes(tagName(a))));
   const candidates=ordered.slice(0,20);
   for(const tag of candidates){const name=tagName(tag),b=node('button',name,'cardtag'+(pins.includes(name)?' pinned':'')+(selectedTags.includes(name)?' picked':''));b.title='클릭: 필터 선택 · 우클릭: 대표 태그 고정';b.onclick=e=>{e.stopPropagation();selectTag(name)};b.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();pinTag(card,name)};list.append(b)}
   const more=node('button','','tag-more');more.onclick=e=>{e.stopPropagation();selectCard(card);openDetail()};area.append(list,more);content.append(area);
   tagLayouts.push({list,more,total:card.tags.length});
  }
  content.append(node('div',card.source_text,'excerpt'));article.append(content);article.onclick=()=>selectCard(card);
  article.draggable=ui.sort==='user';article.ondragstart=e=>{e.dataTransfer.setData('application/x-bbolprom-card-id',card.id);e.dataTransfer.effectAllowed='move'};
  article.ondragover=e=>{if(e.dataTransfer.types.includes('application/x-bbolprom-card-id')){e.preventDefault();article.classList.add('drag-target')}};
  article.ondragleave=()=>article.classList.remove('drag-target');article.ondrop=e=>{
   const id=e.dataTransfer.getData('application/x-bbolprom-card-id');if(!id)return;e.preventDefault();e.stopPropagation();article.classList.remove('drag-target');
   if(id===card.id)return;let order=(ui.order||[]).filter(x=>registered.some(c=>c.id===x));for(const c of registered)if(!order.includes(c.id))order.push(c.id);
   order=order.filter(x=>x!==id);order.splice(order.indexOf(card.id),0,id);busy(async()=>{const saving=saveUI({order,sort:'user'});render();await saving});
  };
  $('gallery').append(article);
 }
 // Read all positions before hiding anything to avoid repeated full-gallery
 // layout for each tag. This matters with 309 cards and thousands of tags.
 const mode=ui.view;
 requestAnimationFrame(()=>{
  const layouts=tagLayouts.filter(x=>x.list.isConnected).map(x=>({...x,buttons:[...x.list.children].map(b=>({b,top:b.offsetTop}))}));
  for(const {buttons,more,total} of layouts){let shown=buttons.length;const lines=[],max=mode==='basic'?2:3;
   if(mode==='basic'||mode==='large')for(const {b,top} of buttons){if(!lines.some(t=>Math.abs(t-top)<3))lines.push(top);if(lines.length>max){b.hidden=true;shown--}}
   more.hidden=total<=shown;more.textContent='+'+(total-shown)+'개 더보기';
  }
 });
 suggest();sidebar();
}
function galleryPicture(card,thumb,index){
 thumb.replaceChildren();const im=card.images[index];
 if(im?.sha){const img=node('img');img.src='/media/'+im.sha;img.loading='lazy';img.alt='카드 연결 이미지';img.onerror=()=>msg('이미지를 표시할 수 없습니다. 원본 저장으로 파일을 확인하세요.');thumb.append(img)}
 else thumb.append(node('div',card.images.length?'이미지 미연결':'이미지 없는 카드','placeholder'));
 if(card.images.length>1){const controls=node('div',undefined,'card-image-controls');
  for(const [d,label] of [[-1,'◀'],[1,'▶']]){const b=node('button',label);b.onclick=e=>{e.stopPropagation();changeCardImage(card,thumb,d)};controls.append(b)}
  controls.insertBefore(node('span',(index+1)+' / '+card.images.length),controls.lastChild);thumb.append(controls);
  thumb.onwheel=e=>{e.preventDefault();e.stopPropagation();changeCardImage(card,thumb,e.deltaY>0?1:-1)};
 }
}
function changeCardImage(card,thumb,d){const index=((cardImages.get(card.id)??0)+d+card.images.length)%card.images.length;cardImages.set(card.id,index);galleryPicture(card,thumb,index);if(selected?.id===card.id){imageIndex=index;showImage()}}
async function pinTag(card,name){await busy(async()=>{const pins=structuredClone(ui.pinned_tags||{}),old=pins[card.id]||[];pins[card.id]=old.includes(name)?old.filter(x=>x!==name):[...old,name];const saving=saveUI({pinned_tags:pins});render();await saving})}
function effectiveCat(tag,card){const id=catId(tag);if(card?.approved)return tag.category_display_name||state.baseline_category_names?.[id]||'미분류';return state.categories.find(c=>c.id===id)?.name||'미분류'}
function tagGroups(card,container,target){
 container.replaceChildren();const groups=new Map();
 for(const tag of card.tags){const name=effectiveCat(tag,card);if(!groups.has(name))groups.set(name,[]);groups.get(name).push(tag)}
 if(!groups.size){container.append(node('p','등록된 태그가 없습니다.','muted'));return}
 for(const [name,tags] of groups){const group=node('section',undefined,'inspector-tag-group');group.append(node('div',name,'cathead'));const list=node('div',undefined,'taglist');
  for(const tag of tags){const label=tagName(tag),pair=node('span',undefined,'tag-pair'),button=node('button',label,'tag'+(selectedTags.includes(label)?' picked':''));button.dataset.tag=label;button.title='클릭: 원문 형광펜 · 우클릭: 대표 태그';button.onclick=()=>highlight(tag,target,card);button.oncontextmenu=e=>{e.preventDefault();pinTag(card,label)};const add=node('button','+','tag-add');add.title=label+' 필터 선택';add.onclick=()=>selectTag(label);pair.append(button,add);list.append(pair)}group.append(list);container.append(group);
 }
}
function inspect(){
 $('inspector').hidden=!selected;$('empty').hidden=!!selected;$('inspectorPanel').classList.toggle('has-selection',!!selected);
 if(!selected){$('cardTitle').textContent='카드 정보';return}
 imageIndex=Math.min(imageIndex,Math.max(0,selected.images.length-1));
 $('cardTitle').textContent=selected.approved?'승인 카드 '+selected.card_id:'신규 카드';showImage();tagGroups(selected,$('taglist'),$('source'));
 $('source').textContent=selected.source_text;$('origins').textContent=JSON.stringify({source_text_sha256:selected.sha??selected.source_text_sha256,origins:selected.origins,analysis_references:selected.analysis_references},null,2);
 $('cardState').textContent=selected.approved?(selected.user_tag_edited?'사용자 태그 수정본 · 버전 '+selected.tag_revision:'최초 정답 원본 유지'):selected.analysis_status;$('analyzeBtn').disabled=!!selected.approved;$('editTagsBtn').disabled=false;$('cardFolderBtn').disabled=!!selected.approved;$('engineTagHistoryBtn').disabled=!!selected.approved;$('editCardBtn').disabled=!!selected.approved;$('historyBtn').disabled=false;$('historyBtn').textContent=selected.approved?'태그 수정 이력 · 복원':'수정 이력 · 복원';
 $('hideCard').textContent=(ui.hidden_cards||[]).includes(selected.id)?'숨김 해제':'카드 숨기기';
}
function currentImage(){return selected?.images[imageIndex]}
function showImage(){
 const im=currentImage();$('imageBox').replaceChildren();
 if(im?.sha){const img=node('img');img.id='inspectImage';img.src='/media/'+im.sha;img.alt='원본 비율 유지';img.onclick=openZoom;img.onerror=()=>msg('이미지 표시 실패: 원본 저장으로 파일을 확인하세요.');$('imageBox').append(img)}
 else $('imageBox').append(node('div',im?.ref?'이미지 미연결 · '+im.ref:'이미지 없는 정상 카드','notice'));
 $('imageCount').textContent=selected.images.length?(imageIndex+1)+' / '+selected.images.length:'0 / 0';
 for(const id of ['prevImage','nextImage'])$(id).disabled=selected.images.length<2;
 for(const id of ['saveImage','copyImage'])$(id).disabled=!im?.sha;
}
function cycle(d){if(!selected?.images.length)return;imageIndex=(imageIndex+d+selected.images.length)%selected.images.length;cardImages.set(selected.id,imageIndex);showImage()}
function highlight(tag,target=$('source'),card=selected){
 const chars=Array.from(card.source_text),bounds=new Set();let invalid=0,valid=0;
 for(const s of tag.spans??[]){if(Number.isInteger(s.start_cp)&&Number.isInteger(s.end_cp)&&s.start_cp>=0&&s.start_cp<s.end_cp&&s.end_cp<=chars.length&&chars.slice(s.start_cp,s.end_cp).join('')===s.evidence){for(let i=s.start_cp;i<s.end_cp;i++)bounds.add(i);valid++}else invalid++}
 const out=document.createDocumentFragment();let start=0;
 while(start<chars.length){const on=bounds.has(start);let end=start+1;while(end<chars.length&&bounds.has(end)===on)end++;out.append(node(on?'mark':'span',chars.slice(start,end).join('')));start=end}
 target.replaceChildren(out);target.querySelector('mark')?.scrollIntoView({block:'nearest'});
 msg(invalid?'근거 좌표 불일치 '+invalid+'건: 해당 구간은 강조하지 않았습니다.':valid?'검증된 원문 근거 '+valid+'구간':'직접 근거 0구간: 원문과 태그를 그대로 보존합니다.');
}
async function copyPrompt(){await navigator.clipboard.writeText(selected.source_text);msg('전체 원문을 복사했습니다.')}
function saveImage(){const im=currentImage();if(!im?.sha)return;const path=im.path_in_source||im.ref||'image';const name=path.split('/').pop();download('/media/'+im.sha,name.includes('.')?name:name+'.bin');msg('원본 이미지 바이트를 저장했습니다.')}
async function copyImage(){
 const im=currentImage();if(!im?.sha)return;const response=await fetch('/media/'+im.sha);if(!response.ok)throw Error('이미지를 읽을 수 없습니다');let blob=await response.blob();
 if(blob.type!=='image/png'){const bitmap=await createImageBitmap(blob),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;canvas.getContext('2d').drawImage(bitmap,0,0);bitmap.close();blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'))}
 await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);msg('원본 크기의 이미지 픽셀을 복사했습니다.')
}
function openZoom(){const im=currentImage();if(!im?.sha){msg('연결된 이미지가 없습니다.');return}$('zoomViewport').classList.remove('actual');$('zoomImage').src='/media/'+im.sha;$('zoomImage').onload=()=>{$('zoomDimensions').textContent=$('zoomImage').naturalWidth+' × '+$('zoomImage').naturalHeight+' px'};$('zoomActual').textContent='원본 크기 (1:1)';$('zoomDialog').showModal()}
function openDetail(){if(!selected)return;$('detailTitle').textContent=selected.approved?'카드 '+selected.card_id:'신규 카드';$('detailImageBox').replaceChildren();const im=currentImage();if(im?.sha){const img=node('img');img.src='/media/'+im.sha;img.alt='연결 원본 이미지';img.onclick=openZoom;$('detailImageBox').append(img)}else $('detailImageBox').append(node('p','이미지 없는 카드'));$('detailSource').textContent=selected.source_text;tagGroups(selected,$('detailTags'),$('detailSource'));$('detailDialog').showModal()}
function download(url,name){const a=node('a');a.href=url;a.download=name||url.split('/').pop();document.body.append(a);a.click();a.remove()}

function manualTargets(){const matches=state.cards.filter(c=>c.approved&&c.source_text===$('manualText').value);$('manualTarget').replaceChildren(new Option('자동 · 유일한 일치만',''));for(const c of matches)$('manualTarget').append(new Option('승인 #'+c.card_id,c.id))}
function readBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file)})}
$('manualBtn').onclick=()=>{manualTargets();$('manualDialog').showModal()};$('manualText').oninput=manualTargets;
$('saveManual').onclick=()=>busy(async()=>{
 const text=$('manualText').value;if(!text.trim())throw Error('프롬프트 원문이 필요합니다.');const images=[];
 for(const f of $('manualImages').files)images.push({name:f.name,base64:await readBase64(f),mime:f.type||'application/octet-stream'});
 manualDraft={text,images,approved_target:$('manualTarget').value||null,origin_filename:$('manualOrigin').value.trim()||'직접 등록'};
 const matches=state.cards.filter(c=>c.source_text===text);
 $('manualReviewSummary').textContent=(matches.length?'기존 동일 원문 '+matches.length+'카드 확인 · 이미지/출처 추가':'신규 카드 1개')+' · 이미지 '+images.length+'개 · 출처: '+manualDraft.origin_filename;
 $('manualReviewText').textContent=text;$('manualReviewImages').replaceChildren();
 for(const im of images){const img=node('img');img.src='data:'+im.mime+';base64,'+im.base64;img.alt=im.name;$('manualReviewImages').append(img)}
 $('manualDialog').close();$('manualReviewDialog').showModal();msg('직접 등록 검토 대기');
});
$('manualReviewBack').onclick=()=>{$('manualReviewDialog').close();$('manualDialog').showModal()};
$('manualConfirm').onclick=()=>busy(async()=>{
 if(!manualDraft)return;$('manualConfirm').disabled=true;
 try{await api('/api/manual',manualDraft);manualDraft=null;$('manualReviewDialog').close();await refresh();msg('검토한 카드를 등록했습니다.')}finally{$('manualConfirm').disabled=false}
});
$('query').oninput=suggest;$('scope').onchange=()=>{render();inspect()};
$('view').onchange=()=>busy(async()=>{const saving=saveUI({view:$('view').value});applyDisplay();render();await saving});
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{$('view').value=b.dataset.view;$('view').onchange()});
$('sort').onchange=()=>busy(async()=>{const saving=saveUI({sort:$('sort').value});render();await saving});
for(const id of ['theme','tone'])$(id).onchange=()=>busy(async()=>{const saving=saveUI({theme:$('theme').value,tone:$('tone').value});applyDisplay();await saving});
$('themeReset').onclick=()=>busy(async()=>{const saving=saveUI({theme:'workstation',tone:'preset',inspector_width:385,view:'basic'});applyDisplay();render();await saving});
$('applyTagsBtn').onclick=()=>busy(async()=>{const patch=ui.filter_active?{filter_active:false}:{filter_active:true,applied_tags:[...selectedTags]};const saving=saveUI(patch);render();await saving});
$('clearTagsBtn').onclick=()=>busy(async()=>{selectedTags=[];const saving=saveUI({selected_tags:[],applied_tags:[],filter_active:false});render();inspect();await saving});
$('hiddenBtn').onclick=()=>busy(async()=>{const saving=saveUI({show_hidden:!ui.show_hidden});selected=null;inspect();render();await saving});
$('hideCard').onclick=()=>busy(async()=>{if(!selected)return;const ids=ui.hidden_cards||[],id=selected.id;const saving=saveUI({hidden_cards:ids.includes(id)?ids.filter(x=>x!==id):[...ids,id]});selected=null;inspect();render();await saving});
$('dismissInspector').onclick=()=>{selected=null;inspect();render()};
$('prevImage').onclick=()=>cycle(-1);$('nextImage').onclick=()=>cycle(1);$('imageBox').onwheel=e=>{if(selected?.images.length>1){e.preventDefault();cycle(e.deltaY>0?1:-1)}};
$('clearHighlight').onclick=()=>{$('source').textContent=selected.source_text};$('expandSource').onclick=()=>{$('source').classList.toggle('expanded');$('expandSource').textContent=$('source').classList.contains('expanded')?'원문 접기':'원문 확장'};
$('copyPrompt').onclick=()=>busy(copyPrompt);$('copyImage').onclick=()=>busy(copyImage);$('saveImage').onclick=saveImage;
$('detailBtn').onclick=openDetail;$('detailZoom').onclick=openZoom;$('detailCopy').onclick=()=>busy(copyPrompt);
$('zoomSave').onclick=saveImage;$('zoomActual').onclick=()=>{$('zoomViewport').classList.toggle('actual');$('zoomActual').textContent=$('zoomViewport').classList.contains('actual')?'화면에 맞춤':'원본 크기 (1:1)'};
for(const id of ['importBtn','addFileBtn','emptyImport'])$(id).onclick=()=>$('hwpx').click();
$('hwpx').onchange=()=>{const file=$('hwpx').files[0];$('hwpx').value='';if(file)uploadBaseline(file)};
$('drop').ondragover=e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();$('drop').classList.add('drag-over')}};
$('drop').ondragleave=()=>$('drop').classList.remove('drag-over');$('drop').ondrop=e=>{if(!e.dataTransfer.files.length)return;e.preventDefault();$('drop').classList.remove('drag-over');const file=e.dataTransfer.files[0];if(file.name.toLowerCase().endsWith('.hwpx'))uploadBaseline(file);else msg('이미지는 카드 직접 등록에서 선택하세요.')};
let gripStart=null;
$('inspectorGrip').onpointerdown=e=>{gripStart={x:e.clientX,width:ui.inspector_width};$('inspectorGrip').setPointerCapture(e.pointerId);e.preventDefault()};
$('inspectorGrip').onpointermove=e=>{if(!gripStart)return;const width=Math.round(Math.max(290,Math.min(720,gripStart.width+gripStart.x-e.clientX)));document.documentElement.style.setProperty('--inspector-width',width+'px')};
$('inspectorGrip').onpointerup=e=>{if(!gripStart)return;const width=Math.round(Math.max(290,Math.min(720,gripStart.width+gripStart.x-e.clientX)));gripStart=null;busy(async()=>{await saveUI({inspector_width:width});render()})};
$('inspectorGrip').onpointercancel=()=>{gripStart=null;applyDisplay()};
$('inspectorGrip').onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();busy(async()=>{await saveUI({inspector_width:Math.max(290,Math.min(720,ui.inspector_width+(e.key==='ArrowLeft'?20:-20)))});applyDisplay()})}};
$('backupBtn').onclick=()=>busy(async()=>{const r=await api('/api/backup',{});download(r.download);msg('데이터베이스와 이미지 백업을 저장했습니다.')});
$('exportBtn').onclick=()=>busy(async()=>{const r=await api('/api/export',{});download(r.download);msg('원본을 유지하고 새 XLSX를 내보냈습니다.')});
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>{const id=b.dataset.close;if(id==='reviewDialog'&&review){api('/api/cancel',{ticket:review.ticket}).catch(e=>msg(e.message));review=null}if(id==='manualReviewDialog')manualDraft=null;$(id).close()};
$('quitBtn').onclick=()=>busy(async()=>{await uiSave;await api('/api/shutdown',{});msg('앱을 종료했습니다. 이 탭을 닫으세요.')});
busy(refresh);

// Retained API settings, tag editor and explicit legacy diagnostic review.
async function upload(file){await busy(async()=>{const r=await fetch('/api/upload',{method:'POST',headers:{'X-Bbolprom-Token':token,'X-Filename':encodeURIComponent(file.name)},body:file});review=await r.json();if(!r.ok)throw Error(review.error);review.originalImages=review.cards.flatMap(c=>c.images);reviewRender();$('reviewDialog').showModal();msg('반입 검토 대기')})}

async function cancelBaseline(){if($('baselineCommit').disabled)return;if(baselineReview){const ticket=baselineReview.ticket;baselineReview=null;await api('/api/cancel',{ticket})}$('baselineDialog').close()}
async function uploadBaseline(file){await busy(async()=>{$('importBtn').disabled=true;try{
 if(state.baseline?.complete){msg('PT 원본을 복사·검증하고 있습니다. 기존 매핑은 유지합니다.');const response=await fetch('/api/source-upload',{method:'POST',headers:{'X-Bbolprom-Token':token,'X-Filename':encodeURIComponent(file.name)},body:file});const saved=await response.json();if(!response.ok)throw Error(saved.error);await refresh();msg(saved.message);return}
 if(baselineReview)await cancelBaseline();const r=await fetch('/api/baseline-upload',{method:'POST',headers:{'X-Bbolprom-Token':token,'X-Filename':encodeURIComponent(file.name)},body:file});const result=await r.json();if(!r.ok)throw Error(result.error);baselineReview=result;$('baselineError').textContent='';$('baselineProgress').textContent='';$('baselineSummary').textContent='고정 ID '+result.stats.cards+'개 · 이미지 참조 '+result.stats.image_references+'건 · 원본 이미지 경로 '+result.stats.unique_image_paths+'개 · 등록 전';$('baselineCards').replaceChildren();let image=0;for(const c of result.cards){const box=node('details');box.dataset.cardId=String(c.card_id);box.append(node('summary','베이스 #'+c.card_id+' · '+c.images.length+' 이미지 · '+c.tag_count+' 태그'));const text=node('pre',c.source_text);text.style.whiteSpace='pre-wrap';box.append(text);for(const im of c.images){const img=node('img');img.src='/pending-media/'+result.ticket+'/'+image++;img.loading='lazy';img.alt=im.ref;img.style.cssText='width:96px;height:96px;object-fit:contain';box.append(img)}$('baselineCards').append(box)}$('baselineDialog').showModal();msg('베이스화 이미지 연결 검토 대기')}finally{$('importBtn').disabled=false}})}
$('baselineCancel').onclick=()=>busy(cancelBaseline);$('baselineDialog').addEventListener('cancel',e=>{e.preventDefault();busy(cancelBaseline)});$('baselineCommit').onclick=()=>busy(async()=>{
 if(!baselineReview||$('baselineCommit').disabled)return;
 $('baselineError').textContent='';$('baselineProgress').textContent='등록 중… 원본 확인·백업·이미지 저장을 진행하고 있습니다.';
 for(const id of ['baselineCommit','baselineCancel','baselineDiagnosticBtn'])$(id).disabled=true;
 let result;
 try{result=await api('/api/baseline-commit',{ticket:baselineReview.ticket})}
 catch(error){$('baselineProgress').textContent='';$('baselineError').textContent='등록하지 못했습니다: '+error.message+' · 이 창의 진단 로그 내보내기로 기록을 저장해 주세요. 다시 등록을 시도할 수 있습니다.';msg('베이스 등록 실패: '+error.message);return}
 finally{for(const id of ['baselineCommit','baselineCancel','baselineDiagnosticBtn'])$(id).disabled=false}
 baselineReview=null;$('baselineDialog').close();await refresh();msg(result.message);
});
function approvedMatches(c){return state.cards.filter(a=>a.approved&&a.source_text===c.source_text)}
function unresolvedReviewIndices(){if(!review)return [];return review.cards.flatMap((c,i)=>{const matches=approvedMatches(c);return matches.length>1&&!matches.some(a=>a.id===c.approved_target)?[i]:[]})}
function reviewOverview(){if(!review)return;const refs=review.cards.reduce((n,c)=>n+c.images.length,0);const approved=state.cards.filter(c=>c.approved).length;const unresolved=unresolvedReviewIndices();$('reviewSummary').textContent='이번 파일 추출: '+review.cards.length+' 검토 카드 · '+refs+' 이미지 참조 | 기존 갤러리: '+state.cards.length+' 카드 (승인 '+approved+' 카드) · 등록 전';$('reviewNotice').textContent=review.notice||'';$('reviewPending').textContent=unresolved.length?'이미지·출처 귀속 선택 필요: '+unresolved.length+' 검토 카드':'이미지·출처 귀속 선택 누락 없음';$('jumpUnresolvedBtn').hidden=!unresolved.length}
function focusReviewCard(index,message){const box=$('review-card-'+(index+1));if(!box)return;document.querySelectorAll('#reviewCards .needs-choice').forEach(e=>e.classList.remove('needs-choice'));box.classList.add('needs-choice');box.scrollIntoView({block:'center'});const choice=box.querySelector('.review-target');if(choice){choice.setAttribute('aria-invalid','true');choice.focus()}$('reviewErrors').textContent=message||'검토 카드 #'+(index+1)+': 동일한 원문을 가진 승인 카드가 여러 개입니다. 이 카드의 이미지·출처를 연결할 승인 카드 번호를 선택한 뒤 등록하세요.';msg($('reviewErrors').textContent)}
$('jumpUnresolvedBtn').onclick=()=>{const first=unresolvedReviewIndices()[0];if(first!==undefined)focusReviewCard(first)};
function renderReviewTarget(c,index,holder){holder.replaceChildren();const matches=approvedMatches(c);if(c.approved_target&&!matches.some(a=>a.id===c.approved_target))c.approved_target=null;if(matches.length>1){const label=node('label','검토 카드 #'+(index+1)+' 이미지·출처 귀속 대상');const choice=node('select');choice.className='review-target';choice.dataset.reviewIndex=String(index+1);choice.setAttribute('aria-label','검토 카드 #'+(index+1)+' 이미지·출처 귀속 승인 카드');choice.append(new Option('선택 필요 — 동일 원문 승인 카드 '+matches.length+'개',''));for(const a of matches)choice.append(new Option('승인 카드 #'+a.card_id+' · 이미지·출처 연결',a.id));choice.value=c.approved_target||'';choice.setAttribute('aria-invalid',String(!choice.value));choice.onchange=()=>{const chosen=choice.value||null;for(const item of review.cards)if(item.source_text===c.source_text)item.approved_target=chosen;for(const [j,item]of review.cards.entries())if(item.source_text===c.source_text){const target=$('review-card-'+(j+1))?.querySelector('.review-target-holder');if(target)renderReviewTarget(item,j,target);$('review-card-'+(j+1))?.classList.remove('needs-choice')}$('reviewErrors').textContent='';reviewOverview()};label.append(choice);holder.append(label)}else if(matches.length===1)holder.append(node('p','이미지·출처 연결: 승인 카드 #'+matches[0].card_id+' (원문 유일 일치)'))}
function reviewRender(){reviewOverview();$('reviewErrors').textContent='';$('reviewCards').replaceChildren();review.cards.forEach((c,i)=>{const box=node('div',undefined,'review-card');box.id='review-card-'+(i+1);box.append(node('h3','검토 카드 #'+(i+1)+' · '+c.images.length+' 이미지 참조 · '+(review.plan?.[i]?.action||'검토 수정')));const text=node('textarea');text.value=c.source_text;text.setAttribute('aria-label','검토 카드 #'+(i+1)+' 원문');const targetHolder=node('div',undefined,'review-target-holder');text.oninput=()=>{c.source_text=text.value;renderReviewTarget(c,i,targetHolder);reviewOverview()};box.append(targetHolder);renderReviewTarget(c,i,targetHolder);box.append(text,node('p',c.images.map(x=>x.ref).join(', ')),node('p',(c.warnings||[]).join(' / '),'warning'));for(const [j,im] of c.images.entries()){const line=node('div',undefined,'row');const preview=node('img');preview.src='/pending-media/'+review.ticket+'/'+review.originalImages.indexOf(im);preview.style='width:100px;height:100px;object-fit:contain';preview.alt=im.ref;line.append(preview);for(const [delta,label] of [[-1,'이전 카드로 이미지 이동'],[1,'다음 카드로 이미지 이동']])if(review.cards[i+delta]){const b=node('button',label);b.onclick=()=>{review.cards[i+delta].images.push(c.images.splice(j,1)[0]);reviewRender()};line.append(b)}box.append(line)}if(i>0){const b=node('button','이전 카드와 병합');b.onclick=()=>{const prev=review.cards[i-1];prev.source_text+='\n'+c.source_text;prev.images.push(...c.images);review.cards.splice(i,1);reviewRender()};box.append(b)}const split=node('button','문단별 분리');split.onclick=()=>{const parts=c.source_text.split('\n');if(parts.length<2)return;review.cards.splice(i,1,...parts.map((p,j)=>({...c,source_text:p,images:j===parts.length-1?c.images:[],warnings:['문단 분리: 이미지는 마지막 카드에 임시 연결']})));reviewRender()};box.append(split);$('reviewCards').append(box)});reviewOverview()}
$('commitBtn').onclick=()=>busy(async()=>{const unresolved=unresolvedReviewIndices();if(unresolved.length){focusReviewCard(unresolved[0]);return}$('commitBtn').disabled=true;try{const r=await api('/api/commit',{ticket:review.ticket,cards:review.cards,approved_targets:Object.fromEntries(review.cards.map((c,i)=>[String(i+1),c.approved_target||null]))});$('reviewDialog').close();review=null;await refresh();msg(r.message)}catch(error){const detail=error.details||{};const indices=detail.unresolved_card_indices||[detail.unresolved_index??detail.card_index].filter(x=>x!==undefined);if(indices.length){focusReviewCard(Number(indices[0])-1,'검토 카드 #'+indices[0]+': '+error.message)}else{$('reviewErrors').textContent=error.message;throw error}}finally{$('commitBtn').disabled=false}});
$('diagnosticBtn').onclick=()=>busy(async()=>{if(!review)return;const result=await api('/api/diagnostic',{ticket:review.ticket});download(result.download);msg('구조 진단 ZIP을 로컬에 저장했습니다. 원문·XML 포함, 이미지 미포함 · 외부 전송 없음')});

function tagRows(){
 $('tagEditRows').replaceChildren();editingTags.forEach((t,i)=>{
  const row=node('div',undefined,'review-card'),name=node('input');name.value=t.name;name.placeholder='태그명';name.oninput=()=>t.name=name.value;
  const cat=node('select');cat.append(new Option('미분류',''));for(const c of state.categories.filter(c=>c.enabled))cat.append(new Option(tagEditContext?.approved?(state.baseline_category_names?.[c.id]||c.name):c.name,c.id));
  if(t.category_id&&!state.categories.some(c=>c.id===t.category_id&&c.enabled))cat.append(new Option((state.baseline_category_names?.[t.category_id]||t.category_id)+' · 기존 소속 보존',t.category_id));
  cat.value=t.category_id||'';cat.onchange=()=>t.category_id=cat.value||null;
  const evidence=node('textarea');evidence.value=t.evidence;evidence.placeholder='정확한 원문 구절 (선택)';evidence.oninput=()=>{t.evidence=evidence.value;delete t.original_spans};
  const remove=node('button','태그 삭제');remove.onclick=()=>{editingTags.splice(i,1);tagRows()};row.append(name,cat,evidence,remove);$('tagEditRows').append(row);
 });
}
$('editTagsBtn').onclick=()=>busy(async()=>{
 if(!selected)return;const card=selected,context={id:card.id,approved:!!card.approved,revision:card.tag_revision??0};tagEditContext=context;let currentTags=card.tags;
 if(!card.approved){const latest=await api('/api/engine/card',{id:card.id});if(tagEditContext!==context)return;if(latest.source_sha256!==card.sha)throw Error('원문이 변경됐습니다. 화면을 새로고침하고 다시 수정하세요.');context.token=latest.token;currentTags=latest.tags;}
 editingTags=currentTags.map((t,i)=>({name:tagName(t),category_id:catId(t)||null,evidence:t.spans?.[0]?.evidence||'',original_spans:structuredClone(t.spans||[]),...(card.approved?{source_index:i}:{})}));
 $('tagEditTitle').textContent=card.approved?'기준 카드 '+card.card_id+' · 사용자 태그 수정':'신규 카드 태그 직접 수정';
 $('tagEditNotice').textContent=card.approved?'최초 정답309개는 그대로 보존합니다. 저장한 수동 수정은 이 카드에만 적용하며, 태그명만 바꾸면 기존 근거 구간을 유지합니다.':'원문은 유지하고 태그와 근거를 직접 수정합니다.';
 $('tagEditError').textContent='';$('tagEditProgress').textContent='';tagRows();$('tagsDialog').showModal();
});
$('addTagRow').onclick=()=>{editingTags.push({name:'',category_id:null,evidence:''});tagRows()};
$('saveTags').onclick=()=>busy(async()=>{
 if(!tagEditContext)return;$('saveTags').disabled=true;$('tagEditError').textContent='';$('tagEditProgress').textContent='태그와 사용자 수정 이력을 저장하고 있습니다.';
 try{
  const c=tagEditContext,data={id:c.id,tags:editingTags};if(c.approved)data.expected_revision=c.revision;else data.expected_token=c.token;
  const r=await api(c.approved?'/api/baseline-tags':'/api/tags',data);$('tagsDialog').close();tagEditContext=null;await refresh();msg(r.message);
 }catch(e){$('tagEditError').textContent=e.message;msg('태그 저장 실패: '+e.message)}finally{$('saveTags').disabled=false;$('tagEditProgress').textContent=''}
});
async function showBaselineTagHistory(){
 const card=selected,r=await api('/api/baseline-tag-history',{id:card.id});$('baselineTagVersions').replaceChildren();$('baselineTagHistoryError').textContent='';
 $('baselineTagHistorySummary').textContent='카드 '+card.card_id+' · 현재 사용자 수정 버전 '+r.current_revision+' · 최초 원본은 버전0';
 for(const version of r.versions){
  const box=node('details');box.dataset.revision=String(version.revision);
  box.append(node('summary',version.revision===0?'최초 정답 원본 · 버전0':'수정 버전 '+version.revision+' · '+new Date(version.created).toLocaleString()));
  for(const t of version.tags){const line=node('div',tagName(t)+' · '+effectiveCat(t,card));line.append(node('pre',(t.spans||[]).map(s=>s.evidence).join(' / ')||'직접 근거 없음'));box.append(line)}
  const restore=node('button',version.revision===0?'최초 정답 원본으로 복원':'이 태그 버전으로 복원');restore.disabled=version.revision===r.current_revision;
  restore.onclick=()=>busy(async()=>{restore.disabled=true;try{const done=await api('/api/baseline-tag-restore',{id:card.id,target_revision:version.revision,expected_revision:r.current_revision});$('baselineTagHistoryDialog').close();await refresh();msg(done.message)}catch(e){$('baselineTagHistoryError').textContent=e.message;restore.disabled=false}});
  box.append(restore);$('baselineTagVersions').append(box);
 }
 $('baselineTagHistoryDialog').showModal();
}
$('analyzeBtn').onclick=()=>busy(async()=>{const r=await api('/api/analyze',{id:selected.id});await refresh();msg('API 상태: '+r.status+' · '+(r.warnings||[]).join(' / '))});
function settings(){const c=state.api||{};$('apiEnabled').checked=!!c.enabled;$('apiConsent').checked=!!c.consent;$('apiExamples').checked=c.use_approved_examples??false;$('apiCorrections').checked=c.use_user_corrections??false;$('endpoint').value='https://api.openai.com/v1/chat/completions';$('model').value=c.model||'gpt-6.1-sol';$('apiKey').value='';$('saveKey').disabled=!state.api_key_storage?.supported;$('deleteKey').disabled=!state.api_key_storage?.supported;$('maxCalls').value=c.max_calls??10;$('maxTokens').value=c.max_output_tokens||4096;$('timeout').value=c.timeout||30;$('maxCost').value=c.max_cost_usd??'';$('inPrice').value=c.input_usd_per_million??'';$('outPrice').value=c.output_usd_per_million??'';const u=state.api_usage||{};$('apiUsage').textContent='오늘 (UTC '+(u.day_utc||'')+') 호출 '+(u.calls||0)+'회 · 입력 '+(u.total_input_tokens||0)+' / 출력 '+(u.total_output_tokens||0)+' 토큰 · 비용 예약 상한 $'+(u.reserved_cost_usd||0)+' (가격은 사용자가 공급자 기준으로 입력)';$('keyPresent').textContent=state.api_key_storage?.error||(!state.api_key_storage?.supported?'Windows 보안 보관함을 사용할 수 없습니다. 키 저장·API 호출 차단':('Windows 보안 보관함: '+(state.api_key_present?'키 등록됨 (값은 반환하지 않음)':'키 없음')));$('categoryRows').replaceChildren();for(const cat of state.categories){const box=node('details');box.append(node('summary',cat.id+' · '+cat.name+(cat.enabled?'':' · 비활성')));const name=node('input');name.value=cat.name;const def=node('textarea');def.value=cat.definition||'';def.placeholder='사용자가 확정한 분류 정의 · 포함/제외';const rename=node('button','표시명 변경');rename.onclick=()=>category({operation:'rename',id:cat.id,name:name.value});const define=node('button','이후 분석용 정의 확정');define.onclick=()=>category({operation:'define',id:cat.id,definition:def.value});const toggle=node('button',cat.enabled?'비활성화 → 미분류':'재활성화 (태그 자동 복귀 없음)');toggle.onclick=()=>category({operation:cat.enabled?'deactivate':'reactivate',id:cat.id,restore_tags:false});box.append(name,rename,def,define,toggle);$('categoryRows').append(box)}}async function category(data){await busy(async()=>{await api('/api/categories',data);await refresh();settings();msg('분류 설정 저장됨')})}
$('settingsBtn').onclick=()=>{settings();$('settingsDialog').showModal()};$('saveApi').onclick=()=>busy(async()=>{await api('/api/settings',{api:{enabled:$('apiEnabled').checked,consent:$('apiConsent').checked,use_approved_examples:$('apiExamples').checked,use_user_corrections:$('apiCorrections').checked,endpoint:$('endpoint').value,model:$('model').value,timeout:Number($('timeout').value),max_calls:Number($('maxCalls').value),max_output_tokens:Number($('maxTokens').value),max_cost_usd:$('maxCost').value===''?null:Number($('maxCost').value),input_usd_per_million:$('inPrice').value===''?null:Number($('inPrice').value),output_usd_per_million:$('outPrice').value===''?null:Number($('outPrice').value)}});await refresh();settings();msg('API 설정 저장됨')});$('addCat').onclick=()=>category({operation:'add',id:$('newCatId').value,category:{id:$('newCatId').value,name:$('newCatName').value,definition:$('newCatDef').value}});

let cardEdit=null;
$('editCardBtn').onclick=()=>{if(!selected||selected.approved)return;cardEdit={id:selected.id,expected_sha:selected.sha,old_text:selected.source_text,old_images:structuredClone(selected.images)};$('editCardText').value=selected.source_text;$('editCardFiles').value='';$('editCardForm').hidden=false;$('editCardReview').hidden=true;$('editCardImages').replaceChildren();for(const im of selected.images){const label=node('label',undefined,'edit-image-row'),checkbox=node('input');checkbox.type='checkbox';checkbox.dataset.sha=im.sha;const image=node('img');image.src='/media/'+im.sha;image.alt='현재 연결 이미지';label.append(checkbox,image,node('span','이 연결 제거'));$('editCardImages').append(label)}$('editCardDialog').showModal()};
$('editToReview').onclick=()=>busy(async()=>{if(!cardEdit)return;const text=$('editCardText').value;if(!text.trim())throw Error('원문이 필요합니다.');const images=[];for(const file of $('editCardFiles').files)images.push({name:file.name,base64:await readBase64(file)});Object.assign(cardEdit,{text,images,remove_images:[...$('editCardImages').querySelectorAll('input:checked')].map(x=>x.dataset.sha)});$('editBefore').textContent=cardEdit.old_text;$('editAfter').textContent=text;$('editImageChange').textContent='연결 제거 '+cardEdit.remove_images.length+'개 · 이미지 추가 '+images.length+'개';$('editCardForm').hidden=true;$('editCardReview').hidden=false});
$('editBack').onclick=()=>{$('editCardForm').hidden=false;$('editCardReview').hidden=true};
$('saveCardEdit').onclick=()=>busy(async()=>{if(!cardEdit)return;$('saveCardEdit').disabled=true;try{const {id,text,images,remove_images,expected_sha}=cardEdit;const r=await api('/api/card-edit',{id,text,images,remove_images,expected_sha});$('editCardDialog').close();cardEdit=null;await refresh();msg(r.message)}finally{$('saveCardEdit').disabled=false}});
$('historyBtn').onclick=()=>busy(async()=>{if(!selected)return;if(selected.approved){await showBaselineTagHistory();return}const id=selected.id;const r=await api('/api/card-history',{id});$('historyRows').replaceChildren();if(!r.versions.length)$('historyRows').append(node('p','저장된 수정 이력이 없습니다.'));for(const version of r.versions){const box=node('details');box.append(node('summary',new Date(version.created).toLocaleString()+' · '+version.reason),node('h3','이전 원문'),node('pre',version.source_text),node('p',version.tags.length+'태그 · '+version.images.length+'이미지 연결'));const restore=node('button','이 상태로 복원');restore.onclick=()=>busy(async()=>{restore.disabled=true;try{const done=await api('/api/card-restore',{id,version_id:version.id});$('historyDialog').close();await refresh();msg(done.message)}finally{restore.disabled=false}});box.append(restore);$('historyRows').append(box)}$('historyDialog').showModal()});
for(const b of document.querySelectorAll('#editCardDialog [data-close],#historyDialog [data-close]'))b.onclick=()=>$(b.dataset.close).close();

async function exportLocalDiagnostic(){
 const images=[...document.querySelectorAll('#gallery img,#imageBox img')];
 const observation={displayed_cards:document.querySelectorAll('#gallery article').length,
  rendered_images:images.length,loaded_images:images.filter(im=>im.complete&&im.naturalWidth>0).length,
  failed_images:images.filter(im=>im.complete&&im.naturalWidth===0).length,
  selected_tag_count:selectedTags.length,applied_tag_count:(ui.applied_tags||[]).length,
  filter_active:!!ui.filter_active,show_hidden:!!ui.show_hidden,scope:$('scope').value};
 msg('진단 수집 중… 저장 이미지 파일의 해시를 확인하고 있습니다.');
 const result=await api('/api/local-diagnostic',{ui_observation:observation});download(result.download);
 msg('진단 ZIP 저장: '+result.file+' · 원문/이미지/API키 미포함. 이 파일을 채팅에 첨부해 주세요.');
}
for(const id of ['localDiagnosticBtn','baselineDiagnosticBtn'])$(id).onclick=()=>busy(async()=>{
 $(id).disabled=true;try{await exportLocalDiagnostic()}finally{$(id).disabled=false}
});

$('saveKey').onclick=()=>busy(async()=>{let key=$('apiKey').value;$('apiKey').value='';$('saveKey').disabled=true;try{const r=await api('/api/key',{operation:'save',key});key='';await refresh();settings();msg(r.message)}finally{key='';$('apiKey').value='';$('saveKey').disabled=!state.api_key_storage?.supported}});
$('deleteKey').onclick=()=>busy(async()=>{$('apiKey').value='';const r=await api('/api/key',{operation:'delete'});await refresh();settings();msg(r.message)});
$('settingsDialog').addEventListener('close',()=>{$('apiKey').value=''});

$('dataFolderBtn').onclick=()=>busy(async()=>{const r=await api('/api/open-data-folder',{});msg(r.message)});
$('cardFolderBtn').onclick=()=>busy(async()=>{if(selected&&!selected.approved){const r=await api('/api/open-card-folder',{id:selected.id});msg(r.message)}});

// New-card API subsystem UI; baseline registration and manual baseline editions remain separate.
let engineDefinitionView=null;
async function loadEnginePanel(){
 const [defs,corr,status]=await Promise.all([api('/api/engine/definitions',{}),api('/api/engine/corrections',{}),api('/api/engine/status',{})]);
 engineDefinitionView=defs;$('engineDefinitions').replaceChildren();
 $('engineStatus').textContent=status.version+' · 정의 확정 '+defs.definitions.filter(x=>x.definition_approved).length+' / '+defs.definitions.length+' · 참고용 교정 '+corr.corrections.filter(x=>x.active).length+'건';
 for(const d of defs.definitions){const box=node('details');box.dataset.categoryId=d.id;box.append(node('summary',d.id+' · '+d.name+' · '+(d.definition_approved?'확정':'초안 · 미승인')));
  for(const [field,label] of [['definition','정의'],['include','포함 기준'],['exclude','제외·경계']]){const l=node('label',label),input=node('textarea');input.dataset.field=field;input.value=d[field]||'';l.append(input);box.append(l)}$('engineDefinitions').append(box)}
 $('engineCorrections').replaceChildren();
 for(const row of corr.corrections){const box=node('div',undefined,'review-card');box.append(node('p',row.card_id.slice(0,8)+' · 버전 '+row.revision+' · '+row.tags.join(', ')+' · 제외: '+row.removed.join(', ')));
  const b=node('button',row.active?'다음 추천 참고 해제':'다음 추천에 다시 참고');b.onclick=()=>busy(async()=>{await api('/api/engine/corrections',{operation:'set_active',id:row.id,active:!row.active});await loadEnginePanel();msg('교정 참고 상태를 저장했습니다. 현재 카드의 수동 태그는 유지됩니다.')});box.append(b);$('engineCorrections').append(box)}
 if(!corr.corrections.length)$('engineCorrections').append(node('p','아직 신규 카드의 수동 태그 교정이 없습니다.'));
}
$('loadEngineBtn').onclick=()=>busy(loadEnginePanel);
$('approveEngineDefinitions').onclick=()=>busy(async()=>{
 if(!engineDefinitionView)throw Error('정의 초안을 먼저 열어 검토하세요.');
 const definitions=[...$('engineDefinitions').children].map(box=>{const row={id:box.dataset.categoryId};for(const field of ['definition','include','exclude'])row[field]=box.querySelector('[data-field="'+field+'"]').value;return row}).filter(x=>x.definition.trim());
 await api('/api/engine/definitions',{operation:'approve',definitions,expected_token:engineDefinitionView.token});await loadEnginePanel();msg('신규 분석용 분류 정의를 확정했습니다. 베이스309개는 유지됩니다.');
});
$('engineTagHistoryBtn').onclick=()=>busy(async()=>{
 if(!selected||selected.approved)return;const card=selected,r=await api('/api/engine/tag-history',{id:card.id});$('engineTagVersions').replaceChildren();
 for(const v of r.versions){const box=node('details');box.append(node('summary','버전 '+v.revision+' · '+v.reason+' · '+new Date(v.created).toLocaleString()),node('p',v.tags.map(tagName).join(', ')||'태그 없음'));
  const b=node('button','이 태그 버전으로 복원');b.disabled=v.source_sha!==card.sha;b.onclick=()=>busy(async()=>{await api('/api/engine/tag-restore',{id:card.id,version_id:v.id,expected_token:r.token});$('engineTagHistoryDialog').close();await refresh();msg('태그 버전을 복원했습니다.')});box.append(b);$('engineTagVersions').append(box)}
 if(!r.versions.length)$('engineTagVersions').append(node('p','아직 태그 변경 이력이 없습니다.'));$('engineTagHistoryDialog').showModal();
});
