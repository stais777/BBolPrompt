"""Local DB registry for newly analyzed cards; user-confirmed commits only.

Original image bytes are streamed unchanged to local vault. Duplicate decisions
use source SHA256 and original image MD5+SHA1. Approval of legacy 309 is protected.
"""
from __future__ import annotations
import hashlib,json,os,shutil,sqlite3, tempfile
from datetime import datetime,timezone
from pathlib import Path
from .hwpx import HWPXReader

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text_sha256 TEXT NOT NULL UNIQUE,
  source_text TEXT NOT NULL,
  origin_name TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'engine_draft'
);
CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  md5 TEXT NOT NULL, sha1 TEXT NOT NULL,
  bytes INTEGER NOT NULL, vault_path TEXT NOT NULL,
  UNIQUE(md5,sha1)
);
CREATE TABLE IF NOT EXISTS card_images (
  card_id INTEGER NOT NULL REFERENCES cards(id),
  image_id INTEGER NOT NULL REFERENCES images(id),
  position INTEGER NOT NULL,
  source_file TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  imported_utc TEXT NOT NULL,
  PRIMARY KEY (card_id,image_id)
);
CREATE TABLE IF NOT EXISTS tags (
  card_id INTEGER NOT NULL REFERENCES cards(id),
  category TEXT NOT NULL, name TEXT NOT NULL, spans_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'engine_rule',
  PRIMARY KEY(card_id,category,name)
);
CREATE TABLE IF NOT EXISTS review_items (
  card_id INTEGER NOT NULL REFERENCES cards(id),
  ordinal INTEGER NOT NULL,
  item_json TEXT NOT NULL,
  PRIMARY KEY(card_id,ordinal)
);
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name TEXT NOT NULL, source_sha256 TEXT NOT NULL,
  imported_utc TEXT NOT NULL, decision_json TEXT NOT NULL
);
'''

def connect(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=root/'cards.sqlite3';c=sqlite3.connect(db)
    c.executescript(SCHEMA)
    return db,c

def build_plan(result,root):
    root=Path(root)
    db=root/'cards.sqlite3'
    known={};images={}
    if db.is_file():
        con=sqlite3.connect(db)
        try:
            known={sha:card_id for card_id,sha in con.execute('SELECT id,text_sha256 FROM cards')}
            images={card_id:{(md5,sha1) for md5,sha1 in con.execute('''
                SELECT i.md5,i.sha1 FROM card_images ci JOIN images i ON ci.image_id=i.id WHERE ci.card_id=?''',(card_id,))}
                    for card_id in known.values()}
        finally:con.close()
    rows=[]
    seen_by_text={}
    for c in result['cards']:
        sha=c['source_text_sha256']
        existing=known.get(sha)
        incoming={(im['digest']['md5'],im['digest']['sha1'])
                  for im in c['images'] if im['resolved'] and 'digest' in im}
        if any(im['resolved'] and 'digest' not in im for im in c['images']):
            raise ValueError('이미지 MD5/SHA1이 없는 결과입니다. --skip-image-hash 없이 다시 분석하세요.')
        previous=seen_by_text.get(sha)
        if previous:
            first_idx, available=previous
            count=len(incoming-available)
            action=('add_images_to_existing' if existing else 'merge_to_new_batch_card') if count else 'skip_identical'
            available.update(incoming)
            target=first_idx
        else:
            available=set(images.get(existing,set()))
            count=len(incoming-available)
            action=('add_images_to_existing' if count else 'skip_identical') if existing else 'new_card'
            available.update(incoming)
            seen_by_text[sha]=(c['engine_card'],available)
            target=None
        rows.append({'engine_card':c['engine_card'],'existing_db_card_id':existing,
                     'action':action,'merge_target_engine_card':target,
                     'new_image_count':count,'source_sha256':sha})
    return {'schema':'bbolprom-import-review-alpha-0.2',
            'input_sha256':result['file']['sha256'],'source_name':result['file']['name'],
            'decisions':rows,
            'summary':{k:sum(x['action']==k for x in rows)
                       for k in ('new_card','add_images_to_existing','merge_to_new_batch_card','skip_identical')}}

def _stream_asset(reader,path,destination,expected):
    dest=Path(destination);dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='pending_',dir=str(dest.parent));os.close(fd)
    h_md5=hashlib.md5();h_sha1=hashlib.sha1();size=0
    try:
        with reader.zip.open(path) as src,open(tmp,'wb') as dst:
            while chunk:=src.read(1024*1024):
                h_md5.update(chunk);h_sha1.update(chunk);size+=len(chunk);dst.write(chunk)
        if (h_md5.hexdigest(),h_sha1.hexdigest(),size)!=(expected['md5'],expected['sha1'],expected['bytes']):
            raise ValueError('원본 미디어 해시 불일치: '+path)
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def register(result,hwpx_path,root,commit=False):
    """Dry run default; persistent changes only with explicit --commit."""
    path=Path(hwpx_path); root=Path(root)
    import hashlib
    digest=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):digest.update(b)
    if digest.hexdigest()!=result['file']['sha256']:
        raise ValueError('반입 파일 해시가 분석 당시 파일과 다릅니다. 등록 중단.')
    plan=build_plan(result,root)
    if not commit:return plan
    root.mkdir(parents=True,exist_ok=True)
    db=root/'cards.sqlite3'
    if db.is_file():
        bak=root/'backup';bak.mkdir(exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        # SQLite online-safe backup; do not overwrite the only backup.
        conn=sqlite3.connect(db)
        try:
            dst=sqlite3.connect(bak/f'cards_{stamp}.bak.sqlite3')
            try:conn.backup(dst)
            finally:dst.close()
        finally:conn.close()
    _,conn=connect(root)
    now=datetime.now(timezone.utc).isoformat()
    with HWPXReader(path) as reader:
        assigned_ids={}
        try:
            with conn:
                for c,row in zip(result['cards'],plan['decisions']):
                    if row['action']=='skip_identical':continue
                    if row['action']=='new_card':
                        cur=conn.execute('INSERT INTO cards(text_sha256,source_text,origin_name,created_utc,updated_utc,status) VALUES(?,?,?,?,?,?)',
                            (c['source_text_sha256'],c['source_text'],result['file']['name'],now,now,'engine_draft'))
                        card_id=cur.lastrowid
                        assigned_ids[c['source_text_sha256']]=card_id
                        for number,item in enumerate(c['review_candidates']+c.get('unclassified_tag_candidates',[])):
                            conn.execute('INSERT INTO review_items(card_id,ordinal,item_json) VALUES(?,?,?)',
                                (card_id,number,json.dumps(item,ensure_ascii=False)))
                        for tag in c['tags']:
                            conn.execute('INSERT INTO tags(card_id,category,name,spans_json) VALUES(?,?,?,?)',
                                (card_id,tag['category_column'],tag['tag'],json.dumps(tag['spans'],ensure_ascii=False)))
                    else:card_id=row['existing_db_card_id'] or assigned_ids[c['source_text_sha256']]
                    for ix,im in enumerate(c['images']):
                        if not im['resolved'] or 'digest' not in im:continue
                        dig=im['digest'];md5,sha1=dig['md5'],dig['sha1']
                        existing=conn.execute('SELECT id FROM images WHERE md5=? AND sha1=?',(md5,sha1)).fetchone()
                        if existing:image_id=existing[0]
                        else:
                            ext=Path(im['path']).suffix.lower()
                            vault=f'vault/{md5[:2]}/{md5}_{sha1}{ext}'
                            actual=root/vault
                            if not actual.exists():_stream_asset(reader,im['path'],actual,dig)
                            cur=conn.execute('INSERT INTO images(md5,sha1,bytes,vault_path) VALUES(?,?,?,?)',
                                (md5,sha1,dig['bytes'],vault));image_id=cur.lastrowid
                        already=conn.execute('SELECT 1 FROM card_images WHERE card_id=? AND image_id=?',
                                             (card_id,image_id)).fetchone()
                        if not already:
                            position=conn.execute('SELECT COUNT(*) FROM card_images WHERE card_id=?',(card_id,)).fetchone()[0]
                            conn.execute('INSERT INTO card_images(card_id,image_id,position,source_file,source_ref,imported_utc) VALUES(?,?,?,?,?,?)',
                                (card_id,image_id,position,result['file']['name'],im['ref'],now))
                conn.execute('INSERT INTO imports(source_name,source_sha256,imported_utc,decision_json) VALUES(?,?,?,?)',
                    (result['file']['name'],result['file']['sha256'],now,json.dumps(plan,ensure_ascii=False)))
        finally:conn.close()
    return plan
