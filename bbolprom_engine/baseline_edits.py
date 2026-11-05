"""Explicit user tag editions of the fixed309. Original records never change.

An append-only journal lives in the regular backup-covered library DB. Only the
authenticated manual-edit routes call save/restore. API analysis cannot use it
to change a baseline card. Revision0 is always the pinned original.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from .library import _now, validate_tags
from .tags import CATEGORIES

DDL='''
CREATE TABLE IF NOT EXISTS baseline_tag_editions(
 card_id INTEGER NOT NULL REFERENCES baseline_cards(card_id),
 revision INTEGER NOT NULL CHECK(revision>0), created TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN ('save','restore')),
 restored_revision INTEGER, source_sha TEXT NOT NULL, original_sha TEXT NOT NULL,
 tags_sha TEXT NOT NULL, tags_json TEXT NOT NULL, PRIMARY KEY(card_id,revision));
CREATE TRIGGER IF NOT EXISTS baseline_tag_editions_no_update BEFORE UPDATE ON baseline_tag_editions
 BEGIN SELECT RAISE(ABORT,'User tag history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS baseline_tag_editions_no_delete BEFORE DELETE ON baseline_tag_editions
 BEGIN SELECT RAISE(ABORT,'User tag history is append-only'); END;
'''


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()


class BaselineTagEdits:
    def __init__(self,library,records,*,initialize=True):
        self.library=library
        self.records={c['card_id']:copy.deepcopy(c) for c in records}
        if initialize:
            with library.connect() as c:c.executescript(DDL)

    def card_id(self,ident):
        match=re.fullmatch(r'approved-([1-9][0-9]{0,2})',str(ident))
        if not match or int(match[1]) not in self.records:raise ValueError('고정309개 카드 ID가 필요합니다.')
        return int(match[1])

    def _edition(self,card_id,row=None):
        original=self.records[card_id]
        if row is None:
            return {'card_id':card_id,'revision':0,'created':None,'operation':'original',
                'restored_revision':None,'tags':copy.deepcopy(original['tags']),
                'tags_sha':digest(original['tags'])}
        row=dict(row);tags=json.loads(row.pop('tags_json'))
        if (row['source_sha']!=original['source_text_sha256'] or row['original_sha']!=digest(original)
                or row['tags_sha']!=digest(tags)):
            raise ValueError('사용자 태그 수정 이력의 무결성이 다릅니다. 덮어쓰지 않습니다.')
        if not isinstance(tags,list):raise ValueError('태그 이력 형식 오류')
        validate_tags(original['source_text'],tags)
        row['tags']=tags
        return row

    def latest(self,card_id):
        with self.library.connect() as c:
            row=c.execute('SELECT * FROM baseline_tag_editions WHERE card_id=? ORDER BY revision DESC LIMIT 1',(card_id,)).fetchone()
        return self._edition(card_id,row)

    def editions(self):
        with self.library.connect() as c:
            rows=c.execute('''SELECT e.* FROM baseline_tag_editions e JOIN
                (SELECT card_id,max(revision) AS revision FROM baseline_tag_editions GROUP BY card_id) m
                ON e.card_id=m.card_id AND e.revision=m.revision''').fetchall()
        return {r['card_id']:self._edition(r['card_id'],r) for r in rows}

    def project(self,cards):
        latest=self.editions()
        for card in cards:
            edition=latest.get(card['card_id'])
            card['tag_revision']=edition['revision'] if edition else 0
            card['user_tag_edited']=bool(edition and edition['tags']!=self.records[card['card_id']]['tags'])
            if edition:
                card['tags']=copy.deepcopy(edition['tags'])
                card['analysis_status']='user_edited_baseline' if card['user_tag_edited'] else 'approved_original_restored'
        return cards

    def history(self,card_id):
        with self.library.connect() as c:
            rows=c.execute('SELECT * FROM baseline_tag_editions WHERE card_id=? ORDER BY revision DESC',(card_id,)).fetchall()
        return [self._edition(card_id,r) for r in rows]+[self._edition(card_id)]

    def prepare_tags(self,card_id,raw_tags,categories):
        if not isinstance(raw_tags,list) or len(raw_tags)>2000:raise ValueError('태그 목록을 확인하세요 (최대2000개).')
        text=self.records[card_id]['source_text'];old=self.latest(card_id)['tags']
        active={c['id']:c['name'] for c in categories if c.get('enabled',True)}
        result=[];indices=set()
        for raw in raw_tags:
            if not isinstance(raw,dict) or set(raw)-{'name','category_id','evidence','original_spans','source_index'}:
                raise ValueError('지원하지 않는 수동 태그 필드입니다.')
            name=raw.get('name');cat=raw.get('category_id');quote=raw.get('evidence','')
            if not isinstance(name,str) or not name.strip() or len(name)>200 or not isinstance(quote,str):raise ValueError('태그명·원문 근거를 확인하세요.')
            index=raw.get('source_index');previous=None
            if index is not None:
                if type(index) is not int or not 0<=index<len(old) or index in indices:raise ValueError('기존 태그 번호가 다릅니다. 다시 불러오세요.')
                indices.add(index);previous=old[index]
            prior_cat=previous.get('category_id',previous.get('category_column')) if previous else None
            if cat is not None and (not isinstance(cat,str) or (cat not in active and not (previous and cat==prior_cat))):
                raise ValueError('새 소속은 활성 분류에서 선택하세요. 기존 소속은 보존할 수 있습니다.')
            if 'original_spans' in raw:
                if previous is None or raw['original_spans']!=previous.get('spans',[]):raise ValueError('보존할 근거가 기존 구간과 다릅니다. 원문 근거 칸에서 수정하세요.')
                spans=copy.deepcopy(previous.get('spans',[]))
                if quote!=(spans[0]['evidence'] if spans else ''):raise ValueError('수정한 근거와 보존 구간이 다릅니다.')
            else:
                spans=[]
                prior_spans=previous.get('spans',[]) if previous else []
                if previous and quote==(prior_spans[0]['evidence'] if prior_spans else ''):
                    spans=copy.deepcopy(prior_spans)
                elif quote:
                    from .api import evidence_spans
                    spans=evidence_spans(text,[quote])
                    if len(spans)!=1:raise ValueError('원문에 정확히 한 번 나타나는 더 긴 근거 구절을 입력하세요.')
            tag={'tag':name.strip(),'category_column':cat,'spans':spans}
            if cat and cat not in CATEGORIES:tag['category_display_name']=active.get(cat,previous.get('category_display_name','') if previous else '')
            result.append(tag)
        validate_tags(text,result)
        return result

    def _append(self,card_id,tags,expected_revision,operation,restored=None):
        if type(expected_revision) is not int or expected_revision<0:raise ValueError('현재 태그 수정 버전이 필요합니다.')
        validate_tags(self.records[card_id]['source_text'],tags)
        # Existing full backup format automatically includes the edition journal.
        self.library.backup()
        with self.library.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM baseline_tag_editions WHERE card_id=? ORDER BY revision DESC LIMIT 1',(card_id,)).fetchone()
            current=self._edition(card_id,row)
            if current['revision']!=expected_revision:raise ValueError('다른 창에서 태그가 변경됐습니다. 다시 불러온 뒤 수정하세요.')
            if current['tags']==tags:return current['revision']
            revision=expected_revision+1
            c.execute('INSERT INTO baseline_tag_editions VALUES(?,?,?,?,?,?,?,?,?)',
                (card_id,revision,_now(),operation,restored,self.records[card_id]['source_text_sha256'],
                 digest(self.records[card_id]),digest(tags),encoded(tags)))
        return revision

    def save(self,card_id,raw_tags,categories,expected_revision):
        return self._append(card_id,self.prepare_tags(card_id,raw_tags,categories),expected_revision,'save')

    def restore(self,card_id,target_revision,expected_revision):
        if type(target_revision) is not int or target_revision<0:raise ValueError('복원할 태그 버전을 확인하세요.')
        target=next((v for v in self.history(card_id) if v['revision']==target_revision),None)
        if target is None:raise ValueError('이 카드의 태그 수정 이력이 없습니다.')
        return self._append(card_id,target['tags'],expected_revision,'restore',target_revision)

    def reference_catalog(self):
        """In-memory latest user-approved editions, used only with example opt-in."""
        from .baseline import MASTER_SHA
        cards=[{'card_id':r['card_id'],'source_text':r['source_text'],'tags':copy.deepcopy(r['tags'])} for r in self.records.values()]
        latest=self.editions()
        for card in cards:
            edition=latest.get(card['card_id'])
            if edition:
                card['tags']=copy.deepcopy(edition['tags']);card['user_tag_revision']=edition['revision']
                card['user_tag_revision_sha256']=edition['tags_sha']
        return {'schema':'bbolprom-approved-gallery-readonly-v1','origin':{'master_sha256':MASTER_SHA},'cards':cards}


def audit_editions(library,records):
    """Counts/hashes only: never export user tag names or evidence text."""
    result={'edition_count':0,'edited_card_count':0,'effective_tag_count':sum(len(r['tags']) for r in records),
        'latest':[],'errors':[]}
    with library.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='baseline_tag_editions'").fetchone():return result
        rows=c.execute('SELECT * FROM baseline_tag_editions ORDER BY card_id,revision').fetchall()
    service=BaselineTagEdits(library,records,initialize=False);latest={};revision={}
    for row in rows:
        cid=row['card_id'];result['edition_count']+=1
        try:
            entry=service._edition(cid,row)
            if entry['revision']!=revision.get(cid,0)+1:raise ValueError('태그 이력 버전 연속성 오류')
            revision[cid]=entry['revision'];latest[cid]=entry
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            result['errors'].append({'card_id':cid,'revision':row['revision'],'type':type(exc).__name__})
    for cid,entry in latest.items():
        changed=entry['tags']!=service.records[cid]['tags']
        result['edited_card_count']+=int(changed)
        result['effective_tag_count']+=len(entry['tags'])-len(service.records[cid]['tags'])
        result['latest'].append({'card_id':cid,'revision':entry['revision'],'tags_sha256':entry['tags_sha'],
            'tag_count':len(entry['tags']),'span_count':sum(len(t.get('spans',[])) for t in entry['tags']),
            'matches_original_tags':not changed})
    return result
