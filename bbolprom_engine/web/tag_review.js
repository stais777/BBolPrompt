'use strict';
// Read-only inspection of the already saved result. Never calls a provider or assigns a category.
function reviewText(value){return String(value??'').replace(/sk-[A-Za-z0-9_-]+/g,'[키 비공개]')}
function resetTagReview(){for(const id of ['tagReview','detailTagReview']){const el=$(id);if(el){el.hidden=true;el.replaceChildren()}}}
function approvedTagMatches(label){
 const groups=new Map();
 for(const card of state.cards.filter(c=>c.approved))for(const tag of card.tags){
  if(tagName(tag)!==label)continue;
  const id=catId(tag),key=id||'';
  if(!groups.has(key))groups.set(key,{category_id:id,name:effectiveCat(tag,card),cards:new Set()});
  groups.get(key).cards.add(card.card_id);
 }
 return [...groups.values()];
}
function showTagReview(tag,card,target){
 const panel=$(target?.id==='detailSource'?'detailTagReview':'tagReview');
 if(!panel)return;
 panel.replaceChildren();panel.hidden=!!card.approved;
 if(card.approved)return;
 const label=tagName(tag),heading=node('summary',reviewText(label)+' · '+effectiveCat(tag,card));
 const body=node('div',undefined,'tag-review-body');
 body.append(node('strong',catId(tag)?'분류 판단 사유':'미분류 사유'));
 body.append(node('p',reviewText(tag.reason||(catId(tag)?'별도 판단 사유가 저장돼 있지 않습니다.':'미분류 사유가 저장돼 있지 않습니다. 원문 근거를 확인하세요.'))));
 const chars=Array.from(card.source_text),spans=(tag.spans||[]).filter(s=>Number.isInteger(s.start_cp)&&Number.isInteger(s.end_cp)&&s.start_cp>=0&&s.start_cp<s.end_cp&&s.end_cp<=chars.length&&chars.slice(s.start_cp,s.end_cp).join('')===s.evidence);
 body.append(node('strong','검증된 원문 근거 · '+spans.length+'구간'));
 const quotes=[...new Set(spans.map(s=>s.evidence))];
 for(const quote of quotes.slice(0,8))body.append(node('pre',reviewText(quote)));
 if(quotes.length>8)body.append(node('p','서로 다른 근거 중 8개를 표시합니다. 전체 구간은 기존 저장본에 유지됩니다.'));
 if(!spans.length){
  body.append(node('p','확정된 형광펜 구간이 없습니다. 원문과 미분류 사유를 확인하세요.','warning'));
  const candidates=[...new Set((tag.evidence_text||[]).filter(q=>typeof q==='string'&&q))];
  if(candidates.length){body.append(node('strong','API가 제시한 후보 근거 · 위치 확정 전'));for(const quote of candidates.slice(0,8))body.append(node('pre',reviewText(quote)))}
 }
 const matches=approvedTagMatches(label);body.append(node('strong','같은 이름의 현재 기준 태그'));
 if(matches.length){
  for(const match of matches)body.append(node('p',match.name+' ('+(match.category_id||'미분류')+') · '+match.cards.size+'개 기준 카드'));
  body.append(node('p','원문 문맥과 위 사유를 함께 검토하세요. 기준 후보를 표시한 것만으로 분류를 변경하지 않습니다.','muted'));
 }else body.append(node('p','같은 이름의 기준 태그는 없습니다. 신규 표현으로 검토하세요.','muted'));
 if(target?.id==='source'){
  const edit=node('button','태그 수정 열기');edit.onclick=()=>$('editTagsBtn').click();body.append(edit);
 }
 panel.append(heading,body);panel.open=true;
}
