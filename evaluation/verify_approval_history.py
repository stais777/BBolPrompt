"""Verify copied approval fields against original XLSX/JSON/MD with exact SHA.
Requires original handoff and openpyxl; runtime does not require either.
"""
from pathlib import Path
import argparse,hashlib,json,zipfile
import openpyxl


def verify(handoff,ledger_path):
 root=Path(handoff);raw_ledger=Path(ledger_path).read_bytes();ledger=json.loads(raw_ledger);cache={};values={}
 for sid,source in ledger['sources'].items():
  p=root/source['path'];raw=p.read_bytes()
  if source.get('member'):
   assert hashlib.sha256(raw).hexdigest()==source['archive_sha256']
   with zipfile.ZipFile(p) as z:raw=z.read(source['member'])
  assert hashlib.sha256(raw).hexdigest()==source['sha256'],sid
  if source['kind'] in ('final_master','final_highlight_approval'):
   w=openpyxl.load_workbook(p,read_only=True,data_only=True);cache[sid]={s.title:list(s.values) for s in w};w.close()
  elif source.get('member'):values[sid]=json.loads(raw)
  else:values[sid]=raw.decode('utf8').splitlines()
 for record in ledger['records']:
  p=record['provenance'];sid=p['source_id']
  if 'sheet' in p:
   rows=cache[sid][p['sheet']];expected={str(k):v for k,v in zip(rows[0],rows[p['row']-1]) if k and v is not None}
  else:
   node=values[sid]
   for token in p['json_pointer'].strip('/').split('/'):node=node[int(token)] if isinstance(node,list) else node[token]
   expected={k:v for k,v in node.items() if k not in ('candidate_evidence','evidence')}
  assert record['fields']==expected,record['id']
 for item in ledger['workflow']+ledger['constraints']:
  p=item['provenance'];assert item['text']==values[p['source_id']][p['line']-1]
 return {'ledger_sha256':hashlib.sha256(raw_ledger).hexdigest(),
  'source_files_and_archive_members_sha_verified':len(ledger['sources']),
  'records_checked_against_original_rows_or_json_pointers':len(ledger['records']),
  'workflow_steps_exact_source_lines':len(ledger['workflow']),
  'constraints_exact_source_lines':len(ledger['constraints']),
  'source_field_differences':0,'originals_modified':False,'live_API_called':False}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--handoff',required=True,type=Path)
 p.add_argument('--ledger',default=Path(__file__).resolve().parents[1]/'bbolprom_engine/data/approved_history.json',type=Path)
 p.add_argument('--out',default=Path(__file__).with_name('approval-history-source-verification.json'),type=Path)
 a=p.parse_args();report=verify(a.handoff,a.ledger);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
