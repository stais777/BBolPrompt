"""Source-backed approval workflow and safely scoped historical decisions.

This is an API context selector, never an importer, automatic synonym replacer,
classifier, or proof of model quality. Original sources and the309 stay unchanged.
"""
from __future__ import annotations
import copy,hashlib,json,math,re
from collections import Counter
from pathlib import Path
from .approved_context import APPROVED_MASTER_SHA,_features

HISTORY_PATH=Path(__file__).parent/'data/approved_history.json'
ALLOWED_STATUSES={'approved_rule','final_confirmed','historical_conflict','pending_excluded','unresolved','non_decision_excluded'}
LIVE_STATUSES={'approved_rule','final_confirmed'}
MAX_RECORDS=12
MAX_CHARS=32000

def _valid_sha(s):return isinstance(s,str) and bool(re.fullmatch('[a-f0-9]{64}',s))

def validate_history(data):
    if not isinstance(data,dict) or set(data)!={'schema','master_sha256','sources','workflow','constraints','records'}:
        raise ValueError('Invalid approval history fields')
    if data['schema']!='bbolprom-approval-history-1' or data['master_sha256']!=APPROVED_MASTER_SHA:
        raise ValueError('Approval history master provenance mismatch')
    sources=data['sources']
    if not isinstance(sources,dict) or not sources:raise ValueError('Approval history sources required')
    for sid,source in sources.items():
        if not isinstance(sid,str) or not isinstance(source,dict) or not _valid_sha(source.get('sha256')):
            raise ValueError('Invalid approval source digest')
        if not isinstance(source.get('path'),str) or not source['path'] or source['path'].startswith('/') or '..' in Path(source['path']).parts:
            raise ValueError('Invalid approval source path')
        if source.get('member') and not _valid_sha(source.get('archive_sha256')):raise ValueError('Nested archive digest required')
    seen=set()
    def provenance(p):
        if not isinstance(p,dict) or p.get('source_id') not in sources:raise ValueError('Unknown approval provenance')
        if 'row' in p and (type(p['row']) is not int or p['row']<2):raise ValueError('Invalid source row')
        if 'line' in p and (type(p['line']) is not int or p['line']<1):raise ValueError('Invalid source line')
    if not isinstance(data['workflow'],list) or len(data['workflow'])!=8:raise ValueError('Original eight-step workflow required')
    for item in data['workflow']+data['constraints']:
        if set(item)!={'id','text','provenance'} or not isinstance(item['text'],str) or not item['text']:
            raise ValueError('Invalid source-backed workflow item')
        provenance(item['provenance'])
        if item['id'] in seen:raise ValueError('Duplicate approval ID')
        seen.add(item['id'])
    if not isinstance(data['records'],list):raise ValueError('Approval records required')
    for r in data['records']:
        if not isinstance(r,dict) or r.get('status') not in ALLOWED_STATUSES or not isinstance(r.get('fields'),dict):raise ValueError('Invalid approval decision')
        if not isinstance(r.get('id'),str) or not r['id'] or r['id'] in seen:raise ValueError('Duplicate approval ID')
        seen.add(r['id']);provenance(r.get('provenance'))
        if r.get('card_id') is not None and (type(r['card_id']) is not int or not 1<=r['card_id']<=309):raise ValueError('Invalid historical card ID')
        if not isinstance(r.get('before'),dict) or not isinstance(r.get('after'),list):raise ValueError('Invalid decision mapping')
        for proof in r.get('approval_proofs',[]):
            if proof.get('source_id') not in sources:raise ValueError('Unknown approval proof')
    record_ids={r['id'] for r in data['records']}
    for r in data['records']:
        if any(i not in record_ids for i in r.get('later_card_decision_ids',[])):raise ValueError('Unknown later judgment link')
    return data

def load_approval_history(path=None):
    raw=Path(path or HISTORY_PATH).read_bytes()
    data=json.loads(raw)
    validate_history(data)
    return data

def retrieve_approval_history(text,history=None,*,record_limit=MAX_RECORDS,char_limit=MAX_CHARS,exclude_card_ids=()):
    """Always provide the approved method; choose a bounded contextual history.

    Excludes all unresolved/pending/final-mismatching rows. Later approved card
    decisions accompany an older matching mapping, preventing a stale rationale
    from being presented without the final context. Text selection is lexical,
    not a claim that the model has semantically judged the new prompt.
    """
    if not isinstance(text,str):raise ValueError('New source text required')
    if type(record_limit) is not int or not 1<=record_limit<=MAX_RECORDS:raise ValueError('Invalid history record limit')
    if type(char_limit) is not int or not 8000<=char_limit<=MAX_CHARS:raise ValueError('Invalid history size bound')
    history=load_approval_history() if history is None else validate_history(history)
    excluded=set(exclude_card_ids)
    if any(type(cid) is not int or not 1<=cid<=309 for cid in excluded):raise ValueError('Invalid edited baseline card IDs')
    ledger_sha=hashlib.sha256(json.dumps(history,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
    q=_features(text);by_id={r['id']:r for r in history['records']}
    candidates=[]
    for index,r in enumerate(history['records']):
        if r['status'] not in LIVE_STATUSES or r['card_id'] in excluded:continue
        # Never score card IDs/counts/status as relevant subject matter.
        content=' '.join([str(r['before'].get('name',''))]+[str(t.get('name','')) for t in r['after']]+[
          str(v) for k,v in r['fields'].items() if any(w in k for w in ('근거','사유','reason','원칙','예외','기준'))])
        f=_features(content);overlap=q & f
        if not overlap:continue
        score=len(overlap)/max(1,len(f))**0.5
        priority=1.2 if r['family']=='highlight_decision' else 1.1 if r['family']=='approved_rule' else 1
        candidates.append((score*priority,-index,r))
    candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
    base={'schema':'bbolprom-selected-approval-history-1','master_sha256':APPROVED_MASTER_SHA,
      'ledger_sha256':ledger_sha,'workflow':copy.deepcopy(history['workflow']),
      'constraints':copy.deepcopy(history['constraints']),'decisions':[],'sources':{},
      'scope':'Only relevant approved contextual history. Latest card decisions/current tags outrank older rationales. No universal substitutions or automatic reapproval.',
      'selection_method':'lexical retrieval; semantic judgment and uncertainty belong to the provider'}
    def outbound(rows):
        p=copy.deepcopy(base);p['decisions']=copy.deepcopy(rows)
        used={i['provenance']['source_id'] for i in p['workflow']+p['constraints']+rows}
        used.update(proof['source_id'] for r in rows for proof in r.get('approval_proofs',[]))
        p['sources']={sid:copy.deepcopy(history['sources'][sid]) for sid in sorted(used)}
        return p
    chosen=[];ids=set();families=Counter();signatures=set()
    for _,_,record in candidates:
        if record['id'] in ids or families[record['family']]>=4:continue
        signature=json.dumps([record['family'],record['before'],record['after'],
           {k:v for k,v in record['fields'].items() if '사유' in k or 'reason' in k or '근거' in k}],ensure_ascii=False,sort_keys=True)
        if signature in signatures:continue
        companions=[by_id[i] for i in record.get('later_card_decision_ids',[]) if by_id[i]['status'] in LIVE_STATUSES and by_id[i]['card_id'] not in excluded and i not in ids]
        additions=[]
        for r in companions+[record]:
            if r['id'] not in ids and r['id'] not in {x['id'] for x in additions}:additions.append(r)
        if len(chosen)+len(additions)>record_limit:continue
        trial=outbound(chosen+additions)
        if len(json.dumps(trial,ensure_ascii=False,separators=(',',':')))>char_limit:continue
        chosen+=additions;ids.update(r['id'] for r in additions);families.update(r['family'] for r in additions);signatures.add(signature)
    result=outbound(chosen)
    if len(json.dumps(result,ensure_ascii=False,separators=(',',':')))>char_limit:raise ValueError('Mandatory approved workflow exceeds context budget')
    return result
