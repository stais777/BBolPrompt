"""Read-only, provenance-carrying approval decisions. No source prompts/baseline.

The lexical retriever chooses material for a semantic provider, not tag results.
Its approved dictionaries/rules are historical contextual guidance, never a
hard-coded before→after replacement engine or a search alias database.
"""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path

APPROVED_MASTER_SHA='b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'
SNAPSHOT = Path(__file__).parent / 'data' / 'approved_context.json'

def _features(text):
    low = str(text).casefold()
    words = set(re.findall(r'[\w]+', low))
    compact = ''.join(c for c in low if not c.isspace())
    return words | {compact[i:i+2] for i in range(len(compact)-1)}

def load_approved_context(path=None):
    data = json.loads(Path(path or SNAPSHOT).read_text(encoding='utf8'))
    if data.get('schema') != 'bbolprom-approved-context-1':
        raise ValueError('Unsupported approved context snapshot')
    # Deliberately restricted snapshot contract: no per-card prompts, images or spans.
    if set(data) != {'schema','source_sha256','standards','decisions'}:
        raise ValueError('Unexpected approved context fields')
    if data['source_sha256']!=APPROVED_MASTER_SHA:
        raise ValueError('Approved context master provenance mismatch')
    if not isinstance(data['standards'],list) or not isinstance(data['decisions'],list):
        raise ValueError('Invalid context collections')
    for standard in data['standards']:
        if set(standard)!={'id','name','category_id'} or not all(isinstance(standard[k],str) and standard[k] for k in standard):
            raise ValueError('Invalid standard tag context')
    for decision in data['decisions']:
        if set(decision)!={'id','fields','provenance','scope'} or not isinstance(decision['fields'],dict):
            raise ValueError('Invalid decision context')
        p=decision['provenance']
        if not isinstance(p,dict) or set(p)!={'file','sha256','sheet','row'} or p['sha256']!=APPROVED_MASTER_SHA or type(p['row']) is not int or p['row']<2:
            raise ValueError('Invalid approval decision provenance')
        if not all(isinstance(v,(str,int,float)) and not isinstance(v,bool) for v in decision['fields'].values()):
            raise ValueError('Decision context must contain scalar spreadsheet fields')
    return data

def retrieve_context(text, context=None, *, decision_limit=12, tag_limit=100):
    """Return bounded relevant approved decisions, standards, and provenance.

    No matching approved-card answer is ever returned. The model must analyze
    the new text independently, including negation, intention and actors.
    """
    context = context if context is not None else load_approved_context()
    q = _features(text)
    def select(rows, content, limit):
        scored = []
        for i, row in enumerate(rows):
            f = _features(content(row))
            overlap = q & f
            if overlap:
                scored.append((len(overlap) / max(1,len(f))**0.5, -i, row))
        return [copy.deepcopy(r) for _,_,r in sorted(scored,key=lambda x:(x[0],x[1]),reverse=True)[:limit]]
    decisions = select(context.get('decisions',[]),lambda x:json.dumps(x.get('fields',{}),ensure_ascii=False),decision_limit)
    standards = select(context.get('standards',[]),lambda x:x['name'],tag_limit)
    # Include exact standards named by selected decisions, within the same budget.
    decision_text = json.dumps(decisions,ensure_ascii=False)
    selected = {t['id'] for t in standards}
    for item in context.get('standards',[]):
        if len(standards)>=tag_limit:break
        if item['id'] not in selected and item['name'] in decision_text:
            standards.append(copy.deepcopy(item));selected.add(item['id'])
    return {'standards':standards,'decisions':decisions,
            'source_sha256':context.get('source_sha256'),
            'retrieval':'lexical selection of approved contextual decisions; semantic judgment is provider work'}
