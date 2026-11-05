"""Transactional new-card writes and append-only tag/correction history.

No baseline writes, media operations, source edits, credential storage, or ZIP
compression on each tag operation. Existing complete backups include these tables.
"""
from __future__ import annotations
import copy,json,sqlite3,uuid
from pathlib import Path
from ..sqlite_utils import ClosingConnection
from ..library import _now,sha_text,validate_tags
from ..baseline import load_dataset
from .common import digest,encoded,key,name

DDL='''
CREATE TABLE IF NOT EXISTS api_card_state(card_id TEXT PRIMARY KEY REFERENCES cards(id),
 source_sha TEXT NOT NULL,tags_sha TEXT NOT NULL,revision INTEGER NOT NULL,
 protected_json TEXT NOT NULL,excluded_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_tag_editions(id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES cards(id),
 revision INTEGER NOT NULL,source_sha TEXT NOT NULL,created TEXT NOT NULL,reason TEXT NOT NULL,
 before_json TEXT NOT NULL,after_json TEXT NOT NULL,protected_json TEXT NOT NULL,excluded_json TEXT NOT NULL,
 UNIQUE(card_id,revision));
CREATE TABLE IF NOT EXISTS api_user_corrections(id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES cards(id),
 revision INTEGER NOT NULL,source_sha TEXT NOT NULL,created TEXT NOT NULL,tags_json TEXT NOT NULL,removed_json TEXT NOT NULL,
 UNIQUE(card_id,revision));
CREATE TABLE IF NOT EXISTS api_correction_events(correction_id TEXT NOT NULL REFERENCES api_user_corrections(id),
 event_no INTEGER NOT NULL,active INTEGER NOT NULL CHECK(active IN (0,1)),created TEXT NOT NULL,
 PRIMARY KEY(correction_id,event_no));
CREATE TABLE IF NOT EXISTS api_runs(id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES cards(id),
 created TEXT NOT NULL,status TEXT NOT NULL,mode TEXT NOT NULL,audit_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_category_definitions(category_id TEXT NOT NULL,revision INTEGER NOT NULL,
 created TEXT NOT NULL,base_sha TEXT NOT NULL,definition_json TEXT NOT NULL,PRIMARY KEY(category_id,revision));
'''
TABLES={'api_card_state','api_tag_editions','api_user_corrections','api_correction_events','api_runs','api_category_definitions'}
for table in TABLES-{'api_card_state'}:
    for operation in ('UPDATE','DELETE'):
        DDL+=f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'API history is append-only'); END;\n"


class StaleResult(ValueError):pass


class Repository:
    def __init__(self,db,records=None):
        self.db=Path(db).resolve()
        records=load_dataset() if records is None else records
        if [r['card_id'] for r in records]!=list(range(1,310)):raise ValueError('확정309 기준이 필요합니다.')
        self.approved_hashes={r['source_text_sha256'] for r in records}
        with sqlite3.connect(self.db,factory=ClosingConnection) as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='api_runs'").fetchone()
            if not exists:
                folder=self.db.parent/'backup';folder.mkdir(exist_ok=True)
                # DB-only pre-schema snapshot, NOT a complete media backup.
                target=folder/('api-engine-before-'+uuid.uuid4().hex+'.db-snapshot')
                with sqlite3.connect(target,factory=ClosingConnection) as backup:c.backup(backup)
            c.executescript('BEGIN IMMEDIATE;'+DDL+'COMMIT;')

    @staticmethod
    def _authorize(action,table,column,*_):
        if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
            if table=='cards':return sqlite3.SQLITE_OK if action==sqlite3.SQLITE_UPDATE and column in ('tags','analysis_status') else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if table in TABLES or table=='analysis_references' else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH,sqlite3.SQLITE_ALTER_TABLE,
                      sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_DROP_TRIGGER,sqlite3.SQLITE_CREATE_TRIGGER,
                      sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_PRAGMA):return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def connect(self,*,readonly=False):
        c=sqlite3.connect(self.db.as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) if readonly else sqlite3.connect(self.db,timeout=30,factory=ClosingConnection)
        c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        if not readonly:c.set_authorizer(self._authorize)
        return c

    def _card(self,c,cid):
        if not isinstance(cid,str) or cid.startswith('approved-'):raise ValueError('신규 등록 카드만 분석 가능합니다. 승인 카드 재분석 금지')
        row=c.execute('SELECT * FROM cards WHERE id=?',(cid,)).fetchone()
        if row is None or row['sha'] in self.approved_hashes:raise ValueError('신규 등록 카드만 분석 가능합니다. 승인 카드 재분석 금지')
        if sha_text(row['text'])!=row['sha']:raise ValueError('신규 원문 해시 불일치')
        return row

    def _snapshot(self,c,cid):
        card=self._card(c,cid);tags=json.loads(card['tags']);validate_tags(card['text'],tags)
        state=c.execute('SELECT * FROM api_card_state WHERE card_id=?',(cid,)).fetchone()
        if state is None or state['source_sha']!=card['sha'] or state['tags_sha']!=digest(tags):
            # Pre-engine/externally restored tags are conservatively protected.
            protected=[copy.deepcopy(t) for t in tags if state is not None or t.get('source')!='semantic_api']
            excluded=json.loads(state['excluded_json']) if state else []
            revision=state['revision']+1 if state else 0
            c.execute('INSERT OR REPLACE INTO api_card_state VALUES(?,?,?,?,?,?)',
                (cid,card['sha'],digest(tags),revision,encoded(protected),encoded(excluded)))
            state=c.execute('SELECT * FROM api_card_state WHERE card_id=?',(cid,)).fetchone()
        return {'id':cid,'text':card['text'],'sha':card['sha'],'tags':tags,'revision':state['revision'],
            'token':digest([card['sha'],card['tags'],state['revision']]),
            'protected':json.loads(state['protected_json']),'excluded':json.loads(state['excluded_json'])}

    def snapshot(self,cid):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');return self._snapshot(c,cid)

    def _write(self,c,s,tags,protected,excluded,reason,status):
        validate_tags(s['text'],tags)
        if len(encoded(tags))>2_000_000:raise ValueError('태그 저장 크기 제한')
        rev=s['revision']+1;ident=uuid.uuid4().hex
        c.execute('INSERT INTO api_tag_editions VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ident,s['id'],rev,s['sha'],_now(),reason,encoded(s['tags']),encoded(tags),encoded(protected),encoded(excluded)))
        c.execute('UPDATE cards SET tags=?,analysis_status=? WHERE id=? AND sha=?',
            (encoded(tags),status,s['id'],s['sha']))
        c.execute('UPDATE api_card_state SET source_sha=?,tags_sha=?,revision=?,protected_json=?,excluded_json=? WHERE card_id=?',
            (s['sha'],digest(tags),rev,encoded(protected),encoded(excluded),s['id']))
        return rev

    def manual(self,cid,tags,expected_token=None,*,reason='user_edit'):
        if len({key(t) for t in tags})!=len(tags):raise ValueError('같은 카드 태그 중복')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');s=self._snapshot(c,cid)
            if expected_token is not None and expected_token!=s['token']:raise StaleResult('다른 창에서 변경됐습니다. 새로 열어 수정하세요.')
            excluded={key(t):t for t in s['excluded']}
            names={key(t) for t in tags}
            for t in s['tags']:
                if key(t) not in names:excluded[key(t)]={'tag':name(t),'category_id':t.get('category_id',t.get('category_column'))}
            for k in names:excluded.pop(k,None)
            excluded=list(excluded.values());protected=copy.deepcopy(tags)
            rev=self._write(c,s,tags,protected,excluded,reason,'user_edited')
            ident=uuid.uuid4().hex
            c.execute('INSERT INTO api_user_corrections VALUES(?,?,?,?,?,?,?)',
                (ident,cid,rev,s['sha'],_now(),encoded(tags),encoded(excluded)))
            c.execute('INSERT INTO api_correction_events VALUES(?,?,?,?)',(ident,1,1,_now()))
            return rev

    def finish(self,s,result,audit,guard=None):
        """Commit tag result+history+audit together; invalid/stale results retain tags."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');current=self._snapshot(c,s['id'])
            if current['token']!=s['token']:
                result=dict(result,status='stale_result',warnings=['분석 중 카드가 변경돼 이전 결과를 적용하지 않았습니다.'])
            elif guard is not None and not guard():
                result=dict(result,status='stale_reference',warnings=['참고 기준·분류·교정이 바뀌어 결과를 적용하지 않았습니다.'])
            if result['status'] in ('ok','partial'):
                blocked={key(t) for t in current['excluded']};protected={key(t):t for t in current['protected']}
                merged={key(t):t for t in result['tags']+result.get('unclassified',[]) if key(t) not in blocked}
                merged.update(protected);tags=list(merged.values())
                self._write(c,current,tags,current['protected'],current['excluded'],'api_result',result['status'])
                result=dict(result,tags=[t for t in tags if t.get('category_id',t.get('category_column')) is not None],
                    unclassified=[t for t in tags if t.get('category_id',t.get('category_column')) is None])
            c.execute('INSERT INTO api_runs VALUES(?,?,?,?,?,?)',
                (uuid.uuid4().hex,s['id'],_now(),result['status'],result.get('mode','unknown'),encoded(audit)))
            reference=result.get('reference_audit')
            if reference:
                c.execute('INSERT INTO analysis_references VALUES(?,?,?,?,?,?)',
                    (uuid.uuid4().hex,s['id'],_now(),result['status'],result.get('mode','unknown'),encoded(reference)))
            return result

    def history(self,cid):
        with self.connect(readonly=True) as c:
            self._card(c,cid)
            rows=c.execute('SELECT id,revision,source_sha,created,reason,before_json,after_json FROM api_tag_editions WHERE card_id=? ORDER BY revision DESC',(cid,)).fetchall()
            result=[{k:r[k] for k in ('id','revision','source_sha','created','reason')}|{'tags':json.loads(r['after_json'])} for r in rows]
            if rows:
                first=rows[-1]
                result.append({'id':'initial','revision':0,'source_sha':first['source_sha'],'created':first['created'],'reason':'initial_tags','tags':json.loads(first['before_json'])})
            return result

    def restore(self,cid,ident,token):
        with self.connect(readonly=True) as c:
            card=self._card(c,cid)
            row=c.execute('SELECT * FROM api_tag_editions WHERE card_id=? ORDER BY revision LIMIT 1',(cid,)).fetchone() if ident=='initial' else c.execute('SELECT * FROM api_tag_editions WHERE card_id=? AND id=?',(cid,ident)).fetchone()
            if row is None or row['source_sha']!=card['sha']:raise ValueError('현재 원문과 같은 버전의 태그 이력만 복원할 수 있습니다.')
            tags=json.loads(row['before_json'] if ident=='initial' else row['after_json'])
        return self.manual(cid,tags,token,reason='restore_tags')

    def corrections(self):
        with self.connect(readonly=True) as c:
            rows=c.execute('''
                SELECT x.*,c.tags AS current_tags,s.tags_sha AS current_tags_sha,s.protected_json AS current_protected,
                coalesce((SELECT active FROM api_correction_events e WHERE e.correction_id=x.id ORDER BY event_no DESC LIMIT 1),0) AS active
                FROM api_user_corrections x JOIN cards c ON c.id=x.card_id AND c.sha=x.source_sha
                JOIN api_card_state s ON s.card_id=c.id AND s.source_sha=c.sha
                WHERE x.revision=(SELECT max(y.revision) FROM api_user_corrections y WHERE y.card_id=x.card_id)
                ORDER BY x.created DESC LIMIT 500''').fetchall()
            return [dict(r,tags=json.loads(r['tags_json']),removed=json.loads(r['removed_json'])) for r in rows
                if digest(json.loads(r['current_tags']))==r['current_tags_sha'] and r['current_protected']==r['tags_json']]

    def correction_active(self,ident,active):
        if type(active) is not bool:raise ValueError('교정 활성 상태를 확인하세요.')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM api_user_corrections WHERE id=?',(ident,)).fetchone()
            if row is None:raise ValueError('교정 이력이 없습니다.')
            self._card(c,row['card_id'])
            number=c.execute('SELECT coalesce(max(event_no),0)+1 FROM api_correction_events WHERE correction_id=?',(ident,)).fetchone()[0]
            c.execute('INSERT INTO api_correction_events VALUES(?,?,?,?)',(ident,number,int(active),_now()))

    def summary(self):
        with self.connect(readonly=True) as c:
            return {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in sorted(TABLES)}
