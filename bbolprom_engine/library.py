"""Transactional user library. Approved catalogue is a separate read-only resource.

No prompt normalization: identity is the SHA256 of the exact UTF-8 text.
Images are content addressed, original bytes retained; origins include repeat imports.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .sqlite_utils import ClosingConnection


@contextmanager
def _storage_step(operation):
    try:
        yield
    except OSError as exc:
        # A fixed operation name, never a full path, is safe to export.
        exc.bbolprom_operation=operation
        raise

DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY, text TEXT NOT NULL, sha TEXT UNIQUE NOT NULL,
 created TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]', analysis_status TEXT NOT NULL DEFAULT 'not_analyzed');
CREATE TABLE IF NOT EXISTS media(sha TEXT PRIMARY KEY,md5 TEXT NOT NULL,sha1 TEXT NOT NULL,
 bytes INTEGER NOT NULL,path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS card_media(card_id TEXT REFERENCES cards(id),media_sha TEXT REFERENCES media(sha),
 position INTEGER NOT NULL,PRIMARY KEY(card_id,media_sha));
CREATE TABLE IF NOT EXISTS origins(id TEXT PRIMARY KEY,card_id TEXT REFERENCES cards(id),
 filename TEXT NOT NULL,source_sha TEXT NOT NULL,ref TEXT NOT NULL,imported TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analysis_references(id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES cards(id),
 created TEXT NOT NULL,status TEXT NOT NULL,mode TEXT NOT NULL,reference_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS card_versions(id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES cards(id),
 created TEXT NOT NULL,reason TEXT NOT NULL,snapshot_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS import_attempts(id TEXT PRIMARY KEY,created TEXT NOT NULL,updated TEXT NOT NULL,
 mode TEXT NOT NULL,status TEXT NOT NULL,filename TEXT NOT NULL,details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_documents(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,
 bytes INTEGER NOT NULL,stored TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS card_original_files(card_id TEXT NOT NULL REFERENCES cards(id),kind TEXT NOT NULL,
 sha256 TEXT NOT NULL,path TEXT UNIQUE NOT NULL,original_name TEXT NOT NULL,bytes INTEGER NOT NULL,
 PRIMARY KEY(card_id,kind,sha256));
'''

def sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def validate_tags(text, tags):
    seen = set()
    for tag in tags:
        name = tag.get('tag', tag.get('name'))
        if not isinstance(name, str) or not name.strip():
            raise ValueError('빈 태그명')
        if name in seen:
            raise ValueError('같은 카드 태그 중복')
        seen.add(name)
        for s in tag.get('spans', []):
            a, b = s.get('start_cp'), s.get('end_cp')
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text):
                raise ValueError('잘못된 코드포인트 구간')
            if text[a:b] != s.get('evidence'):
                raise ValueError('원문 근거 불일치')

class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'library.sqlite3'
        with self.connect() as c:
            c.executescript(DDL)

    def connect(self):
        c = sqlite3.connect(self.db, timeout=30, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def get_setting(self, key, default=None):
        with self.connect() as c:
            row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def cards(self):
        with self.connect() as c:
            out = []
            for row in c.execute('SELECT * FROM cards ORDER BY created,id'):
                item = dict(row)
                item['source_text'] = item.pop('text')
                item['tags'] = json.loads(item['tags'])
                item['images'] = [dict(r) for r in c.execute('''SELECT m.*,cm.position FROM media m
                  JOIN card_media cm ON cm.media_sha=m.sha WHERE cm.card_id=? ORDER BY cm.position''', (item['id'],))]
                item['origins'] = [dict(r) for r in c.execute('SELECT * FROM origins WHERE card_id=? ORDER BY imported', (item['id'],))]
                audit=c.execute('SELECT reference_json,status,mode FROM analysis_references WHERE card_id=? ORDER BY created DESC LIMIT 1',(item['id'],)).fetchone()
                item['analysis_references']=dict(json.loads(audit[0]),status=audit[1],mode=audit[2]) if audit else None
                item['approved'] = False
                out.append(item)
            return out

    def _put_media(self, stream, expected=None):
        vault = self.root / 'vault'
        vault.mkdir(exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=vault, prefix='pending-')
        hashes = {k: hashlib.new(k) for k in ('md5', 'sha1', 'sha256')}
        size = 0
        try:
            with os.fdopen(fd, 'wb') as f:
                while block := stream.read(1024*1024):
                    f.write(block)
                    size += len(block)
                    for h in hashes.values(): h.update(block)
            dig = {k: h.hexdigest() for k, h in hashes.items()}
            dig['bytes'] = size
            if expected and any(dig[k] != expected.get(k) for k in dig):
                raise ValueError('원본 이미지 해시 불일치')
            rel = 'vault/' + dig['sha256']
            dest = self.root / rel
            if dest.exists():
                if hashlib.sha256(dest.read_bytes()).hexdigest() != dig['sha256']:
                    raise ValueError('저장소 이미지 손상: 등록 중단')
            else:
                os.replace(tmp, dest)
            return dig, rel
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def plan(self, result):
        known={};media={}
        if self.db.is_file():
          with self.connect() as c:
            known = {r['sha']: r['id'] for r in c.execute('SELECT sha,id FROM cards')}
            media = {sha: {r[0] for r in c.execute('SELECT media_sha FROM card_media WHERE card_id=?', (cid,))}
                     for sha, cid in known.items()}
        rows = []
        for card in result['cards']:
            text = card['source_text']; sha = sha_text(text)
            if sha != card['source_text_sha256']:
                raise ValueError('원문 SHA256 불일치')
            if any(not i.get('resolved') or not i.get('digest') for i in card['images']):
                raise ValueError('해결되지 않은 이미지/해시: 등록 전 확인 필요')
            incoming = {i['digest']['sha256'] for i in card['images']}
            new_images = incoming - media.get(sha, set())
            action = 'new_card' if sha not in known else ('add_images' if new_images else 'skip_identical')
            rows.append({'engine_card': card['engine_card'], 'action': action, 'new_images': len(new_images),
                         'existing_id': known.get(sha), 'warnings': card.get('warnings', [])})
            known.setdefault(sha, 'same_batch')
            media.setdefault(sha, set()).update(incoming)
        return rows

    def commit_hwpx(self, source, result):
        from .analysis import file_sha256
        from .hwpx import HWPXReader
        if file_sha256(source) != result['file']['sha256']:
            raise ValueError('분석 이후 원본 파일이 변경됨')
        self.plan(result)
        self.backup(include_sources=False)
        with HWPXReader(source) as reader, self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ids = []
            for card in result['cards']:
                text = card['source_text']
                validate_tags(text, card['tags'])
                row = c.execute('SELECT id FROM cards WHERE sha=?', (sha_text(text),)).fetchone()
                cid = row[0] if row else uuid.uuid4().hex
                if not row:
                    c.execute('INSERT INTO cards VALUES(?,?,?,?,?,?)', (cid, text, sha_text(text), _now(),
                              json.dumps(card['tags'], ensure_ascii=False), 'not_analyzed'))
                for im in card['images']:
                    with reader.zip.open(im['path']) as stream:
                        dig, rel = self._put_media(stream, im['digest'])
                    self._link(c, cid, dig, rel)
                    self._origin(c, cid, result['file']['name'], result['file']['sha256'], im['ref'])
                if not card['images']:
                    self._origin(c, cid, result['file']['name'], result['file']['sha256'], '')
                ids.append(cid)
                from .portable_storage import sync_card_originals
                sync_card_originals(self,c,cid)
            return ids

    def manual(self, text, images, filename='직접 등록'):
        if not isinstance(text, str) or not text.strip(): raise ValueError('원문이 필요합니다')
        self.backup(include_sources=False)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT id FROM cards WHERE sha=?', (sha_text(text),)).fetchone()
            cid = row[0] if row else uuid.uuid4().hex
            if not row:
                c.execute('INSERT INTO cards VALUES(?,?,?,?,?,?)', (cid,text,sha_text(text),_now(),'[]','not_analyzed'))
            for name, stream in images:
                dig, rel = self._put_media(stream)
                self._link(c, cid, dig, rel)
                self._origin(c, cid, name, dig['sha256'], name)
            if not images or filename!='직접 등록': self._origin(c,cid,filename,sha_text(text),'')
            from .portable_storage import sync_card_originals
            sync_card_originals(self,c,cid)
            return cid

    def _link(self, c, cid, dig, rel):
        c.execute('INSERT OR IGNORE INTO media VALUES(?,?,?,?,?)', (dig['sha256'],dig['md5'],dig['sha1'],dig['bytes'],rel))
        pos = c.execute('SELECT COALESCE(MAX(position),-1)+1 FROM card_media WHERE card_id=?', (cid,)).fetchone()[0]
        c.execute('INSERT OR IGNORE INTO card_media VALUES(?,?,?)', (cid,dig['sha256'],pos))

    def _version(self,c,cid,reason):
        row=c.execute('SELECT * FROM cards WHERE id=?',(cid,)).fetchone()
        if row is None:raise ValueError('수정할 신규 카드가 없습니다')
        snapshot=dict(row)
        snapshot['images']=[dict(r) for r in c.execute('SELECT media_sha,position FROM card_media WHERE card_id=? ORDER BY position',(cid,))]
        c.execute('INSERT INTO card_versions VALUES(?,?,?,?,?)',
                  (uuid.uuid4().hex,cid,_now(),reason,json.dumps(snapshot,ensure_ascii=False)))
        return snapshot

    def edit_card(self,cid,text,images,remove_images=(),expected_sha=None):
        if not isinstance(text,str) or not text.strip():raise ValueError('프롬프트 원문이 필요합니다')
        self.backup(include_sources=False)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=self._version(c,cid,'user_card_edit')
            if expected_sha is not None and old['sha']!=expected_sha:raise ValueError('편집 중 다른 창에서 원문이 변경되었습니다. 다시 불러오세요.')
            conflict=c.execute('SELECT id FROM cards WHERE sha=? AND id<>?',(sha_text(text),cid)).fetchone()
            if conflict:raise ValueError('다른 카드와 동일한 원문입니다. 기존 카드를 덮어쓰지 않습니다.')
            known={r['media_sha'] for r in old['images']}
            if set(remove_images)-known:raise ValueError('현재 카드에 없는 이미지입니다')
            tags=json.loads(old['tags'])
            if text!=old['text']:
                # Keep the user's tags, but never attach stale coordinates to
                # changed text. The complete old mapping is in the version.
                for tag in tags:
                    tag['spans']=[]
                    tag['reason']='원문 수정: 근거 재확인 필요'
                status='text_edited_evidence_review'
            else:status=old['analysis_status']
            c.execute('UPDATE cards SET text=?,sha=?,tags=?,analysis_status=? WHERE id=?',
                      (text,sha_text(text),json.dumps(tags,ensure_ascii=False),status,cid))
            for sha in remove_images:c.execute('DELETE FROM card_media WHERE card_id=? AND media_sha=?',(cid,sha))
            for name,stream in images:
                dig,rel=self._put_media(stream);self._link(c,cid,dig,rel);self._origin(c,cid,name,dig['sha256'],name)
            from .portable_storage import sync_card_originals
            sync_card_originals(self,c,cid)
        return cid

    def card_history(self,cid):
        with self.connect() as c:
            versions=[]
            for row in c.execute('SELECT * FROM card_versions WHERE card_id=? ORDER BY created DESC',(cid,)):
                version=dict(row);snapshot=json.loads(version.pop('snapshot_json'))
                version.update(source_text=snapshot['text'],tags=json.loads(snapshot['tags']),images=snapshot['images'])
                versions.append(version)
            return versions

    def restore_card(self,cid,version_id):
        self.backup(include_sources=False)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT snapshot_json FROM card_versions WHERE id=? AND card_id=?',(version_id,cid)).fetchone()
            if not row:raise ValueError('이 카드의 수정 이력이 없습니다')
            target=json.loads(row[0])
            if c.execute('SELECT 1 FROM cards WHERE sha=? AND id<>?',(target['sha'],cid)).fetchone():raise ValueError('다른 카드의 원문과 충돌합니다. 복원 중단')
            self._version(c,cid,'user_restore')
            validate_tags(target['text'],json.loads(target['tags']))
            c.execute('UPDATE cards SET text=?,sha=?,tags=?,analysis_status=? WHERE id=?',
                      (target['text'],target['sha'],target['tags'],target['analysis_status'],cid))
            c.execute('DELETE FROM card_media WHERE card_id=?',(cid,))
            c.executemany('INSERT INTO card_media VALUES(?,?,?)',[(cid,im['media_sha'],im['position']) for im in target['images']])
            from .portable_storage import sync_card_originals
            sync_card_originals(self,c,cid)
        return cid

    def _origin(self, c, cid, filename, source_sha, ref):
        c.execute('INSERT INTO origins VALUES(?,?,?,?,?,?)', (uuid.uuid4().hex,cid,filename,source_sha,ref,_now()))

    def save_analysis(self, cid, result):
        with self.connect() as c:
            row = c.execute('SELECT text FROM cards WHERE id=?', (cid,)).fetchone()
            if not row: raise ValueError('신규 카드가 없습니다. 승인 카드는 분석 대상이 아닙니다.')
            if result.get('source_text') != row[0]: raise ValueError('API 원문 변경 감지')
            tags = result['tags'] + result.get('unclassified', [])
            validate_tags(row[0], tags)
            c.execute('UPDATE cards SET tags=?,analysis_status=? WHERE id=?',
                      (json.dumps(tags,ensure_ascii=False),result['status'],cid))
            self._record_analysis_audit(c,cid,result)

    def _record_analysis_audit(self,c,cid,result):
        audit=result.get('reference_audit')
        if audit is None:return
        expected={'master_sha256','ledger_sha256','workflow_ids','constraint_ids','decision_ids','sources','example_card_ids','selection_method'}
        if not isinstance(audit,dict) or not expected.issubset(audit) or (set(audit)-expected-{'method_guidance','example_revisions'}):raise ValueError('Invalid approval reference audit')
        c.execute('INSERT INTO analysis_references VALUES(?,?,?,?,?,?)',
            (uuid.uuid4().hex,cid,_now(),result['status'],result.get('mode','unknown'),json.dumps(audit,ensure_ascii=False)))

    def record_analysis_audit(self,cid,result):
        # Failed API attempts preserve original tags while retaining provenance
        # of the attempted guidance; provider bodies and secrets are not saved.
        with self.connect() as c:self._record_analysis_audit(c,cid,result)

    def backup(self,*,include_sources=True):
        with _storage_step('backup_prepare'):
            folder = self.root / 'backup'; folder.mkdir(exist_ok=True)
            dest = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.bak.zip')
            fd, tmp = tempfile.mkstemp(dir=folder, suffix='.sqlite3'); os.close(fd)
        try:
            with _storage_step('backup_database_copy'):
                with self.connect() as src, sqlite3.connect(tmp, factory=ClosingConnection) as dst:
                    src.backup(dst)
            with _storage_step('backup_archive_write'):
                with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
                    z.write(tmp, 'library.sqlite3')
                    # Include every vault object: a consistent superset also covers a concurrent import.
                    folders=['vault','new_cards']+(['sources'] if include_sources else [])
                    for name in folders:
                        for path in (self.root/name).rglob('*'):
                            if path.is_symlink():raise ValueError('백업에 외부 연결을 포함하지 않습니다.')
                            if path.is_file() and not path.name.startswith(('pending-','.copy-','.write-')):z.write(path,path.relative_to(self.root))
        finally:
            with _storage_step('backup_temporary_cleanup'):
                os.unlink(tmp)
        return dest

def _now():
    return datetime.now(timezone.utc).isoformat()
