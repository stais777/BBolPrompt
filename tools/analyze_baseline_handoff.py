"""Read-only linkage audit of supplied baseline QA and completed tag master.

Does not resegment PT, repeat a semantic approval review, execute supplied scripts
or claim the absent physical images were rehashed in this environment.
"""
from pathlib import Path
import argparse,csv,hashlib,json,re
from collections import Counter,defaultdict
import openpyxl

MASTER_SHA='b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def analyze(root,uploaded_master,catalog,out):
 root=Path(root);uploaded_master=Path(uploaded_master);out=Path(out)
 if out.resolve().is_relative_to(root.resolve()):raise ValueError('Keep output outside protected baseline package')
 checked=[]
 for line in (root/'SHA256SUMS.txt').read_text().splitlines():
  if not line.strip():continue
  expected,name=line.split(None,1);name=name.strip();p=root/name
  if not p.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe checksum path')
  assert sha(p)==expected,name;checked.append(name)
 embedded=next(root.glob('Bbolprom_Master*.xlsx'))
 assert sha(uploaded_master)==sha(embedded)==MASTER_SHA
 manifest=json.loads((root/'04_카드별_원문_이미지_매니페스트.json').read_text())
 final=json.loads((root/'02_반입검증_최종_20261104.json').read_text())
 initial=json.loads((root/'03_반입검증_초기_71건미해결_수정전.json').read_text())
 assert manifest['basis_master_sha256']==final['referenceMasterSha256']==MASTER_SHA
 records=manifest['cards'];assert [r['card_id'] for r in records]==list(range(1,310))
 assert final['matchedCardIds']==list(range(1,310)) and final['missingCardIds']==[] and final['unresolvedImages']==[]
 existing={c['card_id']:c for c in json.loads(Path(catalog).read_text())['cards']}
 w=openpyxl.load_workbook(uploaded_master,read_only=True,data_only=True)
 rows=list(w['카드별태그'].values);master={int(r[0]):r for r in rows[1:]}
 history_extract=json.loads((root/'09_마스터_검수이력_추출본.json').read_text())
 def trim_empty_tail(row):
  row=[None if x=='' else x for x in row]
  while row and row[-1] in (None,''):row.pop()
  return row
 for name,values in history_extract.items():assert [trim_empty_tail(r) for r in w[name].values]==[trim_empty_tail(r) for r in values],name
 paths=defaultdict(list);by_prompt=defaultdict(list);connection_rows=[];no_image=[];multi=[]
 for c in records:
  cid=c['card_id'];r=master[cid];text=r[14];refs=re.findall(r'image\d+',r[9] or '')
  assert c['prompt']==text==existing[cid]['source_text']
  assert c['prompt_sha256']==hashlib.sha256(text.encode()).hexdigest()
  assert c['image_refs']==refs==re.findall(r'image\d+',existing[cid]['image_ref'])
  assert (c['source_paragraph_start'],c['source_paragraph_end'],c['analysis_batch'],c['master_row'])==(r[11],r[12],r[13],cid+1)
  assert len(c['image_paths'])==len(refs)
  for ref,path in zip(refs,c['image_paths']):
   paths[path].append(cid);connection_rows.append({'card':cid,'ref':ref,'path':path})
  if not refs:no_image.append(cid)
  if len(refs)>1:multi.append(cid)
  by_prompt[c['prompt_sha256']].append(cid)
  actual={(cat,t) for i,cat in enumerate('CDEFGHI') for t in str(r[i+2] or '').splitlines() if t}
  expected={(t['category_column'],t['tag']) for t in existing[cid]['tags']}
  assert actual==expected
 assert connection_rows==final['imagePaths']
 assert len(connection_rows)==531 and len(paths)==522 and no_image==[188] and len(multi)==70
 shared={k:v for k,v in paths.items() if len(v)>1};assert len(shared)==9
 groups={k:v for k,v in by_prompt.items() if len(v)>1};assert len(groups)==12
 def csv_rows(name):
  with (root/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
 csv_cards=csv_rows('05_카드별_이미지연결_309.csv');assert len(csv_cards)==309
 for row,c in zip(csv_cards,records):
  assert int(row['카드ID'])==c['card_id'] and row['원문_SHA256']==c['prompt_sha256']
  assert int(row['이미지연결수'])==len(c['image_refs'])
  assert re.findall(r'image\d+',row['이미지참조순서'])==c['image_refs']
  assert [v.strip() for v in row['이미지파일경로'].split('|') if v.strip()]==c['image_paths']
  assert row['원문시작']==str(c['source_paragraph_start']) and row['원문끝']==str(c['source_paragraph_end'])
  assert int(row['마스터행'])==c['master_row']
 shared_csv=csv_rows('06_공유이미지_9건.csv')
 for row in shared_csv:
  ids=[int(i.strip()) for i in row['카드ID'].split('/')]
  assert shared[row['이미지파일']]==ids and int(row['연결횟수'])==len(ids)
 group_csv=csv_rows('07_동일원문_서로다른카드_참고.csv')
 for row in group_csv:assert groups[row['프롬프트SHA256']]==[int(i.strip()) for i in row['카드ID'].split('/')]
 report={'baseline_package_files_sha_verified':len(checked),'separately_uploaded_master_sha256':sha(uploaded_master),
  'embedded_master_identical':True,'existing_309_catalog_matches':True,
  'cards':len(records),'tag_mappings':sum(len(c['tags']) for c in existing.values()),'image_reference_rows':len(connection_rows),
  'unique_image_paths_in_historical_report':len(paths),'no_image_cards':no_image,'multiple_image_cards':len(multi),
  'shared_image_paths':shared,'same_prompt_card_groups':list(groups.values()),'unique_prompt_count':len(by_prompt),
  'historical_audit_sheets_match':len(history_extract),'history_extract_empty_cell_representation_and_trailing_padding_ignored':True,'source_paragraph_ranges_match':True,
  'historical_final_unresolved_image_references':len(final['unresolvedImages']),
  'historical_initial_unresolved_image_records':len(initial['unresolvedImages']),
  'initial_71_issue_is_already_resolved':True,'card_ids_merged':False,
  'original_PT_present':False,'PT_reparsed_here':False,'image_binary_hashes_recomputed_here':False,'master_modified':False,
  'source_roles':{'baseline_QA':'Confirmed card identity, prompt, ordered image references and historical path resolution.',
                  'completed_master':'Final tag/category values for the same card IDs; highlighting anchors cross-linked to approved cumulative mapping.'},
  'policy_note':'Current user stopped independent local segmentation. Do not reinterpret the attached future-engine goals as permission to resume it.'}
 w.close();out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--handoff',required=True,type=Path);p.add_argument('--master',required=True,type=Path)
 project=Path(__file__).resolve().parents[1]
 p.add_argument('--catalog',type=Path,default=project/'assets/approved_catalog.json')
 p.add_argument('--out',type=Path,default=project/'evaluation/baseline-handoff-analysis.json')
 a=p.parse_args();r=analyze(a.handoff,a.master,a.catalog,a.out)
 print(json.dumps({k:r[k] for k in ('baseline_package_files_sha_verified','embedded_master_identical','cards','image_reference_rows','unique_image_paths_in_historical_report','multiple_image_cards','unique_prompt_count','historical_audit_sheets_match')},ensure_ascii=False))
