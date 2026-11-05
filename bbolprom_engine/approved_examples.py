"""Explicitly enabled approved-card context for NEW-card semantic API requests.

This is separate from importer/segmenter and from independent A/B evaluation.
The caller must opt in after external-transmission consent. Related historical
source→tag→evidence examples guide a provider; they never force a matching answer,
change card boundaries, rewrite approvals, or reclassify historical categories.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from pathlib import Path
from .approved_context import APPROVED_MASTER_SHA, _features

CATALOG_PATH=Path(__file__).resolve().parent.parent/'assets'/'approved_catalog.json'
EXAMPLE_SCOPE=('Historical user-approved source/tag/evidence example, not a mandatory answer. '
               'Analyze the NEW prompt independently. Historical category IDs describe that approval only; '
               'current active user category definitions govern new classification. No historical data is reclassified.')
MAX_EXAMPLES=3
MAX_TOTAL_CHARS=12000
MAX_PROMPT_CHARS=4000
MAX_TAGS=20


def _sha(text):return hashlib.sha256(text.encode('utf8')).hexdigest()

def _limit(value,name,maximum):
    if type(value) is not int or not 1<=value<=maximum:raise ValueError(f'Invalid {name} example-context bound')


def _span(text,span):
    if not isinstance(span,dict):raise ValueError('Invalid approved evidence mapping')
    start,end,quote=span.get('start_cp'),span.get('end_cp'),span.get('evidence')
    if type(start) is not int or type(end) is not int or not isinstance(quote,str) or not 0<=start<end<=len(text) or text[start:end]!=quote:
        raise ValueError('Approved example evidence does not match immutable source')
    return {'start_cp':start,'end_cp':end,'evidence':quote}


def _score(query,phrase):
    features=_features(phrase)
    return len(query & features)/max(1,len(features))**0.5


def retrieve_approved_examples(text,*,enabled=False,catalog_path=None,catalog=None,
        max_examples=MAX_EXAMPLES,max_total_chars=MAX_TOTAL_CHARS,
        max_prompt_chars=MAX_PROMPT_CHARS,max_tags=MAX_TAGS):
    """Select at most three bounded approved examples without writing any source.

    Selection is lexical retrieval, NOT a semantic model or accuracy benchmark.
    Exact same source prompts are excluded, including by full source SHA. For a
    long source, excerpts are literal slices. Evidence has both original-source
    and excerpt-relative Unicode codepoint coordinates. No image bytes are read.
    """
    if type(enabled) is not bool:raise ValueError('Example retrieval enabled must be boolean')
    if not enabled:return []
    if not isinstance(text,str):raise ValueError('New prompt must be a string')
    _limit(max_examples,'count',MAX_EXAMPLES);_limit(max_total_chars,'total chars',MAX_TOTAL_CHARS)
    _limit(max_prompt_chars,'source chars',MAX_PROMPT_CHARS);_limit(max_tags,'tag count',MAX_TAGS)
    if catalog is None:
        path=Path(catalog_path or CATALOG_PATH)
        raw=path.read_bytes();catalog=json.loads(raw)
        catalog_sha=hashlib.sha256(raw).hexdigest();catalog_name=path.name
    else:
        if catalog_path is not None:raise ValueError('Provide catalog or path, not both')
        catalog_sha=hashlib.sha256(json.dumps(catalog,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
        catalog_name='explicit-in-memory-catalog'
    if not isinstance(catalog,dict) or catalog.get('schema')!='bbolprom-approved-gallery-readonly-v1' or not isinstance(catalog.get('cards'),list):
        raise ValueError('Invalid approved example catalog')
    if catalog.get('origin',{}).get('master_sha256')!=APPROVED_MASTER_SHA:
        raise ValueError('Approved example master provenance mismatch')
    new_sha=_sha(text);q=_features(text);ranked=[]
    for ordinal,card in enumerate(catalog['cards']):
        source=card.get('source_text');card_id=card.get('card_id')
        if not isinstance(source,str) or type(card_id) is not int:raise ValueError('Invalid approved example card')
        if source==text or _sha(source)==new_sha:continue
        tags=card.get('tags')
        if not isinstance(tags,list):raise ValueError('Invalid approved tag mappings')
        scored=[]
        for position,tag in enumerate(tags):
            name=tag.get('tag');cat=tag.get('category_column')
            if cat is None and card.get('user_tag_revision'):continue # user kept this candidate unclassified
            if not isinstance(name,str) or not isinstance(cat,str):raise ValueError('Invalid approved tag identity')
            raw_spans=tag.get('spans',[])
            if not isinstance(raw_spans,list):raise ValueError('Invalid approved spans')
            spans=[_span(source,s) for s in raw_spans]
            relevance=_score(q,name)+sum(_score(q,s['evidence']) for s in spans)/max(1,len(spans))
            if relevance>0:scored.append((relevance,-position,name,cat,spans))
        if not scored:continue
        scored.sort(key=lambda x:(x[0],x[1]),reverse=True)
        relevance=_score(q,source)+scored[0][0]
        if relevance>0:ranked.append((relevance,-ordinal,card,scored[:max_tags]))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    selected=[];remaining=max_total_chars-2
    for _,_,card,tag_rows in ranked:
        if len(selected)>=max_examples:break
        source=card['source_text'];start=0;end=len(source)
        if len(source)>max_prompt_chars:
            anchors=[s['start_cp'] for row in tag_rows for s in row[4]]
            anchor=anchors[0] if anchors else 0
            start=max(0,anchor-max_prompt_chars//4)
            end=min(len(source),start+max_prompt_chars);start=max(0,end-max_prompt_chars)
        excerpt=source[start:end];mappings=[]
        for _,_,name,cat,source_spans in tag_rows:
            contained=[s for s in source_spans if start<=s['start_cp']<s['end_cp']<=end]
            # Do not pretend a mapping had no evidence merely because its real
            # approved evidence lies outside the bounded excerpt.
            if source_spans and not contained:continue
            mappings.append({'name':name,'approved_category_id':cat,
                'standard_tag_id':'std-'+_sha(cat+'\0'+name)[:16],
                'spans':[{'start_cp':s['start_cp']-start,'end_cp':s['end_cp']-start,'evidence':s['evidence']} for s in contained],
                'source_spans':copy.deepcopy(contained),
                'evidence_status':'approved_exact_spans' if contained else 'approved_without_direct_span'})
        if not mappings:continue
        example={'approved_card_id':card['card_id'],'source_text':excerpt,
            'source_excerpt_start_cp':start,'source_excerpt_end_cp':end,
            'full_source_length_cp':len(source),'excerpt_sha256':_sha(excerpt),
            'tag_mappings':mappings,'partial_tag_selection':len(mappings)<len(card['tags']),
            'provenance':{'master_sha256':APPROVED_MASTER_SHA,'catalog_sha256':catalog_sha,
                          'catalog_file':catalog_name,'full_source_sha256':_sha(source)},
            'scope':EXAMPLE_SCOPE}
        if card.get('user_tag_revision'):
            example['provenance'].update(user_tag_revision=card['user_tag_revision'],
                user_tag_revision_sha256=card['user_tag_revision_sha256'])
        while mappings and len(json.dumps(example,ensure_ascii=False,separators=(',',':')))>remaining-(1 if selected else 0):
            mappings.pop();example['partial_tag_selection']=True
        if not mappings:continue
        size=len(json.dumps(example,ensure_ascii=False,separators=(',',':')))
        remaining-=size+(1 if selected else 0);selected.append(example)
    return selected


def prepare_examples_for_request(text,examples):
    """Recheck outbound excerpts and exact offsets; never load a catalog here."""
    if examples is None:return []
    if not isinstance(examples,list) or len(examples)>MAX_EXAMPLES:raise ValueError('Too many approved examples')
    if len(json.dumps(examples,ensure_ascii=False,separators=(',',':')))>MAX_TOTAL_CHARS:
        raise ValueError('Approved examples exceed disclosure size limit')
    output=[];new_sha=_sha(text)
    fields={'approved_card_id','source_text','source_excerpt_start_cp','source_excerpt_end_cp',
            'full_source_length_cp','excerpt_sha256','tag_mappings','partial_tag_selection','provenance','scope'}
    tag_fields={'name','approved_category_id','standard_tag_id','spans','source_spans','evidence_status'}
    for example in examples:
        if not isinstance(example,dict) or set(example)!=fields:raise ValueError('Invalid approved example fields')
        source=example['source_text'];p=example['provenance']
        required={'master_sha256','catalog_sha256','catalog_file','full_source_sha256'}
        revised={'user_tag_revision','user_tag_revision_sha256'}
        if not isinstance(p,dict) or set(p) not in (required,required|revised) or p['master_sha256']!=APPROVED_MASTER_SHA:
            raise ValueError('Invalid approved example provenance')
        if not all(isinstance(p[k],str) and p[k] for k in required):raise ValueError('Invalid approved example provenance types')
        if revised.issubset(p) and (type(p['user_tag_revision']) is not int or p['user_tag_revision']<1 or
                not isinstance(p['user_tag_revision_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',p['user_tag_revision_sha256'])):
            raise ValueError('Invalid user-approved tag edition provenance')
        if not all(re.fullmatch('[0-9a-f]{64}',p[k]) for k in ('master_sha256','catalog_sha256','full_source_sha256')):
            raise ValueError('Invalid approved example provenance digest')
        if not isinstance(source,str) or len(source)>MAX_PROMPT_CHARS or _sha(source)!=example['excerpt_sha256']:
            raise ValueError('Approved example excerpt changed')
        if source==text or p['full_source_sha256']==new_sha:continue
        start,end,length=example['source_excerpt_start_cp'],example['source_excerpt_end_cp'],example['full_source_length_cp']
        if not all(type(n) is int for n in (start,end,length)) or not 0<=start<=end<=length or end-start!=len(source):
            raise ValueError('Invalid approved excerpt source coordinates')
        if type(example['approved_card_id']) is not int or not 1<=example['approved_card_id']<=309 or type(example['partial_tag_selection']) is not bool or example['scope']!=EXAMPLE_SCOPE:
            raise ValueError('Invalid approved example identity/scope')
        if start==0 and end==length and p['full_source_sha256']!=example['excerpt_sha256']:
            raise ValueError('Approved full-source digest disagrees with excerpt')
        mappings=example['tag_mappings']
        if not isinstance(mappings,list) or not 1<=len(mappings)<=MAX_TAGS:raise ValueError('Invalid approved example mapping count')
        for mapping in mappings:
            if not isinstance(mapping,dict) or set(mapping)!=tag_fields:raise ValueError('Invalid example tag mapping')
            if not all(isinstance(mapping[k],str) and mapping[k] for k in ('name','approved_category_id','standard_tag_id')):
                raise ValueError('Invalid approved example tag identity')
            if mapping['standard_tag_id']!='std-'+_sha(mapping['approved_category_id']+'\0'+mapping['name'])[:16]:
                raise ValueError('Approved example standard tag identity mismatch')
            if not isinstance(mapping['spans'],list) or not isinstance(mapping['source_spans'],list) or len(mapping['spans'])!=len(mapping['source_spans']):
                raise ValueError('Invalid approved example paired spans')
            for relative,absolute in zip(mapping['spans'],mapping['source_spans']):
                relative=_span(source,relative)
                if not isinstance(absolute,dict) or set(absolute)!={'start_cp','end_cp','evidence'} or type(absolute['start_cp']) is not int or type(absolute['end_cp']) is not int or absolute!={**relative,'start_cp':relative['start_cp']+start,'end_cp':relative['end_cp']+start}:
                    raise ValueError('Approved example source/excerpt offsets disagree')
            if mapping['evidence_status']!=('approved_exact_spans' if mapping['spans'] else 'approved_without_direct_span'):
                raise ValueError('Approved example evidence status mismatch')
        output.append(copy.deepcopy(example))
    return output
