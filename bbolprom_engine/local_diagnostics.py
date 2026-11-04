"""Small local support evidence; never includes prompts, media, DB or credentials.

Fixed-baseline integrity is distinct from independent segmentation or visual
image/prompt judgement. Source attempts survive failure, cancellation and commit.
"""
from __future__ import annotations
import hashlib
import json
import platform
import sys
import uuid
import zipfile
from pathlib import Path

from . import baseline
from .library import _now
from .version import VERSION

SCHEMA='bbolprom-local-diagnostic-1'
MAX_ATTEMPTS=20


def safe_error(error):
    # No traceback, credential-bearing HTTP body, arbitrary OS path or headers.
    result={'type':type(error).__name__}
    if isinstance(error,ValueError):result['message']=str(error)[:1000]
    elif isinstance(error,OSError):result['errno']=error.errno
    return result


class ImportAudit:
    def __init__(self,library):self.library=library

    def begin(self,name,byte_count=None):
        ident=uuid.uuid4().hex;now=_now()
        name=Path(str(name).replace('\\','/')).name[:512]
        details={'events':[{'at':now,'status':'started'}]}
        if byte_count is not None:details['file']={'name':name,'bytes':byte_count}
        with self.library.connect() as c:
            c.execute('INSERT INTO import_attempts VALUES(?,?,?,?,?,?,?)',
                      (ident,now,now,baseline.MODE,'started',name,json.dumps(details,ensure_ascii=False)))
        return ident

    def update(self,ident,status,**values):
        now=_now()
        with self.library.connect() as c:
            row=c.execute('SELECT details_json FROM import_attempts WHERE id=?',(ident,)).fetchone()
            if row is None:raise ValueError('반입 진단 이력이 없습니다')
            details=json.loads(row[0]);details.update(values)
            details['events'].append({'at':now,'status':status})
            c.execute('UPDATE import_attempts SET updated=?,status=?,details_json=? WHERE id=?',
                      (now,status,json.dumps(details,ensure_ascii=False),ident))

    def recent(self):
        with self.library.connect() as c:
            total=c.execute('SELECT COUNT(*) FROM import_attempts').fetchone()[0]
            rows=[]
            for row in c.execute('SELECT * FROM import_attempts ORDER BY created DESC LIMIT ?',(MAX_ATTEMPTS,)):
                item=dict(row);item['details']=json.loads(item.pop('details_json'));rows.append(item)
        return total,rows


def _digest(path):
    hashes={k:hashlib.new(k) for k in ('md5','sha1','sha256')};size=0
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):
            size+=len(block)
            for h in hashes.values():h.update(block)
    return dict(bytes=size,**{k:h.hexdigest() for k,h in hashes.items()})


def _build_info():
    package=Path(__file__).resolve().parents[2]
    result={'version':VERSION,'source_commit':None,'packaged':False}
    provenance=package/'BUILD_PROVENANCE.json'
    if provenance.is_file():
        data=json.loads(provenance.read_text(encoding='utf8'))
        result.update(source_commit=data.get('application_source_commit'),packaged=True,
                      cross_built=bool(data.get('cross_built')))
    return result


def _ui_snapshot(value):
    if not isinstance(value,dict):return {}
    out={}
    for key in ('displayed_cards','rendered_images','loaded_images','failed_images','selected_tag_count','applied_tag_count'):
        n=value.get(key)
        if type(n) is int and 0<=n<=100000:out[key]=n
    for key in ('filter_active','show_hidden'):
        if type(value.get(key)) is bool:out[key]=value[key]
    if value.get('scope') in ('all','approved','new'):out['scope']=value['scope']
    return out


def collect_local_diagnostic(store,destination,ui_snapshot=None):
    library=store.library;destination=Path(destination)
    if destination.exists():raise FileExistsError('진단 파일은 새 파일로 저장합니다')
    status=store.status();total,attempts=ImportAudit(library).recent()
    with library.connect() as c:
        db_check=[r[0] for r in c.execute('PRAGMA quick_check')]
        foreign_keys=[list(r) for r in c.execute('PRAGMA foreign_key_check')]
        rows=[dict(r) for r in c.execute('SELECT * FROM baseline_cards ORDER BY card_id')]
        links=[dict(r) for r in c.execute('''SELECT b.*,m.md5,m.sha1,m.bytes,m.path
                 FROM baseline_image_links b LEFT JOIN media m ON m.sha=b.media_sha
                 ORDER BY b.card_id,b.position''')]
        sources=[dict(r) for r in c.execute('SELECT * FROM baseline_sources ORDER BY imported')]
        # Limit auxiliary data to counts, never settings, endpoint URLs or text.
        user_card_count=c.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    expected={r['card_id']:r for r in store.records}
    cards=[];immutable_errors=[];invalid_spans=[]
    for row in rows:
        record=json.loads(row['record_json']);cid=row['card_id']
        exact=record==expected.get(cid)
        if not exact:immutable_errors.append(cid)
        text=record['source_text'];tag_count=len(record['tags']);spans=0;empty=0
        for ti,tag in enumerate(record['tags']):
            if not tag.get('spans'):empty+=1
            for si,s in enumerate(tag.get('spans',[])):
                spans+=1;a,b=s.get('start_cp'),s.get('end_cp')
                if type(a) is not int or type(b) is not int or not 0<=a<b<=len(text) or text[a:b]!=s.get('evidence'):
                    invalid_spans.append({'card_id':cid,'tag_index':ti,'span_index':si})
        cards.append({'card_id':cid,'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                      'source_chars':len(text),'tag_count':tag_count,'span_count':spans,'zero_span_tags':empty,
                      'approved_record_sha256':hashlib.sha256(row['record_json'].encode()).hexdigest(),
                      'matches_fixed_reference':exact,'images':[]})
    by_card={c['card_id']:c for c in cards}
    media={};media_errors=[];identity_errors=[]
    for link in links:
        cid=link['card_id'];position=link['position'];source_path=link['source_path'];sha=link['media_sha']
        reference=expected.get(cid,{}).get('expected_images',[])
        identity=(0<=position<len(reference) and reference[position]=={'ref':link['ref'],'path':source_path})
        if not identity:identity_errors.append({'card_id':cid,'position':position})
        image={'position':position,'ref':link['ref'],'source_path':source_path,'media_sha256':sha,
               'matches_reference_identity':identity}
        if sha and sha not in media:
            entry={'stored':{'sha256':sha,'md5':link['md5'],'sha1':link['sha1'],'bytes':link['bytes']}}
            path=library.root/'vault'/sha
            try:
                # Address by validated SHA rather than trusting an arbitrary DB path.
                if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('저장 이미지 SHA 형식 오류')
                measured=_digest(path)
                entry.update(present=True,measured=measured,hashes_match=measured==entry['stored'])
                if not entry['hashes_match']:media_errors.append({'sha256':sha,'reason':'stored_media_hash_mismatch'})
            except (OSError,ValueError) as exc:
                entry.update(present=False,hashes_match=False,error=safe_error(exc));media_errors.append({'sha256':sha,'reason':'missing_or_unreadable'})
            media[sha]=entry
        if cid in by_card:by_card[cid]['images'].append(image)
    # Prepared hashes were measured from the selected HWPX, independently of
    # stored media readback. Use only evidence matching the committed source.
    prepared={}
    for attempt in attempts:
        d=attempt['details'];file=d.get('file',{})
        if file.get('sha256')==baseline.SOURCE_SHA and d.get('image_digests'):
            prepared=d['image_digests'];break
    for card in cards:
        for im in card['images']:
            source_digest=prepared.get(im['source_path'])
            im['source_digest_available']=source_digest is not None
            if source_digest is not None:
                im['source_digest']=source_digest
                if im['media_sha256']:
                    im['source_matches_stored_media']=source_digest==media.get(im['media_sha256'],{}).get('measured')
                    if not im['source_matches_stored_media']:
                        media_errors.append({'card_id':card['card_id'],'position':im['position'],'reason':'source_to_store_mismatch'})
    counts={'fixed_cards':len(cards),'unique_prompt_hashes':len({c['source_text_sha256'] for c in cards}),
            'tag_mappings':sum(c['tag_count'] for c in cards),'spans':sum(c['span_count'] for c in cards),
            'approved_zero_span_tags':sum(c['zero_span_tags'] for c in cards),'image_references':len(links),
            'unique_source_paths':len({l['source_path'] for l in links}),
            'linked_image_references':sum(l['media_sha'] is not None for l in links),
            'unique_stored_media':len(media),'user_cards':user_card_count}
    expected_counts={'fixed_cards':309,'unique_prompt_hashes':296,'tag_mappings':8471,'spans':10358,
                     'approved_zero_span_tags':17,'image_references':531,'unique_source_paths':522}
    count_match=all(counts.get(k)==v for k,v in expected_counts.items())
    source_ok=bool(sources) and all(s['source_sha']==baseline.SOURCE_SHA for s in sources)
    clean=(count_match and not immutable_errors and not invalid_spans and not identity_errors and
           not media_errors and db_check==['ok'] and not foreign_keys)
    acceptance='not_imported'
    if sources:
        acceptance='failed_integrity'
        if clean and source_ok and counts['linked_image_references']==531:
            acceptance='passed_integrity' if prepared else 'passed_storage_integrity_source_comparison_unavailable'
    report={'schema':SCHEMA,'created_utc':_now(),'application':_build_info(),
            'runtime':{'os':platform.system(),'os_release':platform.release(),'architecture':platform.machine(),
                       'python':platform.python_version(),'sys_platform':sys.platform},
            'mode':baseline.MODE,'is_independent_segmentation_test':False,
            'reference':{'master_sha256':baseline.MASTER_SHA,'manifest_sha256':baseline.MANIFEST_SHA,
                         'catalog_sha256':baseline.CATALOG_SHA,'expected_PT_sha256':baseline.SOURCE_SHA},
            'baseline_status':status,'counts':counts,'expected_counts':expected_counts,'counts_match':count_match,
            'acceptance':acceptance,'committed_sources':sources,'cards':cards,'media':media,
            'integrity':{'sqlite_quick_check':db_check,'foreign_key_errors':foreign_keys,
                         'immutable_card_errors':immutable_errors,'invalid_spans':invalid_spans,
                         'image_identity_errors':identity_errors,'media_errors':media_errors,
                         'source_image_hashes_available':bool(prepared)},
            'import_attempts':attempts,'total_import_attempts':total,'attempt_limit':MAX_ATTEMPTS,
            'attempts_truncated':total>len(attempts),
            'ui_observation':_ui_snapshot(ui_snapshot),
            'disclosure':{'prompt_text_included':False,'image_bytes_included':False,'document_XML_included':False,
                          'database_included':False,'API_keys_or_settings_included':False,'auto_uploaded':False},
            'limits':['Source image/prompt semantic correspondence is not visually judged.',
                      'Hashes are local runtime observations, not a live API quality evaluation.',
                      'Runtime OS is reported by the user machine; this export is not a complete native UI acceptance test.']}
    summary=('뽈프롬 로컬 반입 진단\n'
             f'버전: {VERSION}\n상태: {acceptance}\n'
             f'기준카드: {counts["fixed_cards"]} / 309\n'
             f'연결된 이미지 참조: {counts["linked_image_references"]} / 531\n'
             f'원본 이미지 경로: {counts["unique_source_paths"]} / 522\n'
             f'저장 이미지 해시/연결 오류: {len(media_errors)}\n'
             f'최근 반입 이력: {len(attempts)} / {total}\n'
             '원문·이미지·문서XML·DB·API키는 포함하지 않습니다. 자동 전송하지 않습니다.\n'
             '고정 마스터 베이스화의 무결성 진단이며 카드 독립 분리나 이미지 의미 판정 결과가 아닙니다.\n')
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            z.writestr('report.json',json.dumps(report,ensure_ascii=False,indent=2))
            z.writestr('SUMMARY.txt',summary)
    except Exception:
        destination.unlink(missing_ok=True);raise
    return report
