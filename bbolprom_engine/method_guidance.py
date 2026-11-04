"""Bounded, source-exact descriptions of the historical tagging method.

These descriptions do not authorize changed product policy, baseline mutation,
local resegmentation or hidden retries. Actual approvals/current user scope win.
"""
from __future__ import annotations
import copy,hashlib,json,re
from pathlib import Path
from .approved_context import APPROVED_MASTER_SHA

METHOD_PATH=Path(__file__).parent/'data/method_guidance.json'
MAX_METHOD_CHARS=24000

def validate_method_guidance(data):
 expected={'schema','master_sha256','sources','semantic_axes','processing_steps','normalization_phases','highlight_invariants','historical_exceptions','precedence','limits'}
 if not isinstance(data,dict) or set(data)!=expected or data['schema']!='bbolprom-method-guidance-1' or data['master_sha256']!=APPROVED_MASTER_SHA:
  raise ValueError('Invalid method guidance provenance/schema')
 if not isinstance(data['sources'],dict) or not data['sources']:raise ValueError('Method sources required')
 for source in data['sources'].values():
  if not isinstance(source,dict) or not re.fullmatch('[a-f0-9]{64}',source.get('sha256','')) or source.get('kind')!='reconstructed_method_description':
   raise ValueError('Invalid method description source')
  if source.get('path') not in ('01_full_process.md','02_decision_rules_examples.md','03_highlighting_mapping.md'):
   raise ValueError('Unknown method description source')
 seen=set()
 for name,count in [('semantic_axes',10),('processing_steps',7),('normalization_phases',13),('highlight_invariants',14),('historical_exceptions',2)]:
  items=data[name]
  if not isinstance(items,list) or len(items)!=count:raise ValueError('Method description collection mismatch')
  for item in items:
   if set(item)!={'id','text','provenance'} or not isinstance(item['text'],str) or not item['text']:raise ValueError('Invalid method clause')
   if item['id'] in seen:raise ValueError('Duplicate method clause ID')
   seen.add(item['id']);p=item['provenance']
   if not isinstance(p,dict) or set(p)!={'source_id','line'} or p['source_id'] not in data['sources'] or type(p['line']) is not int or p['line']<1:
    raise ValueError('Invalid method source line')
 if not isinstance(data['limits'],list) or not all(isinstance(x,str) for x in data['limits']):raise ValueError('Invalid method limits')
 return data

def load_method_guidance(path=None):
 return validate_method_guidance(json.loads(Path(path or METHOD_PATH).read_bytes()))

def prepare_method_guidance(data):
 if data is None:return None
 validate_method_guidance(data)
 canonical=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 if len(canonical)>MAX_METHOD_CHARS:raise ValueError('Method guidance disclosure exceeds limit')
 result=copy.deepcopy(data)
 result['guidance_sha256']=hashlib.sha256(canonical.encode('utf8')).hexdigest()
 return result
