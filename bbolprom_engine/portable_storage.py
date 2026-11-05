"""Portable data, verified non-destructive legacy copying, retained originals.

All persisted asset paths are relative to data. Windows credentials stay in the
OS vault. Migration never removes or rewrites the old user's library.
"""
from __future__ import annotations
import hashlib
import http.client
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sqlite3
import tempfile
from .sqlite_utils import ClosingConnection

LAYOUT=1
LOCATION_HINT='Bbolprom-portable-location.json'


def previous_data_root(target,profile):
    """Prefer the most recent portable data during a later program update.

    A folder already containing data always wins. Never silently re-import a
    stale LocalAppData library after the user has started using portable data.
    """
    target=Path(target).resolve();profile=Path(profile)
    if (target/'library.sqlite3').is_file():return None
    hint=profile/LOCATION_HINT
    if not hint.is_file():return profile/'Bbolprom'
    if hint.stat().st_size>8192:raise ValueError('이전 자료 폴더 위치 기록을 확인할 수 없습니다. 기존 data를 함께 옮겨주세요.')
    try:
        saved=json.loads(hint.read_text(encoding='utf8'));path=Path(saved['data_path'])
        valid=saved.get('schema')=='bbolprom-portable-location-1' and path.is_absolute()
    except (ValueError,KeyError,TypeError):valid=False;path=None
    if not valid or not (path/'library.sqlite3').is_file() or not (path/'portable.json').is_file():
        raise ValueError('이전에 사용한 data 폴더를 찾을 수 없습니다. 기존 data를 이 프로그램 폴더에 함께 옮겨주세요.')
    return path


def remember_data_root(root,profile):
    try:
        atomic_bytes(Path(profile)/LOCATION_HINT,json.dumps({'schema':'bbolprom-portable-location-1','data_path':str(Path(root).resolve())},ensure_ascii=False).encode())
        return True
    except OSError:return False


def relative_file(root,value):
    if not isinstance(value,str) or not value or '\\' in value or PureWindowsPath(value).is_absolute():
        raise ValueError('자료의 상대경로가 올바르지 않습니다.')
    rel=Path(value)
    if rel.is_absolute() or '..' in rel.parts or ':' in value:raise ValueError('자료 경로가 저장 폴더를 벗어납니다.')
    probe=Path(root)
    for part in rel.parts:
        probe=probe/part
        if probe.is_symlink() or getattr(probe,'is_junction',lambda:False)():raise ValueError('자료의 외부 연결은 사용하지 않습니다.')
    path=(Path(root)/rel).resolve()
    if not path.is_relative_to(Path(root).resolve()):raise ValueError('자료 경로가 저장 폴더를 벗어납니다.')
    return path


def file_digest(path):
    hs={k:hashlib.new(k) for k in ('sha256','sha1','md5')};size=0
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024):
            size+=len(block)
            for h in hs.values():h.update(block)
    return dict(bytes=size,**{k:h.hexdigest() for k,h in hs.items()})


def atomic_copy(source,destination,expected=None,progress=None):
    source=Path(source);destination=Path(destination)
    initial=source.stat()
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        measured=file_digest(destination)
        if expected and measured['sha256']==expected:return measured
        raise ValueError('보관된 원본 파일이 기존 기록과 다릅니다. 덮어쓰지 않았습니다.')
    fd,temp=tempfile.mkstemp(dir=destination.parent,prefix='.copy-')
    hs={k:hashlib.new(k) for k in ('sha256','sha1','md5')};size=0
    try:
        with os.fdopen(fd,'wb') as dst,source.open('rb') as src:
            while block:=src.read(1024*1024):
                dst.write(block);size+=len(block)
                for h in hs.values():h.update(block)
                if progress:progress(len(block))
            dst.flush();os.fsync(dst.fileno())
        measured=dict(bytes=size,**{k:h.hexdigest() for k,h in hs.items()})
        current=source.stat()
        if (initial.st_size,initial.st_mtime_ns)!=(current.st_size,current.st_mtime_ns):raise ValueError('복사 도중 원본 파일이 변경됐습니다. 전환하지 않았습니다.')
        if expected and measured['sha256']!=expected:raise ValueError('복사 도중 원본 파일이 변경됐습니다. 전환하지 않았습니다.')
        # Both streams are closed before Windows rename/readback.
        if file_digest(temp)!=measured:raise ValueError('복사된 파일의 해시가 다릅니다.')
        os.replace(temp,destination)
        return measured
    finally:
        if os.path.exists(temp):os.unlink(temp)


def atomic_bytes(destination,body):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=destination.parent,prefix='.write-')
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(body);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,destination)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def preserve_basefile(library,source):
    from . import baseline
    from .library import _now
    from .analysis import file_sha256
    if file_sha256(source)!=baseline.SOURCE_SHA:raise ValueError('확정 PT.hwpx와 SHA256이 다릅니다. 기존 자료는 유지됩니다.')
    measured=atomic_copy(source,relative_file(library.root,'sources/PT.hwpx'),baseline.SOURCE_SHA)
    with library.connect() as c:
        old=c.execute("SELECT sha256,bytes FROM source_documents WHERE path='sources/PT.hwpx'").fetchone()
        if old and (old['sha256']!=measured['sha256'] or old['bytes']!=measured['bytes']):raise ValueError('원본 문서 보관 기록과 다릅니다.')
        c.execute('INSERT OR IGNORE INTO source_documents VALUES(?,?,?,?)',
            ('sources/PT.hwpx',measured['sha256'],measured['bytes'],_now()))
    return measured


def _basename(name):
    name=Path(str(name).replace('\\','/')).name
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')
    if not name:name='image.bin'
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:name='_'+name
    suffix=Path(name).suffix[:12];return Path(name).stem[:75]+suffix


def sync_card_originals(library,c,cid):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',cid):raise ValueError('카드 보관 ID가 올바르지 않습니다.')
    card=c.execute('SELECT text,sha FROM cards WHERE id=?',(cid,)).fetchone()
    if card is None:raise ValueError('원본을 보관할 신규 카드가 없습니다.')
    base='new_cards/'+cid
    texts={card['sha']:card['text']};historic_images={}
    for version in c.execute('SELECT snapshot_json FROM card_versions WHERE card_id=?',(cid,)):
        snapshot=json.loads(version['snapshot_json']);texts[snapshot['sha']]=snapshot['text']
        for image in snapshot['images']:historic_images.setdefault(image['media_sha'],image['position'])
    for sha,text in texts.items():
        rel=base+'/원문-'+sha+'.txt';path=relative_file(library.root,rel);body=text.encode('utf8')
        if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('이전 원문 버전의 해시가 다릅니다.')
        if path.exists():
            if file_digest(path)['sha256']!=sha:raise ValueError('보관 원문이 기록과 다릅니다. 덮어쓰지 않았습니다.')
        else:atomic_bytes(path,body)
        c.execute('INSERT OR IGNORE INTO card_original_files VALUES(?,?,?,?,?,?)',(cid,'text',sha,rel,'원문.txt',len(body)))
    rows=[dict(r) for r in c.execute('''SELECT m.*,cm.position FROM card_media cm JOIN media m ON m.sha=cm.media_sha
        WHERE cm.card_id=? ORDER BY cm.position''',(cid,)).fetchall()]
    known={r['sha'] for r in rows}
    for sha,pos in historic_images.items():
        if sha in known:continue
        row=c.execute('SELECT * FROM media WHERE sha=?',(sha,)).fetchone()
        if row is None:raise ValueError('이전 카드 버전의 원본 이미지가 없습니다.')
        rows.append(dict(row,position=pos));known.add(sha)
    for im in rows:
        old=c.execute("SELECT path FROM card_original_files WHERE card_id=? AND kind='image' AND sha256=?",(cid,im['sha'])).fetchone()
        source=relative_file(library.root,im['path'])
        origin=c.execute('SELECT filename FROM origins WHERE card_id=? AND source_sha=? ORDER BY imported LIMIT 1',(cid,im['sha'])).fetchone()
        if origin:name=_basename(origin['filename'])
        else:
            with source.open('rb') as stream:head=stream.read(16)
            suffix='.png' if head.startswith(b'\x89PNG') else '.jpg' if head.startswith(b'\xff\xd8') else '.bmp' if head.startswith(b'BM') else '.gif' if head.startswith(b'GIF8') else '.webp' if head[:4]==b'RIFF' and head[8:12]==b'WEBP' else '.bin'
            name='image-'+str(im['position']+1)+suffix
        rel=old['path'] if old else base+'/originals/'+im['sha']+'-'+name
        measured=atomic_copy(source,relative_file(library.root,rel),im['sha'])
        if any(measured[k]!=im[k] for k in ('md5','sha1','bytes')):raise ValueError('카드 원본 이미지의 해시가 다릅니다.')
        c.execute('INSERT OR IGNORE INTO card_original_files VALUES(?,?,?,?,?,?)',(cid,'image',im['sha'],rel,name,measured['bytes']))


def storage_summary(library):
    from . import baseline
    with library.connect() as c:
        doc=c.execute("SELECT * FROM source_documents WHERE path='sources/PT.hwpx'").fetchone()
        count=c.execute('SELECT count(*) FROM card_original_files').fetchone()[0]
    file=library.root/'sources/PT.hwpx'
    ready=bool(doc and doc['sha256']==baseline.SOURCE_SHA and file.is_file() and file.stat().st_size==doc['bytes'])
    marker=library.root/'portable.json'
    return {'mode':'portable' if marker.is_file() else 'custom','data_path':str(library.root),
        'baseline_source_saved':ready,'new_card_original_files':count}


def audit_original_storage(library):
    """Full readback, without exporting filenames, raw text or absolute paths."""
    with library.connect() as c:
        docs=c.execute('SELECT path,sha256,bytes FROM source_documents').fetchall()
        originals=c.execute('SELECT card_id,kind,path,sha256,bytes FROM card_original_files').fetchall()
    result={'source_document_count':len(docs),'new_card_original_files':len(originals),'errors':[]}
    for kind,rows in (('base_document',docs),('card_original',originals)):
        for row in rows:
            try:
                actual=file_digest(relative_file(library.root,row['path']))
                if actual['sha256']!=row['sha256'] or actual['bytes']!=row['bytes']:raise ValueError('원본 보관 무결성 불일치')
            except (OSError,ValueError) as exc:
                result['errors'].append({'kind':kind,'sha256':row['sha256'],'type':type(exc).__name__})
    return result


def database_fingerprint(path):
    hashes={}
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as c:
        if c.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('이전 DB 무결성 검사 실패')
        if c.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('이전 DB 연결 무결성 검사 실패')
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in tables:
            quoted='"'+name.replace('"','""')+'"'
            columns=len(c.execute('PRAGMA table_info('+quoted+')').fetchall())
            rows=c.execute('SELECT * FROM '+quoted+' ORDER BY '+','.join(str(i+1) for i in range(columns))).fetchall()
            hashes[name]=hashlib.sha256(json.dumps(rows,ensure_ascii=False,default=lambda b:{'bytes':b.hex()}).encode()).hexdigest()
    return hashes


def _snapshot(source,dest):
    with sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as src,sqlite3.connect(dest,factory=ClosingConnection) as dst:
        src.backup(dst)


def data_identity(root):
    """Local instance identity without disclosing the user's absolute path."""
    return hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode('utf8')).hexdigest()


def process_alive(pid):
    """Read-only tri-state check: True / False / unknown (None).

    Windows os.kill(pid, 0) is NOT a liveness probe: it can terminate the process.
    Only wait on a process handle; never send a signal on Windows.
    """
    if type(pid) is not int or not 0<pid<=0xffffffff:return None
    if os.name=='nt':return _windows_process_alive(pid)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except (PermissionError,OSError):return None


def _windows_process_alive(pid):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x00100000,False,pid) # SYNCHRONIZE only
    if not handle:return False if ctypes.get_last_error()==87 else None
    try:
        result=kernel.WaitForSingleObject(handle,0)
        return False if result==0 else True if result==258 else None
    finally:kernel.CloseHandle(handle)


class LibraryInUseError(ValueError):
    def __init__(self,url):
        self.url=url
        super().__init__('이전 뽈프롬에서 앱 종료 후 다시 실행하세요. 기존 자료는 그대로 있습니다.\n'
            '응답 중인 뽈프롬 주소: '+url+'\n'
            '해당 화면의 [앱 종료]를 누르세요. 브라우저 창만 닫으면 프로그램이 남아 있을 수 있습니다.')


def _legacy_running(root):
    runtime=Path(root)/'runtime.json'
    if not runtime.is_file() or runtime.stat().st_size>4096:return False
    try:
        saved=json.loads(runtime.read_text(encoding='utf8'))
        if not isinstance(saved,dict):return None
        port=saved.get('port')
        if type(port) is not int or not 1<=port<=65535:return False
        con=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
        try:
            con.request('GET','/health');response=con.getresponse();d=json.loads(response.read(4096))
            if response.status!=200 or not isinstance(d,dict) or d.get('ok') is not True or d.get('approved_count')!=309:return None
            # New instances identify their data root. A different library at a
            # recycled port must not prevent migration of this one.
            if 'data_id' in d:
                if d['data_id']!=data_identity(root):return None
            # Pre-0.3.8 health has no data identity. A definitely dead saved PID
            # disproves ownership; unknown PID status never bypasses the guard.
            elif process_alive(saved.get('pid')) is False:return None
            return f'http://127.0.0.1:{port}/'
        finally:con.close()
    except (OSError,ValueError,http.client.HTTPException):return False


def verify_data(library,*,full_hash=True):
    """Verify fixed309, manual editions, and all DB-linked original assets."""
    from .baseline import load_dataset,BaselineStore
    from .baseline_edits import audit_editions
    records=load_dataset();store=BaselineStore(library,records)
    if audit_editions(library,records)['errors']:raise ValueError('사용자 태그 수정 이력 무결성 검사 실패')
    with library.connect() as c:
        media=c.execute('SELECT * FROM media').fetchall()
        docs=c.execute('SELECT * FROM source_documents').fetchall()
        originals=c.execute('SELECT * FROM card_original_files').fetchall()
    for row in media:
        path=relative_file(library.root,row['path'])
        if path.stat().st_size!=row['bytes']:raise ValueError('이미지 파일 크기가 기록과 다릅니다.')
        if full_hash and file_digest(path)!={'sha256':row['sha'],'md5':row['md5'],'sha1':row['sha1'],'bytes':row['bytes']}:raise ValueError('이전 이미지 파일의 해시가 다릅니다.')
    for row in list(docs)+list(originals):
        path=relative_file(library.root,row['path'])
        if path.stat().st_size!=row['bytes'] or (full_hash and file_digest(path)['sha256']!=row['sha256']):raise ValueError('보관 원본 파일의 해시가 다릅니다.')
    return {'fixed_cards':309,'linked_image_references':store.status()['linked_image_references'],'media_files':len(media),
        'source_documents':len(docs),'card_original_files':len(originals)}


def prepare_portable_data(root,legacy=None,progress=None):
    """Copy into sibling staging, verify, then rename; old data is untouched."""
    from .library import Library
    root=Path(root)
    if root.is_symlink() or getattr(root,'is_junction',lambda:False)():raise ValueError('data 폴더의 외부 연결은 사용하지 않습니다.')
    root=root.resolve();root.parent.mkdir(parents=True,exist_ok=True)
    callback=progress or (lambda *args:None)
    if (root/'library.sqlite3').is_file():
        library=Library(root)
        marker=root/'portable.json'
        if not marker.is_file():
            callback('기존 data 원본 파일을 확인하고 있습니다.',0,0)
            with library.connect() as c:
                for row in c.execute('SELECT id FROM cards').fetchall():sync_card_originals(library,c,row['id'])
            verify_data(library);atomic_bytes(marker,json.dumps({'schema':'bbolprom-portable-1','migrated_legacy':False}).encode())
        else:
            verify_data(library,full_hash=False)
        return root
    legacy=Path(legacy).resolve() if legacy else None
    if root.exists() and any(root.iterdir()):raise ValueError('data 폴더에 DB 없는 자료가 있습니다. 덮어쓰지 않으니 새 빈 폴더에서 실행하세요.')
    if not legacy or legacy==root or not (legacy/'library.sqlite3').is_file():
        root.mkdir(exist_ok=True);Library(root)
        atomic_bytes(root/'portable.json',json.dumps({'schema':'bbolprom-portable-1','migrated_legacy':False}).encode())
        return root
    running=_legacy_running(legacy)
    if running:raise LibraryInUseError(running)
    callback('기존 카드·수정 이력을 준비하고 있습니다.',0,0)
    databases=[n for n in ('library.sqlite3','api-safety.sqlite3') if (legacy/n).is_file()]
    fingerprints={name:database_fingerprint(legacy/name) for name in databases}
    files=[]
    for name in ('vault','new_cards','sources','backup','exports'):
        folder=legacy/name
        if folder.is_symlink():raise ValueError('자료 폴더의 외부 연결은 자동 복사하지 않습니다.')
        if not folder.exists():continue
        for file in sorted(folder.rglob('*')):
            if file.is_symlink():raise ValueError('자료 폴더의 외부 연결은 자동 복사하지 않습니다.')
            if file.is_file() and not file.name.startswith(('.copy-','.write-','pending-')):files.append(file)
    total=sum(f.stat().st_size for f in files)+sum((legacy/n).stat().st_size for n in databases)
    if shutil.disk_usage(root.parent).free<total+32*1024*1024:raise ValueError('data 복사에 필요한 저장 공간이 부족합니다. 기존 자료는 그대로 있습니다.')
    stage=Path(tempfile.mkdtemp(dir=root.parent,prefix='.bbolprom-data-copy-'))
    try:
        for name in databases:
            _snapshot(legacy/name,stage/name)
            if database_fingerprint(stage/name)!=fingerprints[name]:raise ValueError('DB 복사 검증에 실패했습니다.')
        done=0
        observed=[]
        for file in files:
            rel=file.relative_to(legacy)
            def copied(size):
                nonlocal done
                done+=size;callback('기존 원본·이미지·백업을 복사하고 있습니다.',done,total)
            atomic_copy(file,stage/rel,progress=copied)
            stat=file.stat();observed.append((file,stat.st_size,stat.st_mtime_ns))
        callback('복사된 원본과 309개 기준을 검증하고 있습니다.',total,total)
        library=Library(stage);verify_data(library)
        # Add readable originals for old operational cards, without re-tagging.
        with library.connect() as c:
            for row in c.execute('SELECT id FROM cards').fetchall():sync_card_originals(library,c,row['id'])
        counts=verify_data(library)
        for name in databases:
            if database_fingerprint(legacy/name)!=fingerprints[name]:raise ValueError('복사 중 이전 자료가 변경됐습니다. 이전 앱 종료 후 다시 실행하세요.')
        if any((f.stat().st_size,f.stat().st_mtime_ns)!=(size,mtime) for f,size,mtime in observed):raise ValueError('복사 중 이전 원본 파일이 변경됐습니다. 전환하지 않았습니다.')
        atomic_bytes(stage/'portable.json',json.dumps({'schema':'bbolprom-portable-1','migrated_legacy':True,'verified':counts},ensure_ascii=False,indent=2).encode())
        if root.exists():root.rmdir() # checked empty; never replace an existing library
        os.replace(stage,root)
        return root
    finally:
        if stage.exists():shutil.rmtree(stage)
