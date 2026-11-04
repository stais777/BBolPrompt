"""Optional frozen STANDARD TERM VOCABULARY.

Contains only finalized tag names and permissible category IDs; it must never
contain original prompts, card IDs, per-card tags, image references, or spans.
Thus it can help identify literal known terms but cannot reproduce baseline labels.
"""
from __future__ import annotations
import json
from pathlib import Path

def load_terms(mode='generic'):
    if mode=='generic':return []
    if mode!='approved_terms':raise ValueError('knowledge mode must be generic or approved_terms')
    path=Path(__file__).parent/'lexicon'/'approved_terms_only.json'
    data=json.loads(path.read_text(encoding='utf8'))
    assert data['schema']=='bbolprom-terms-only-0.2'
    for t in data['terms']:
        assert set(t)=={'tag','category_column'},'Lexicon must not contain per-card answers'
    return data['terms']

class TermScanner:
    def __init__(self,terms):
        self.root={}
        for it in terms:
            name=it['tag'];word=name.lower()
            if not 2<=len(word)<=70:continue
            cur=self.root
            for c in word:cur=cur.setdefault(c,{})
            cur.setdefault('$',[]).append(it)
    def find(self,text):
        low=text.lower()
        if len(low)!=len(text):
            # Maintaining exact original code point offsets is more important than
            # matching a rare Unicode case-expansion character.
            return
        for start,char in enumerate(low):
            cur=self.root.get(char)
            if cur is None:continue
            end=start+1
            while True:
                if '$' in cur:
                    for it in cur['$']:
                        yield it,start,end
                if end>=len(low) or low[end] not in cur:break
                cur=cur[low[end]];end+=1
