'use strict';
// Local operation feedback. Status polling never invokes a model or resends analysis.
let localAnalysisJob=null,analysisPollTimer=null,analysisPollBusy=false;
let manualSaving=false,manualCommittedId=null,manualDraftAtCommit=null;
const operationMessages=new Map();
function operationText(value){return String(value??'').replace(/sk-[A-Za-z0-9_-]+/g,'[키 비공개]').slice(0,1600)}
function elapsedLabel(start){const n=Math.max(0,Math.floor((Date.now()-start)/1000));return n+'초'}
function activeAnalysis(){return localAnalysisJob||((state.analysis_activity||{}).running?state.analysis_activity:null)}
function operationMessage(id,message,error=false){operationMessages.set(id,{message:operationText(message),error});if(selected?.id===id)updateOperationInspector()}
function attemptMessage(row){
 const p=row.provider||{};
 const completion={ok:'분석 완료',partial:'분석 완료 · 미분류 후보 있음'}[row.status];
 const reasons={output_limit:'출력 한도에 도달해 응답이 완성되지 않았습니다.',refused:'공급자가 태그 응답을 반환하지 않았습니다.',filtered:'공급자의 응답 제한으로 결과를 받지 못했습니다.',timeout:'응답 대기시간을 초과했습니다.',incomplete_response:'완성된 응답을 받지 못했습니다.',http_error:'API HTTP '+p.http_status,connection_or_response_error:'연결 또는 응답 처리 오류입니다.'};
 return 'API 상태: '+row.status+(completion?' · '+completion:'')+(p.error_code?' · '+(reasons[p.error_code]||p.error_code):'')+
  (p.input_tokens!==undefined?' · 입력 '+p.input_tokens+' / 출력 '+(p.output_tokens??0)+' 토큰':'')+
  (!['ok','partial'].includes(row.status)?' · 원문과 기존 태그는 유지됩니다.':'');
}
function updateOperationInspector(){
 if(!selected)return;
 const job=activeAnalysis(),id=selected.id,button=$('analyzeBtn');
 button.disabled=!!selected.approved||!!job;
 button.textContent=job?(job.card_id===id?'API 분석 중…':'다른 카드 분석 중'):'이 카드 API 분석';
 $('hideCard').title='목록에서 숨기는 기능입니다. 원본 삭제가 아니며 숨긴 카드 보기에서 복구할 수 있습니다.';
 const el=$('cardState');let message,error=false;
 if(job?.card_id===id){
  const started=job.started_ms??Date.parse(job.started_utc);
  message='API 분석 중 · '+elapsedLabel(Number.isFinite(started)?started:Date.now())+' · 추가 클릭은 필요하지 않습니다.';
 }else if(operationMessages.has(id)){({message,error}=operationMessages.get(id))}
 else if(!selected.approved){const row=(state.api_recent_attempts||[]).find(x=>x.card_id===id);if(row){message=attemptMessage(row);error=!['ok','partial'].includes(row.status)}}
 if(message!==undefined)el.textContent=message;
 el.classList.toggle('warning',error);el.setAttribute('role',error?'alert':'status');el.setAttribute('aria-live',error?'assertive':'polite');
}
function scheduleAnalysisPoll(){
 if(analysisPollTimer||localAnalysisJob||!state.analysis_activity?.running)return;
 analysisPollTimer=setTimeout(async()=>{analysisPollTimer=null;await readAnalysisStatus(false);scheduleAnalysisPoll()},1500);
}
function reconcileOperationStatus(){updateOperationInspector();scheduleAnalysisPoll()}
async function readAnalysisStatus(showMessage=true){
 if(analysisPollBusy)return;analysisPollBusy=true;
 try{
  const info=await api('/api/analysis-status');state.analysis_activity=info.activity;state.api_recent_attempts=info.recent;state.api_usage=info.usage;
  if(!info.activity.running&&selected){const row=info.recent.find(x=>x.card_id===selected.id);if(row)operationMessages.set(selected.id,{message:attemptMessage(row),error:!['ok','partial'].includes(row.status)})}
  if(!info.activity.running&&!localAnalysisJob){await refresh();if(showMessage)msg('분석 상태를 확인했습니다. 추가 모델 호출은 하지 않았습니다.')}
  else if(showMessage)msg('API 응답을 기다리고 있습니다. 추가 모델 호출은 하지 않았습니다.');
  updateOperationInspector();
 }catch(e){if(showMessage&&selected)operationMessage(selected.id,'상태 확인 오류: '+operationText(e.message),true)}
 finally{analysisPollBusy=false}
}
async function runCardAnalysis(){
 const card=selected;if(!card||card.approved||activeAnalysis())return;
 const job={running:true,card_id:card.id,started_ms:Date.now()};localAnalysisJob=job;
 operationMessages.delete(card.id);updateOperationInspector();msg('API 분석 중입니다. 추가 클릭은 필요하지 않습니다.');
 try{
  const result=await api('/api/analyze',{id:card.id});
  const completion=['ok','partial'].includes(result.status)?' · 분석 완료 · 분류 '+result.tags.length+'개 · 미분류 '+result.unclassified.length+'개':'';
  const text='API 상태: '+result.status+completion+' · '+(result.warnings||[]).join(' / ');
  operationMessage(card.id,text,!['ok','partial'].includes(result.status));
  // Registration/analysis response and gallery refresh are separate outcomes.
  try{await refresh()}catch(e){operationMessage(card.id,text+' · 결과 저장 후 목록 갱신을 확인하지 못했습니다. 분석 상태 확인을 눌러주세요.',true)}
  msg(text);
 }catch(e){
  operationMessage(card.id,'API 결과 확인 오류: '+operationText(e.message)+' · 자동 재시도하지 않습니다. 분석 상태 확인을 눌러주세요.',true);
  msg('API 결과 확인 오류: '+operationText(e.message)+' · 추가 분석 대신 분석 상태 확인을 눌러주세요.');
 }finally{
  localAnalysisJob=null;
  // Refresh the lightweight local status, not a second paid request.
  try{const info=await api('/api/analysis-status');state.analysis_activity=info.activity;state.api_recent_attempts=info.recent;state.api_usage=info.usage}catch{}
  updateOperationInspector();scheduleAnalysisPoll();
 }
}
function resetManualOperation(){
 manualCommittedId=null;manualDraftAtCommit=null;$('manualReviewStatus').textContent='';$('manualReviewStatus').classList.remove('warning');
 $('manualConfirm').disabled=false;$('manualConfirm').hidden=false;$('manualReviewBack').hidden=false;$('manualResultRefresh').hidden=true;
}
async function finishManualDisplay(){
 await refresh();
 const card=state.cards.find(c=>c.id===manualCommittedId||c.overlay_id===manualCommittedId);
 $('manualReviewDialog').close();
 if(card&&visibleCards().some(c=>c.id===card.id)){
  selectCard(card);$('gallery').querySelector('[data-card-id="'+card.id+'"]')?.scrollIntoView({block:'nearest'});
 }
 msg('검토한 카드를 등록했습니다.'+(card&&!visibleCards().some(c=>c.id===card.id)?' 현재 필터 밖의 카드입니다. 전체 카드 보기에서 확인하세요.':''));
}
async function runManualConfirmation(){
 if(manualSaving||!manualDraft||manualCommittedId)return;
 manualSaving=true;manualDraftAtCommit=structuredClone(manualDraft);
 const existingIds=new Set(state.cards.map(c=>c.id));
 const dialog=$('manualReviewDialog'),controls=[...dialog.querySelectorAll('button')].map(b=>[b,b.disabled]);
 for(const [b]of controls)b.disabled=true;
 const start=Date.now(),status=$('manualReviewStatus');status.classList.remove('warning');status.setAttribute('role','status');
 const show=()=>{status.textContent=(manualCommittedId?'등록 완료 · 목록 반영 중':'카드 등록 중 · 기존 자료 백업과 저장을 기다리고 있습니다')+' · '+elapsedLabel(start)};
 show();const timer=setInterval(show,1000);
 try{
  const result=await api('/api/manual',manualDraftAtCommit);manualCommittedId=result.id;manualDraft=null;show();
  await finishManualDisplay();
 }catch(e){
  if(!manualCommittedId){
   // A lost response does not prove the server rolled registration back.
   try{await refresh();const card=state.cards.find(c=>!existingIds.has(c.id)&&c.source_text===manualDraftAtCommit.text);if(card)manualCommittedId=card.overlay_id||card.id}catch{}
  }
  status.textContent=manualCommittedId?'카드 등록은 완료됐지만 목록 표시를 확인하지 못했습니다. 등록 결과 다시 표시를 눌러주세요.':'등록 결과를 확인하지 못했습니다. '+operationText(e.message)+' 목록을 먼저 확인한 뒤 재시도하세요.';
  status.classList.add('warning');status.setAttribute('role','alert');$('manualResultRefresh').hidden=false;
  msg(status.textContent);
 }finally{
  clearInterval(timer);manualSaving=false;for(const [b,old]of controls)b.disabled=old;
  if(manualCommittedId){$('manualConfirm').disabled=true;$('manualConfirm').hidden=true;$('manualReviewBack').hidden=true;manualDraft=null}
 }
}
$('manualReviewDialog').addEventListener('cancel',e=>{if(manualSaving)e.preventDefault()});
$('manualResultRefresh').onclick=async()=>{
 try{if(manualCommittedId)await finishManualDisplay();else{await refresh();$('manualReviewStatus').textContent='목록을 갱신했습니다. 등록 여부를 확인해주세요.'}}
 catch(e){$('manualReviewStatus').textContent='목록 확인 오류: '+operationText(e.message)}
};
$('analysisStatusBtn').onclick=()=>readAnalysisStatus(true);
setInterval(()=>{if(activeAnalysis())updateOperationInspector()},1000);
