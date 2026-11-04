"""Read-only analysis of the supplied method package and bounded guidance build.

Descriptive documents are never promoted above actual approvals/current policy.
No executable supplied by the package is run.
"""
from __future__ import annotations
import argparse,hashlib,json,re
from collections import Counter,defaultdict
from pathlib import Path
import openpyxl

MASTER_SHA='b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'

def sha(raw):return hashlib.sha256(raw).hexdigest()

def analyze(root,catalog_path,guidance_out,report_out):
 root=Path(root)
 if any(Path(p).resolve().is_relative_to(root.resolve()) for p in (guidance_out,report_out)):
  raise ValueError('Outputs must stay outside the protected method handoff')
 if Path(guidance_out).resolve()==Path(catalog_path).resolve():raise ValueError('Cannot overwrite approved catalog')
 manifest=json.loads((root/'file_sha256_manifest.json').read_text())['files']
 for name,item in manifest.items():
  p=root/name
  if not p.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe method manifest path')
  raw=p.read_bytes()
  if len(raw)!=item['size'] or sha(raw)!=item['sha256']:raise ValueError('Method source checksum mismatch: '+name)
 master=root/'final/master.xlsx';assert sha(master.read_bytes())==MASTER_SHA
 cumulative=json.loads((root/'final/cumulative_mapping.json').read_text())
 verbatim=json.loads((root/'approval_history_verbatim.json').read_text())
 assert cumulative['source_master_sha256']==MASTER_SHA
 for key,items in verbatim['records_by_source_field'].items():assert items==cumulative[key],key
 cards={c['card_id']:c for c in cumulative['source_cards']}
 assert set(cards)==set(range(1,310))
 mappings=cumulative['mapping_records'];assert len(mappings)==8471
 actual=Counter((r['card_id'],r['category_column'],r['tag']) for r in mappings)
 wb=openpyxl.load_workbook(master,read_only=True,data_only=True)
 vals=list(wb['카드별태그'].values);expected=Counter();image_refs=0
 for row in vals[1:]:
  cid=row[0];card=cards[cid];text=row[14];ref=row[9] or ''
  assert text==card['source_text'] and ref==card['image_ref']
  assert sha(text.encode('utf8'))==card['source_text_sha256']
  ordered=[]
  for i in range(7):
   tags=str(row[i+2] or '').splitlines()
   for t in tags:expected[(cid,chr(67+i),t)]+=1
   ordered+=tags
  assert list(dict.fromkeys(ordered))==str(row[10] or '').splitlines()
  image_refs+=len(re.findall(r'image\d+',ref))
 assert expected==actual;assert image_refs==531
 spans=0;empty=[];by_name=defaultdict(lambda:defaultdict(set))
 for r in mappings:
  text=cards[r['card_id']]['source_text'];assert r['source_text_sha256']==sha(text.encode('utf8'))
  if not r['spans']:empty.append(r['record_id'])
  for s in r['spans']:
   assert text[s['start_cp']:s['end_cp']]==s['evidence'];spans+=1
  by_name[r['tag']][r['category_column']].add(r['card_id'])
 assert spans==10358 and len(empty)==17
 index=json.loads((root/'final/tag_index.json').read_text());assert len(index['entries'])==2200
 for item in index['entries']:
  expected_ids={k:sorted(v) for k,v in by_name[item['태그']].items()}
  assert item['category_card_ids']==expected_ids,item['태그']
  assert item['해당 카드 수']==len(set().union(*by_name[item['태그']].values()))
 catalog=json.loads(Path(catalog_path).read_text());existing={c['card_id']:c for c in catalog['cards']}
 for cid,c in cards.items():
  assert existing[cid]['source_text']==c['source_text'] and existing[cid]['image_ref']==c['image_ref']
 reference={(r['card_id'],r['category_column'],r['tag']):r['spans'] for r in mappings}
 for c in catalog['cards']:
  for t in c['tags']:assert t['spans']==reference[(c['card_id'],t['category_column'],t['tag'])]
 ledger_path=Path(catalog_path).resolve().parents[0].parent/'bbolprom_engine/data/approved_history.json'
 action_field_matches=0
 if ledger_path.is_file():
  oldledger=json.loads(ledger_path.read_text())
  for rec in oldledger['records']:
   if rec['family']!='highlight_decision':continue
   p=rec['provenance']
   if 'json_pointer' in p:
    _,key,action_index=p['json_pointer'].split('/')
    original={k:v for k,v in cumulative[key][int(action_index)].items() if k not in ('candidate_evidence','evidence')}
    assert rec['fields']==original,rec['id']
   else:
    last=cumulative['user_approved_tag_actions_296_309'][p['row']-2];f=rec['fields']
    assert (f['번호'],f['카드'],f['열'],f['기존 태그'],f['처리'],f['정정 또는 통합 대상'],f['원문 판단 근거'])==(last['번호'],last['카드'],last['열'],last['기존 태그'],last['권고 처리'],last['대상 / 정정명'],last['사유'])
   action_field_matches+=1
  assert action_field_matches==287
 # Source-backed reconstruction: include semantic axes, described pipeline and
 # highlighting invariants, but not claims about a new independent parser.
 sources={};axes=[];steps=[];invariants=[];phases=[];exceptions=[]
 for name in ('01_full_process.md','02_decision_rules_examples.md','03_highlighting_mapping.md'):
  raw=(root/name).read_bytes();sid='method-'+sha(name.encode())[:12]
  sources[sid]={'path':name,'sha256':sha(raw),'kind':'reconstructed_method_description','approval_authority':'final master and explicit approvals take precedence'}
  section=''
  for no,line in enumerate(raw.decode('utf8').splitlines(),1):
   if line.startswith('## '):section=line
   target=None
   if name.startswith('01_') and (section.startswith('## 1.') or section.startswith('## 2.')) and line.startswith('5. '):target=exceptions
   if name.startswith('01_') and ((section.startswith('## 4.') and re.match(r'^[1-7]\. ',line)) or (section.startswith('## 5.') and re.match(r'^[1-6]\. ',line))):target=phases
   if name.startswith('02_') and section.startswith('## A.') and line.startswith('| ') and not line.startswith('| 판단') and not line.startswith('|---'):target=axes
   if name.startswith('02_') and section.startswith('## C.') and re.match(r'^\d+\. ',line):target=steps
   if name.startswith('03_') and any(section.startswith('## '+str(n)+'.') for n in (2,3)) and line.startswith('- '):target=invariants
   if name.startswith('03_') and section.startswith('## 6.') and line.startswith('- ') and '위치 후보' not in line:target=invariants
   if target is not None:
    target.append({'id':f'{sid}-L{no}','text':line,'provenance':{'source_id':sid,'line':no}})
 assert len(axes)==10 and len(steps)==7
 conflicts=[
  {'document':'06_codex_implementation_brief.md','issue':'Document reports local v0.3.1 extracted665; current user screenshots/report say495. No evidence these are the same run.',
   'resolution':'Keep each attributed observation; do not overwrite user-reported495 or claim parser quality improved.'},
  {'document':'01_full_process.md','issue':'Historical counts1297/2573 are labelled oldE/place and oldF/situation. Master evidence has F_001-309_승인원본1297 with situation concepts and G열_승인반영_요약2573 with poses.',
   'resolution':'Use semantic field headers and actual approval sheets; preserve original text and record this discrepancy. Do not shift current approved categories based on the summary count.'},
  {'document':'06_codex_implementation_brief.md','issue':'Independent local HWPX engine is an original project goal; latest user stopped local segmentation and requested fixed baselining.',
   'resolution':'Latest user scope governs. This phase audits methods/API context only; do not restart local segmentation or disguise baselining as extraction.'},
  {'document':'03_highlighting_mapping.md','issue':'Description mentions API position candidates; existing API policy assigns exact codepoint calculation to the program.',
   'resolution':'Keep evidence-quote response contract; code computes and validates offsets. No response-schema change is inferred.'},
  {'document':'02_decision_rules_examples.md','issue':'Card304 description says natural C-curl bob was shortened to C-curl bob. The supplied final master/catalog instead retains I:자연스러운 C컬 단발.',
   'resolution':'Preserve the supplied final value. Treat the claimed shortening as an unverified historical description, not a current replacement rule; do not feed summary examples as final approved actions.'},
  {'document':'04_master_schema.md','issue':'Nine round14 raw rows retain pre-approval status strings.',
   'resolution':'Explicit subsequent batch approval and final mappings govern; raw status text is retained and linked to proof.'}]
 guidance={'schema':'bbolprom-method-guidance-1','master_sha256':MASTER_SHA,'sources':sources,
  'semantic_axes':axes,'processing_steps':steps,'normalization_phases':phases,'highlight_invariants':invariants,'historical_exceptions':exceptions,
  'precedence':'Current explicit user scope and API policy > final master/actual approval decisions > reconstructed method descriptions.',
  'limits':['Related examples are contextual, not keyword substitutions or guaranteed correct new-card answers.',
   'Keep current API evidence-quote contract; exact offsets are program-validated.',
   'Historical same-prompt card IDs do not redefine current new-import deduplication policy.',
   'Do not repeat historic per-tag approval rounds for every new card. Ambiguous candidates may remain unclassified.',
   'A static baseline is not evidence of independent extraction or actual model quality.']}
 Path(guidance_out).write_text(json.dumps(guidance,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf8')
 clauses=[c for group in ('semantic_axes','processing_steps','normalization_phases','highlight_invariants','historical_exceptions') for c in guidance[group]]
 for clause in clauses:
  p=clause['provenance'];src=sources[p['source_id']];source_raw=(root/src['path']).read_bytes()
  assert sha(source_raw)==src['sha256']
  assert source_raw.decode('utf8').splitlines()[p['line']-1]==clause['text']
 # Record all six descriptive files as analyzed sources even when not sent live.
 report={'guidance_clauses_source_lines_exact':len(clauses),'method_package_files_hash_verified':len(manifest),'master_sha256':MASTER_SHA,'master_sheets':len(wb.sheetnames),
  'cards':len(cards),'tag_mappings':len(mappings),'spans':spans,'empty_span_records':empty,'image_reference_count':image_refs,
  'unique_image_reference_ids':len({r for c in cards.values() for r in re.findall(r'image\d+',c['image_ref'])}),'binary_media_count_verified':False,
  'existing_ledger_approval_actions_matched':action_field_matches,
  'no_image_cards':[cid for cid,c in cards.items() if not c['image_ref']],'index_entries':len(index['entries']),
  'existing_catalog_text_tags_and_spans_match':True,'verbatim_action_collections':len(verbatim['records_by_source_field']),
  'verbatim_actions':sum(len(v) for v in verbatim['records_by_source_field'].values()),
  'analyzed_method_documents':{p.name:sha(p.read_bytes()) for p in sorted(root.glob('0[1-6]_*.md'))},
  'semantic_axes':len(axes),'processing_steps':len(steps),'normalization_phase_steps':len(phases),'highlight_invariants':len(invariants),'historical_exceptions':len(exceptions),
  'discrepancies_and_scope_resolutions':conflicts,'source_modified':False,'actual_PT_reparsed':False,'live_API_called':False}
 wb.close();Path(report_out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--handoff',required=True,type=Path)
 root=Path(__file__).resolve().parents[1]
 p.add_argument('--catalog',default=root/'assets/approved_catalog.json',type=Path)
 p.add_argument('--out',default=root/'bbolprom_engine/data/method_guidance.json',type=Path)
 p.add_argument('--report',default=root/'evaluation/method-handoff-analysis.json',type=Path)
 a=p.parse_args();r=analyze(a.handoff,a.catalog,a.out,a.report)
 print(json.dumps({k:r[k] for k in ('method_package_files_hash_verified','cards','tag_mappings','spans','image_reference_count','verbatim_action_collections','verbatim_actions','semantic_axes','processing_steps','highlight_invariants')},ensure_ascii=False))
