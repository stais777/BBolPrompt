"""Build a provenance ledger from provided approvals; never save a source workbook.

Approval is resolved from explicit sources and checked against final C~I data.
Historical decisions that no longer match stay in the audit, not live guidance.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re,zipfile
from collections import Counter
from pathlib import Path
import openpyxl

MASTER_SHA='b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'
CANONICAL = {
 'B_001-309_최종승인사전':'vertical_dictionary',
 'C_001-150_승인사전29종':'vertical_dictionary',
 '가로_다음차수적용기준':'approved_rule',
 '가로2차_다음차수적용기준':'approved_rule',
 'F_001-309_승인원본1297':'vertical_situation',
 'H열_승인원본1080':'vertical_props',
 'G열_중복삭제_검토대기':'duplicate_removal',
 'H열_중복검토대기1':'duplicate_removal',
 '가로1차_승인변경이력':'horizontal_decision',
 '가로2차_승인변경이력':'horizontal_decision',
}
for a,b in [(1,50),(51,100),(101,150),(151,200),(201,250),(251,300)]:
 CANONICAL[f'B_{a:03}-{b:03}_승인원본']='vertical_concept'
CANONICAL['B_301-309_승인원본102건']='vertical_concept'
for name in ['C_001-050_승인원본124건','C_051-100_승인원본103건','C_101-150_승인원본114건',
             'C151-200_최종승인감사','C201-250_최종승인감사','C251-300_승인감사','C301-309_승인감사']:
 CANONICAL[name]='vertical_state'

def digest(raw):return hashlib.sha256(raw).hexdigest()
def compact(value):return re.sub(r'\s+','',str(value or ''))
def approved_status(value):
 text=compact(value).lower()
 if re.search(r'미승인|승인대기|승인전|승인필요|미결정|미확정|확정전|확정대기|unapproved|notapproved|disapproved|pending|승인되지|승인철회|승인취소|반려',text):return False
 return '승인' in text or 'approved' in text or bool(re.search(r'사용자.*최종(?:확정|확인)',text))

def operation(raw):
 text=str(raw or '').lower()
 if '중복' in text and '삭제' in text:return 'deduplicate'
 if 'delete' in text or '삭제' in text or 'remov' in text:return 'delete'
 if any(t in text for t in ('merge','통합')):return 'merge'
 if any(t in text for t in ('keep','유지','retention')):return 'keep'
 if any(t in text for t in ('rename','정정','명칭','정규화')):return 'rename'
 if '이동' in text or text=='move':return 'move'
 return 'decision'

def targets(raw, default):
 if isinstance(raw,list):
  out=[]
  for t in raw:
   if isinstance(t,dict):
    cat=t.get('column',t.get('category_column',t.get('category_id',default)))
    name=t.get('tag',t.get('name'))
    if name:out.append({'category_id':cat,'name':str(name)})
  return out
 text=str(raw or '').replace('`','').strip()
 text=re.sub(r'\(명칭 정정 대상\)','',text)
 if text in ('','삭제','태그 삭제','미결정','개별 검토 예정'):return []
 out=[]
 for part in re.split(r'\s+/\s+|\n',text):
  m=re.match(r'^([C-I])\s*:\s*(.+)$',part.strip())
  out.append({'category_id':m[1] if m else default,'name':m[2].strip() if m else part.strip()})
 return out

def final_check(card,cat,before,after,op,final):
 if card is None:return 'approved_rule' if after or before else 'unresolved'
 if card not in final:return 'unresolved'
 if op=='delete':return 'final_confirmed' if (cat,before) not in final[card] else 'historical_conflict'
 if op=='deduplicate':return 'final_confirmed' if (cat,before) in final[card] else 'historical_conflict'
 if not after:return 'unresolved'
 return 'final_confirmed' if all((t['category_id'],t['name']) in final[card] for t in after) else 'historical_conflict'

def build(handoff,destination,audit_path):
 root=Path(handoff)
 if any(Path(p).resolve().is_relative_to(root.resolve()) for p in (destination,audit_path)):
  raise ValueError('Outputs must stay outside the protected handoff')
 sources={};records=[];coverage=[];nested=[];seq=0
 with (root/'FILE_SHA256_MANIFEST.tsv').open(encoding='utf8',newline='') as mf:
  expected={r['archive_path']:r['sha256'] for r in csv.DictReader(mf,delimiter='\t')}
 def source(p,kind,member=None,raw=None):
  rel=str(p.relative_to(root));original=p.read_bytes()
  if expected.get(rel)!=digest(original):raise ValueError('Source manifest mismatch: '+rel)
  payload=original if raw is None else raw
  key=rel+('::'+member if member else '')
  sid='src-'+digest(key.encode())[:16]
  sources[sid]={'path':rel,'member':member,'sha256':digest(payload),'kind':kind}
  if member:sources[sid]['archive_sha256']=digest(p.read_bytes())
  return sid
 def add(sid,loc,fields,kind,card=None,cat=None,before='',after=None,op='decision',authority='approved',proofs=()):
  nonlocal seq
  seq+=1;after=after or []
  state=final_check(card,cat,before,after,op,final) if authority=='approved' else 'pending_excluded'
  record={'id':f'approval-{seq:05}','family':kind,'status':state,'card_id':card,
   'before':{'category_id':cat,'name':before},'after':after,'operation':op,
   'fields':fields,'provenance':{'source_id':sid,**loc},'approval_proofs':list(proofs),
   'scope':'Historical contextual decision; not a universal replacement. Current final approvals and user API policy take precedence.'}
  records.append(record);return record
 master=next((root/'01_확정자료').glob('Bbolprom_Master*.xlsx'))
 if digest(master.read_bytes())!=MASTER_SHA:raise ValueError('Final master checksum mismatch')
 mid=source(master,'final_master')
 wb=openpyxl.load_workbook(master,read_only=True,data_only=True)
 tables={s.title:list(s.values) for s in wb};wb.close()
 base=tables['카드별태그'];final={int(r[0]):{(chr(67+i),t) for i in range(7) for t in str(r[2+i] or '').splitlines() if t} for r in base[1:] if type(r[0]) is int}
 if set(final)!=set(range(1,310)):raise ValueError('Invalid final card IDs')
 for name,rows in tables.items():
  selected=name in CANONICAL;accepted=Counter()
  if selected:
   headers=[str(x or '') for x in rows[0]]
   for rowno,row in enumerate(rows[1:],2):
    f={k:v for k,v in zip(headers,row) if k and v is not None}
    status=' | '.join(str(v) for k,v in f.items() if '상태' in k)
    # A sheet labelled 'waiting' may contain explicit later approval in rows.
    authority='approved' if approved_status(status) else 'pending'
    card=next((int(f[k]) for k in ('카드번호','카드') if type(f.get(k)) is int),None)
    old=next((f[k] for k in ('정규화 전 원본 태그','정규화 전 태그','원본 C태그','원본 F태그','원본 H태그','원본 태그','정규화 태그','중복 태그','변경 전 표준 태그','태그 / 표현 A','대상 태그/동시 존재 표현') if k in f),'')
    oldcat={'vertical_concept':'C','vertical_state':'D','vertical_situation':'G','vertical_props':'I'}.get(CANONICAL[name])
    if name.startswith('B_'):oldcat='C'
    if name.startswith('C_'):oldcat='D'
    if name.startswith('G열'):oldcat='H'
    if name=='H열_중복검토대기1':oldcat='I'
    oldcat=str(f.get('이전 분류',f.get('원래 분류',oldcat or '')))
    destcat=str(f.get('반영 분류',f.get('반영/유지 분류',f.get('확정 분류',oldcat))))
    if CANONICAL[name]=='approved_rule' and '분류' in f:
     category_text=str(f['분류']).strip()
     moving=re.fullmatch(r'([C-I])\s*→\s*([C-I])',category_text)
     if moving:oldcat,destcat=moving.groups()
     elif re.fullmatch('[C-I]',category_text):oldcat=destcat=category_text
     else:oldcat=destcat=None # compound/operating rule; do not invent one category
    output=next((f[k] for k in ('최종 승인 표준 태그','승인 표준 태그','최종 표준 태그','승인 태그','최종 처리','승인 처리','승인 정규화 결과','승인 최종 태그','변경 후 / 유지','정규화 대표어') if k in f),old if CANONICAL[name]=='duplicate_removal' else '')
    op=operation(f.get('변경 종류',f.get('처리',output)))
    if not output and '삭제' in status:op='delete'
    if CANONICAL[name]=='duplicate_removal':op='deduplicate'
    after=targets(output,destcat)
    rec=add(mid,{'sheet':name,'row':rowno},f,CANONICAL[name],card,oldcat,str(old),after,op,authority)
    rec['column_epoch']='Historical B/C/F/G/H labels shifted to current C/D/G/H/I; raw fields retained. Horizontal history uses current C-I.'
    if CANONICAL[name]=='approved_rule' and authority=='approved':rec['status']='approved_rule'
    if card is None and CANONICAL[name]=='duplicate_removal':rec['status']='non_decision_excluded'
    accepted[rec['status']]+=1
  coverage.append({'sheet':name,'rows':len(rows)-1,'selected':selected,'outcomes':dict(accepted),
    'reason':'canonical approval history' if selected else 'Preserved inventory only: earlier cumulative duplicate, unapproved proposal, backup, operational history or validation report; not silently promoted to a current rule'})
 # Dictionary labels that were subsequently moved/removed are not current
 # classification rules. Keep the original fields in the audit unchanged.
 current_pairs=set().union(*final.values())
 for rec in records:
  if rec['family']=='vertical_dictionary' and rec['status']=='approved_rule' and rec['operation']!='delete':
   if not rec['after'] or any((t['category_id'],t['name']) not in current_pairs for t in rec['after']):
    rec['status']='historical_conflict'
 # All Markdown handoffs are inventoried; explicit whole-batch approvals serve as
 # proof for stale individual status strings in cumulative JSON.
 md_proofs={}
 for p in sorted((root/'05_과거작업').glob('*.md')):
  sid=source(p,'approval_handoff' if '승인완료' in p.name else 'review_handoff')
  text=p.read_text();m=re.search(r'카드(\d+)-(\d+)',p.name)
  if m and '승인완료' in p.name:
   count=re.search(r'(?:검토\s*|승인[:：]\s*|사용자[:：]\s*\*\*)?(\d+)건\s*전건',text)
   md_proofs[tuple(map(int,m.groups()))]={'source_id':sid,'approved_count':int(count[1]) if count else None,'statement':'Explicit all-items batch approval in supplied handoff'}
 # Select latest APPROVED cumulative archive; its inherited action groups contain
 # stages1-17. It also retains stale row statuses, which are never used alone.
 zp=next((root/'05_과거작업').glob('*17차승인완료*.zip'))
 with zipfile.ZipFile(zp) as z:
  name=next(n for n in z.namelist() if '001-295' in n and n.endswith('.json'))
  raw=z.read(name);cid=source(zp,'approved_cumulative_json',name,raw);cumulative=json.loads(raw)
 if '미승인0' not in cumulative.get('approval_status',''):raise ValueError('Cumulative approval not established')
 for key,items in cumulative.items():
  if not isinstance(items,list) or not (key.startswith('user_approved_tag_') or key.startswith('approved_tag_changes_')):continue
  match=re.search(r'(\d{3})_(\d{3})$',key);batch=tuple(map(int,match.groups())) if match else None
  proof=md_proofs.get(batch) if batch else None
  if proof and proof['approved_count'] not in (None,len(items)):raise ValueError('Approval summary/action count mismatch '+key)
  for ordinal,item in enumerate(items):
   f={k:v for k,v in item.items() if k not in ('candidate_evidence','evidence')}
   card=item.get('card_id',item.get('카드'));cat=item.get('category_column',item.get('from_column',item.get('source_column',item.get('old_category',item.get('column',item.get('열'))))))
   old=item.get('old_tag',item.get('original_tag',item.get('tag',item.get('기존 태그',''))))
   action=item.get('action',item.get('operation',item.get('recommended_action',item.get('proposed_action',item.get('제안','')))))
   if not action:action='delete' if 'removals' in key else 'keep' if 'retention' in key else 'rename' if item.get('new_tag') else 'merge'
   op=operation(action)
   out=item.get('targets',item.get('target_tags',item.get('into_existing',item.get('new_tag',item.get('target_or_new_tag',item.get('target',item.get('정정명 / 통합 목적지','')))))))
   after=targets(out,item.get('new_category',cat))
   if op=='keep':after=[{'category_id':cat,'name':old}]
   if op=='delete':after=[]
   rec=add(cid,{'json_pointer':'/'+key+'/'+str(ordinal)},f,'highlight_decision',card,cat,old,after,op,proofs=[proof] if proof else [{'source_id':cid,'statement':'Explicit approved action collection inherited in latest approved cumulative data'}])
   row_status=' | '.join(str(v) for k,v in item.items() if 'status' in k or k=='상태')
   if row_status and not approved_status(row_status):
    rec['source_status_conflict']=True
    if not proof:rec['status']='pending_excluded'
    else:rec['approval_resolution']='Raw row retains pre-approval wording. Later explicit whole-batch approval and final mapping support its approved status; original wording is retained as history.'
 # Last18th final approval is an explicit separate XLSX, not the pending zip.
 last=next((root/'01_확정자료').glob('*18차승인*.xlsx'));lastid=source(last,'final_highlight_approval')
 w=openpyxl.load_workbook(last,read_only=True,data_only=True)
 values=list(w['18차 최종 승인12건'].values);w.close()
 for rowno,row in enumerate(values[1:],2):
  f=dict(zip(values[0],row));op=operation(f['처리']);cat=f['열'];old=f['기존 태그']
  after=[{'category_id':cat,'name':old}] if op=='keep' else targets(f['정정 또는 통합 대상'],cat)
  add(lastid,{'sheet':'18차 최종 승인12건','row':rowno},f,'highlight_decision',int(f['카드']),cat,old,after,op,'approved' if approved_status(f['승인 상태']) else 'pending')
 # Exact current API policy work sequence; source lines are preserved, not invented.
 policy=next((root/'02_API_승인지침').glob('*상세구현지침*.md'));pid=source(policy,'user_api_policy');lines=policy.read_text().splitlines();workflow=[];constraints=[];section=''
 for line_no,line in enumerate(lines,1):
  if line.startswith('## '):section=line
  if section.startswith('## 3.') and re.match(r'^\d+\. ',line):workflow.append({'id':f'workflow-{len(workflow)+1}','text':line,'provenance':{'source_id':pid,'line':line_no}})
  if any(section.startswith('## '+str(i)+'.') for i in (4,5,6)) and (line.startswith('- ') or line.startswith('| ')):
   if line.startswith('|---') or line.startswith('| API가'):continue
   constraints.append({'id':f'policy-{len(constraints)+1}','text':line,'provenance':{'source_id':pid,'line':line_no}})
 if len(workflow)!=8:raise ValueError('Expected original eight-step API workflow')
 # Enumerate all nested JSONs for coverage, including pending versions; do not
 # import pending review lists just because they contain the word approval.
 for path in sorted((root/'05_과거작업').glob('*.zip')):
  with zipfile.ZipFile(path) as z:
   for info in z.infolist():
    if not info.filename.endswith('.json'):continue
    d=json.loads(z.read(info));keys=[]
    if isinstance(d,dict):keys=[k for k,v in d.items() if isinstance(v,list) and ('review' in k or 'approved_tag_' in k)]
    nested.append({'archive':path.name,'member':info.filename,'status':d.get('approval_status') if isinstance(d,dict) else None,'action_keys':keys,'used_as_latest_cumulative':path==zp and info.filename==name})
 # Link to explicit later approved actions where possible. A mismatch alone
 # is an observation, not proof that a user revoked a rule.
 for rec in records:
  if rec['card_id'] in final:
   relevant={rec['before']['category_id']}|{t['category_id'] for t in rec['after']}
   rec['current_card_tags']={cat:sorted(n for c,n in final[rec['card_id']] if c==cat) for cat in relevant if cat}
   rec['validation_scope']='Final mapping existence/placement only; an older rationale is not automatically the latest judgment.'
  rec['later_card_decision_ids']=[r['id'] for r in records if r['family']=='highlight_decision' and r['status']=='final_confirmed' and r['card_id']==rec['card_id'] and r['id']!=rec['id']] if rec['family']!='highlight_decision' and rec['card_id'] else []
 accepted=[r for r in records if r['status']=='final_confirmed']
 by_before={}
 for r in accepted:
  by_before.setdefault((r['card_id'],r['before']['category_id'],r['before']['name']),[]).append(r)
 for r in records:
  if r['status']!='historical_conflict':continue
  links=[];observations=[]
  for target in r['after'] or [r['before']]:
   key=(r['card_id'],target['category_id'],target['name'])
   links.extend(x['id'] for x in by_before.get(key,[]) if x['id']!=r['id'] and x['family'] in ('horizontal_decision','highlight_decision'))
   locations=sorted(c for c,n in (final.get(r['card_id'],current_pairs) if r['card_id'] else current_pairs) if n==target['name'])
   observations.append({'name':target['name'],'final_categories':locations})
  r['final_comparison']={'observed_final_locations':observations,'supported_later_decision_ids':sorted(set(links)),
   'interpretation':'Historical output differs from final approved data; no automatic universal rule or invented revocation.'}
 ledger={'schema':'bbolprom-approval-history-1','master_sha256':MASTER_SHA,'sources':sources,'workflow':workflow,'constraints':constraints,'records':records}
 Path(destination).write_text(json.dumps(ledger,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf8')
 audit={'master_sha256':MASTER_SHA,'master_sheets_inventoried':len(coverage),'selected_sheets':len(CANONICAL),'sheet_coverage':coverage,
  'sources':sources,'nested_json_inventory':nested,'record_outcomes':dict(Counter(r['status'] for r in records)),
  'record_families':dict(Counter(r['family'] for r in records)),'source_status_conflicts':[r['id'] for r in records if r.get('source_status_conflict')],
  'workflow_steps':len(workflow),'policy_constraints':len(constraints),
  'limitations':['An approved historical action is not a universal rule. Final-mismatched records are excluded from live guidance.',
   'Inventory is not blanket approval: older candidate sheets and pending JSON lists are not sent as current decisions.',
   'Other historical workbooks and illustrative HTML repeat intermediate states; not all are promoted. No unavailable original chat log is invented.',
   'Individual B/C/F/G/H labels in vertical worksheets refer to an older column layout; raw fields remain unchanged.']}
 Path(audit_path).write_text(json.dumps(audit,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf8')
 return ledger,audit

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--handoff',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--audit',required=True,type=Path);a=p.parse_args()
 ledger,audit=build(a.handoff,a.out,a.audit);print(json.dumps({k:audit[k] for k in ('master_sheets_inventoried','selected_sheets','record_outcomes','record_families','workflow_steps','policy_constraints')},ensure_ascii=False,indent=2))
