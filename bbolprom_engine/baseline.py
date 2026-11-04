"""Register the approved master as fixed data, then attach the known PT's media.

This is baselining, not independent segmentation. The manifest and catalogue are
pinned read-only inputs. No text parser, tag inference or fuzzy matching is used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path

from .analysis import file_sha256
from .library import _now

MASTER_SHA = 'b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'
SOURCE_SHA = 'c5d52ce0cda5901d9da178f88c8d5c2eeb5614eefa5a0546916e4951df881ddf'
MANIFEST_SHA = 'caaf514288846f5faec4ebc69b80f4a83b9c45088cae4d8ccf4dffc3d26b808d'
CATALOG_SHA = 'b5917dcc54209c02d4cbf6d9514ba2c003a3f0618d0221864264072c1f4754f7'
MODE = 'fixed_master_baseline'

DDL = '''
CREATE TABLE IF NOT EXISTS baseline_cards(
 card_id INTEGER PRIMARY KEY CHECK(card_id BETWEEN 1 AND 309), record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS baseline_image_links(
 card_id INTEGER NOT NULL REFERENCES baseline_cards(card_id), position INTEGER NOT NULL,
 ref TEXT NOT NULL, source_path TEXT NOT NULL, media_sha TEXT REFERENCES media(sha),
 PRIMARY KEY(card_id,position));
CREATE TABLE IF NOT EXISTS baseline_sources(
 source_sha TEXT PRIMARY KEY, filename TEXT NOT NULL, bytes INTEGER NOT NULL,
 imported TEXT NOT NULL, master_sha TEXT NOT NULL, manifest_sha TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS baseline_cards_no_update BEFORE UPDATE ON baseline_cards
 BEGIN SELECT RAISE(ABORT,'Approved baseline is read-only'); END;
CREATE TRIGGER IF NOT EXISTS baseline_cards_no_delete BEFORE DELETE ON baseline_cards
 BEGIN SELECT RAISE(ABORT,'Approved baseline is read-only'); END;
CREATE TRIGGER IF NOT EXISTS baseline_links_protect_identity
 BEFORE UPDATE OF card_id,position,ref,source_path ON baseline_image_links
 BEGIN SELECT RAISE(ABORT,'Approved baseline links are read-only'); END;
CREATE TRIGGER IF NOT EXISTS baseline_links_no_delete BEFORE DELETE ON baseline_image_links
 BEGIN SELECT RAISE(ABORT,'Approved baseline links are read-only'); END;
CREATE TRIGGER IF NOT EXISTS baseline_links_no_replacement BEFORE UPDATE OF media_sha ON baseline_image_links
 WHEN OLD.media_sha IS NOT NULL AND NEW.media_sha IS NOT OLD.media_sha
 BEGIN SELECT RAISE(ABORT,'Approved image replacement is forbidden'); END;
'''


def load_dataset(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    paths = ((root/'bbolprom_engine/data/baseline_manifest.json', MANIFEST_SHA),
             (root/'assets/approved_catalog.json', CATALOG_SHA))
    values = []
    for path, expected in paths:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('승인 베이스 자료 SHA256 불일치: '+path.name)
        values.append(json.loads(raw))
    manifest, catalogue = values
    if manifest['basis_master_sha256'] != MASTER_SHA or manifest['source_hwpx_sha256'] != SOURCE_SHA:
        raise ValueError('베이스 기준 마스터/원본 불일치')
    if [c['card_id'] for c in manifest['cards']] != list(range(1, 310)):
        raise ValueError('베이스 카드 ID 불일치')
    approved = {c['card_id']: c for c in catalogue['cards']}
    records = []
    for row in manifest['cards']:
        card = copy.deepcopy(approved[row['card_id']])
        if (card['source_text'] != row['prompt'] or
                hashlib.sha256(row['prompt'].encode()).hexdigest() != row['prompt_sha256'] or
                re.findall(r'image\d+', card['image_ref']) != row['image_refs'] or
                len(row['image_refs']) != len(row['image_paths'])):
            raise ValueError('베이스 원문/이미지 연결 불일치')
        card.update(source_text_sha256=row['prompt_sha256'], master_sha256=MASTER_SHA,
                    source_paragraph_start=row['source_paragraph_start'],
                    source_paragraph_end=row['source_paragraph_end'],
                    analysis_batch=row['analysis_batch'], master_row=row['master_row'],
                    expected_images=[{'ref':ref, 'path':path} for ref, path in
                                     zip(row['image_refs'], row['image_paths'])])
        records.append(card)
    return records


class BaselineStore:
    """Separate fixed-ID records: repeated historical prompts remain distinct."""
    def __init__(self, library, records):
        self.library = library
        self.records = records
        self.paths = sorted({i['path'] for c in records for i in c['expected_images']})
        with library.connect() as c:
            c.executescript(DDL)
            c.execute('BEGIN IMMEDIATE')
            existing = {r['card_id']: r['record_json'] for r in c.execute('SELECT * FROM baseline_cards')}
            encoded = {r['card_id']: json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records}
            if existing:
                if existing != encoded:
                    raise ValueError('저장된 승인 베이스가 기준과 다릅니다. 덮어쓰지 않고 중단합니다.')
            else:
                # The ordinary cards table uses unique prompt hashes and cannot
                # represent the 12 intentionally repeated historical groups.
                c.executemany('INSERT INTO baseline_cards VALUES(?,?)', encoded.items())
                c.executemany('INSERT INTO baseline_image_links VALUES(?,?,?,?,NULL)',
                              [(r['card_id'], pos, im['ref'], im['path'])
                               for r in records for pos, im in enumerate(r['expected_images'])])
            expected = [(r['card_id'], pos, im['ref'], im['path'])
                        for r in records for pos, im in enumerate(r['expected_images'])]
            actual = [tuple(r) for r in c.execute(
                'SELECT card_id,position,ref,source_path FROM baseline_image_links ORDER BY card_id,position')]
            if actual != expected:
                raise ValueError('저장된 베이스 이미지 참조가 기준과 다릅니다.')

    def cards(self):
        with self.library.connect() as c:
            images = {}
            for row in c.execute('''SELECT b.card_id,b.position,b.ref,b.source_path,m.*
                    FROM baseline_image_links b LEFT JOIN media m ON m.sha=b.media_sha
                    ORDER BY b.card_id,b.position'''):
                im = dict(row)
                im['path_in_source'] = im.pop('source_path')
                cid = im.pop('card_id')
                im['missing'] = im['sha'] is None
                images.setdefault(cid, []).append(im)
            origins = [dict(r) for r in c.execute('SELECT * FROM baseline_sources ORDER BY imported')]
            cards = []
            for row in c.execute('SELECT * FROM baseline_cards ORDER BY card_id'):
                card = json.loads(row['record_json'])
                card.update(id='approved-'+str(row['card_id']), approved=True,
                            images=images.get(row['card_id'], []), origins=copy.deepcopy(origins),
                            analysis_status='approved_readonly', baseline_registered=True)
                cards.append(card)
            return cards

    def status(self):
        with self.library.connect() as c:
            linked = c.execute('SELECT COUNT(*) FROM baseline_image_links WHERE media_sha IS NOT NULL').fetchone()[0]
            return {'mode': MODE, 'registered_cards': c.execute('SELECT COUNT(*) FROM baseline_cards').fetchone()[0],
                    'expected_image_references': 531, 'expected_unique_paths': 522,
                    'linked_image_references': linked, 'complete': linked == 531,
                    'source_imports': c.execute('SELECT COUNT(*) FROM baseline_sources').fetchone()[0],
                    'master_sha256': MASTER_SHA, 'manifest_sha256': MANIFEST_SHA}

    def prepare(self, source, name):
        source = Path(source)
        sha = file_sha256(source)
        if sha != SOURCE_SHA:
            raise ValueError('확정 PT.hwpx와 SHA256이 다릅니다. 기존 309개 베이스는 유지됩니다. '
                             '이 경로는 확정 원본의 이미지 연결 전용입니다. 새 문서의 갱신 비교는 아직 지원하지 않습니다.')
        digests = {}
        with zipfile.ZipFile(source) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir()]
            for path in self.paths:
                if names.count(path) != 1:
                    raise ValueError('승인 이미지 경로 없음/중복: '+path)
                hashes = {k: hashlib.new(k) for k in ('md5', 'sha1', 'sha256')}
                size = 0
                with z.open(path) as stream:
                    while block := stream.read(1024*1024):
                        size += len(block)
                        for h in hashes.values(): h.update(block)
                digests[path] = dict(bytes=size, **{k:h.hexdigest() for k,h in hashes.items()})
        cards = []
        for card in self.records:
            cards.append({'card_id':card['card_id'], 'source_text':card['source_text'],
                          'source_text_sha256':card['source_text_sha256'], 'tag_count':len(card['tags']),
                          'images':[dict(im, resolved=True, digest=digests[im['path']]) for im in card['expected_images']]})
        return {'mode': MODE, 'file':{'sha256':sha, 'name':name, 'bytes':source.stat().st_size},
                'master_sha256':MASTER_SHA, 'manifest_sha256':MANIFEST_SHA, 'cards':cards,
                'stats':{'cards':309, 'image_references':531, 'unique_image_paths':522,
                         'tags':sum(len(c['tags']) for c in self.records)},
                'notice':'베이스화: 확정 마스터의 309개 ID·원문·태그를 유지하고 원본 이미지 531건을 연결합니다. '
                         '로컬 카드 분리·태그 분석 결과가 아닙니다. 같은 원문을 가진 기존 카드도 각각 유지합니다.'}

    def commit(self, source, result):
        if result.get('mode') != MODE or result.get('master_sha256') != MASTER_SHA or result.get('manifest_sha256') != MANIFEST_SHA:
            raise ValueError('베이스 반입 검토 정보 불일치')
        if result['file']['sha256'] != SOURCE_SHA or file_sha256(source) != SOURCE_SHA:
            raise ValueError('검토 후 원본이 변경되었습니다. 기존 베이스는 유지됩니다.')
        if len(result['cards']) != 309:
            raise ValueError('베이스 검토 카드 수 불일치')
        paths = {}
        for expected, incoming in zip(self.records, result['cards']):
            if (incoming['card_id'] != expected['card_id'] or incoming['source_text'] != expected['source_text'] or
                    incoming['source_text_sha256'] != expected['source_text_sha256'] or
                    [{'ref':i['ref'],'path':i['path']} for i in incoming['images']] != expected['expected_images']):
                raise ValueError('베이스 카드/이미지 참조 변경 금지')
            for im in incoming['images']:
                if im['path'] in paths and paths[im['path']] != im['digest']:
                    raise ValueError('공유 이미지 해시 불일치')
                paths[im['path']] = im['digest']
        self.library.backup()
        with zipfile.ZipFile(source) as z, self.library.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for path, expected in paths.items():
                with z.open(path) as stream:
                    digest, rel = self.library._put_media(stream, expected)
                c.execute('INSERT OR IGNORE INTO media VALUES(?,?,?,?,?)',
                          (digest['sha256'],digest['md5'],digest['sha1'],digest['bytes'],rel))
            for card in result['cards']:
                for pos, im in enumerate(card['images']):
                    c.execute('UPDATE baseline_image_links SET media_sha=? WHERE card_id=? AND position=?',
                              (im['digest']['sha256'],card['card_id'],pos))
            c.execute('INSERT OR IGNORE INTO baseline_sources VALUES(?,?,?,?,?,?)',
                      (SOURCE_SHA,result['file']['name'],result['file']['bytes'],_now(),MASTER_SHA,MANIFEST_SHA))
        return self.status()
