"""Local desktop backend. Bound to loopback only; no external transmission by default."""
from __future__ import annotations
import argparse, base64, hashlib, io, json, os, secrets, sys, tempfile
import threading, uuid, webbrowser, zipfile, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from .library import Library
from .analysis import analyze
from .hwpx import HWPXReader
from .tags import CATEGORIES
from .xlsx_export import export_xlsx
from .version import VERSION

APP_ROOT=Path(__file__).resolve().parent.parent

def image_mime(body):
    if body.startswith(b'\x89PNG'):return 'image/png'
    if body.startswith(b'\xff\xd8'):return 'image/jpeg'
    if body.startswith(b'GIF8'):return 'image/gif'
    if body.startswith(b'BM'):return 'image/bmp'
    if body[:4]==b'RIFF' and body[8:12]==b'WEBP':return 'image/webp'
    return 'application/octet-stream'

class ImportReviewError(ValueError):
    def __init__(self,message,review_card,approved_matches):
        super().__init__(message)
        self.details={'review_card':review_card,'unresolved_index':review_card,'approved_matches':approved_matches}

class Application:
    def __init__(self, data):
        self.library=Library(data)
        self.token=secrets.token_urlsafe(32)
        self.pending={}
        self.lock=threading.RLock()
        self.api_config=None
        self.approved=[]
        self.approved_hashes=set()
        from .baseline import BaselineStore, load_dataset
        self.baseline=BaselineStore(self.library,load_dataset(APP_ROOT))
        self.approved=self.baseline.cards()
        self.approved_hashes={c['source_text_sha256'] for c in self.approved}
        from .local_diagnostics import ImportAudit
        self.import_audit=ImportAudit(self.library)

    def categories(self):
        return self.library.get_setting('categories',[
            {'id':col,'name':name,'definition':'','enabled':True,'exclusions':[]}
            for col,name in CATEGORIES.items()])

    def all_cards(self):
        # Project current category state without rewriting a single approved byte.
        categories={c['id']:c for c in self.categories()}
        cards=self.baseline.cards()
        by_sha={}
        for c in cards:by_sha.setdefault(hashlib.sha256(c['source_text'].encode()).hexdigest(),[]).append(c)
        targets=self.library.get_setting('approved_overlay_targets',{})
        for c in self.library.cards():
            if c['sha'] in by_sha:
                # Additional images/provenance are a user-data overlay, never a master rewrite.
                matches=by_sha[c['sha']]
                approved=next((a for a in matches if a['id']==targets.get(c['sha'])),None)
                if approved is None and len(matches)==1:approved=matches[0]
                if approved is None:
                    c['analysis_status']='승인 동일원문 복수: 이미지 귀속 미선택';cards.append(c)
                else:
                    approved['images']+=c['images'];approved['origins']+=c['origins']
                    approved['overlay_id']=c['id']
            else:cards.append(c)
        history=self.library.get_setting('category_history',[])
        for card in cards:
            for tag in card['tags']:
                cid=tag.get('category_id',tag.get('category_column'))
                events=[h for h in history if h['category_id']==cid and h['operation'] in ('deactivate','reactivate_user_choice')]
                deactivated=bool(events and events[-1]['operation']=='deactivate') or bool(events and events[-1].get('restore_tags') is False)
                if card['approved'] and (deactivated or categories.get(cid,{}).get('enabled') is False):
                    tag['original_category_id']=cid
                    tag['category_id']=None;tag['category_column']=None
                    tag['category_status']='unclassified'
        return cards

    def state(self):
        from .ui import preferences
        config=self.library.get_setting('api',{})
        baseline=self.baseline.status()
        return {'cards':self.all_cards(),'categories':self.categories(),'api':config,'baseline':baseline,'ui':preferences(self.library),
                'api_key_present':bool(os.environ.get(config.get('key_env','BBOLPROM_API_KEY'))),
                'api_usage':self.api_config.public_settings() if self.api_config else {},
                'limitations':['309개는 확정 마스터에서 베이스화한 고정 데이터입니다. 독립 추출 성능이 아닙니다.',
                    '확정 PT 이미지 연결 '+str(baseline['linked_image_references'])+' / 531건. 원본을 선택해 연결할 수 있습니다.',
                    'API 기본 꺼짐. 사용자 확정 분류 정의와 API 설정 필요. 규칙 태그는 의미 판단 대체 불가']}

    def prepare(self, path, name):
        with HWPXReader(path) as reader:
            result=analyze(reader)
        result['file']['name']=name
        # Legacy rules remain diagnostic-only; do not register them as semantic conclusions.
        for c in result['cards']:
            c['diagnostic_rule_tags']=c['tags']
            c['tags']=[];c['review_candidates']=[];c['unclassified_tag_candidates']=[]
        ticket=uuid.uuid4().hex
        self.pending[ticket]=(Path(path),result)
        plan=self.library.plan(result)
        persisted_targets=self.library.get_setting('approved_overlay_targets',{})
        for card,row in zip(result['cards'],plan):
            if card['source_text_sha256'] in self.approved_hashes:
                row['action']='approved_card_image_source_overlay'
                card['approved_matches']=[{'id':a['id'],'card_id':a['card_id']} for a in self.approved if a['source_text']==card['source_text']]
                card['approved_target']=persisted_targets.get(card['source_text_sha256'])
        return {'ticket':ticket,'plan':plan,'cards':result['cards'],
                'stats':dict(result['result_stats'],tag_candidates=0,highlight_spans=0),'notice':'태그는 등록 후 명시적 API 분석으로 생성됩니다. 경계가 모호하면 등록 전 카드를 확인하세요.'}

    def prepare_baseline(self,path,name):
        from .local_diagnostics import safe_error
        name=Path(str(name).replace('\\','/')).name[:512]
        attempt=self.import_audit.begin(name,Path(path).stat().st_size)
        try:
            result=self.baseline.prepare(path,name,source_checked=lambda file:self.import_audit.update(attempt,'source_checked',file=file))
        except Exception as exc:
            self.import_audit.update(attempt,'failed',error=safe_error(exc))
            raise
        self.import_audit.update(attempt,'review_ready',stats=result['stats'],
            image_digests={im['path']:im['digest'] for card in result['cards'] for im in card['images']})
        result['attempt_id']=attempt
        ticket=uuid.uuid4().hex
        self.pending[ticket]=(Path(path),result)
        return dict(result,ticket=ticket)

    def validate_approved_target(self,text,chosen,targets):
        matches=[a['id'] for a in self.approved if a['source_text']==text]
        sha=hashlib.sha256(text.encode()).hexdigest()
        chosen=chosen or targets.get(sha)
        if chosen is not None and chosen not in matches:raise ValueError('선택한 승인 카드와 원문 불일치')
        if len(matches)>1 and chosen is None:
            raise ValueError('동일 원문 승인 카드가 여러 개입니다. 이미지·출처 귀속 대상을 선택하세요.')
        if matches:targets[sha]=chosen or matches[0]

    def action(self, route, data):
        if route=='/api/local-diagnostic':
            from .local_diagnostics import collect_local_diagnostic
            folder=self.library.root/'exports';folder.mkdir(exist_ok=True)
            path=folder/('Bbolprom-Local-'+uuid.uuid4().hex[:12]+'.diagnostic.zip')
            report=collect_local_diagnostic(self.baseline,path,data.get('ui_observation'))
            return {'download':'/download/exports/'+path.name,'file':path.name,'bytes':path.stat().st_size,
                'acceptance':report['acceptance'],'counts':report['counts'],
                'notice':'진단 ZIP에 원문·이미지·문서XML·DB·API키는 포함하지 않습니다. 자동 전송하지 않습니다.'}
        if route=='/api/ui':
            from .ui import save_preferences
            return {'ui':save_preferences(self.library,data)}
        if route=='/api/diagnostic':
            if data['ticket'] not in self.pending:raise ValueError('반입 검토 세션이 없습니다. 파일을 다시 선택하세요.')
            from .diagnostics import collect_structure
            source,result=self.pending[data['ticket']]
            folder=self.library.root/'exports';folder.mkdir(exist_ok=True)
            path=folder/(uuid.uuid4().hex[:12]+'.diagnostic.zip')
            report=collect_structure(source,result,path)
            return {'download':'/download/exports/'+path.name,'file':path.name,
                'source_sha256':report['source']['sha256'],
                'cards':report['extraction']['card_count'],'image_bytes_included':False,
                'notice':report['notice']}
        if route=='/api/cancel':
            entry=self.pending.pop(data['ticket'],None)
            if entry:
                if entry[1].get('attempt_id'):self.import_audit.update(entry[1]['attempt_id'],'cancelled')
                entry[0].unlink(missing_ok=True)
            return {'cancelled':True}
        if route=='/api/baseline-commit':
            if set(data)!={'ticket'}:raise ValueError('베이스화는 확정 카드의 편집 없이 검토 세션만 등록합니다.')
            ticket=data['ticket']
            if ticket not in self.pending:raise ValueError('검토 세션이 만료됨: 원본을 다시 선택하세요.')
            source,result=self.pending[ticket]
            try:status=self.baseline.commit(source,result)
            except Exception as exc:
                from .local_diagnostics import safe_error
                if result.get('attempt_id'):self.import_audit.update(result['attempt_id'],'commit_failed',error=safe_error(exc))
                raise
            if result.get('attempt_id'):self.import_audit.update(result['attempt_id'],'committed',result=status)
            del self.pending[ticket];source.unlink(missing_ok=True)
            return {'baseline':status,'message':'베이스화 309개 ID를 유지하고 531건의 이미지 참조를 연결했습니다.'}
        if route=='/api/commit':
            ticket=data['ticket']
            if ticket not in self.pending: raise ValueError('검토 세션이 만료됨: 재반입 필요')
            source,result=self.pending[ticket]
            if result.get('mode')=='fixed_master_baseline':raise ValueError('확정 베이스는 베이스화 등록 경로를 사용하세요.')
            # Review supports explicit per-card prompt/images. The source remains untouched.
            if 'cards' in data:
                original_images={(i['ref'],i['path']):i for c in result['cards'] for i in c['images']}
                revised=[]
                for n,c in enumerate(data['cards'],1):
                    text=c['source_text'];images=[]
                    for im in c['images']:
                        key=(im['ref'],im['path'])
                        if key not in original_images: raise ValueError('검토 이미지 참조가 원본에 없음')
                        images.append(original_images[key])
                    revised.append(dict(engine_card=n,source_text=text,source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                        images=images,tags=[],warnings=['사용자 반입 검토 수정']))
                result=dict(result,cards=revised)
            targets=self.library.get_setting('approved_overlay_targets',{})
            for card in result['cards']:
                chosen=data.get('approved_targets',{}).get(str(card['engine_card']))
                try:self.validate_approved_target(card['source_text'],chosen,targets)
                except ValueError as exc:
                    matches=[{'id':a['id'],'card_id':a['card_id']} for a in self.approved if a['source_text']==card['source_text']]
                    raise ImportReviewError(str(exc),card['engine_card'],matches) from None
            ids=self.library.commit_hwpx(source,result)
            self.library.set_setting('approved_overlay_targets',targets)
            del self.pending[ticket];source.unlink(missing_ok=True)
            return {'ids':ids,'message':'등록됨. 중복 원문은 병합하고 모든 출처를 보존했습니다.'}
        if route=='/api/manual':
            images=[]
            for im in data.get('images',[]):
                images.append((str(im['name']),io.BytesIO(base64.b64decode(im['base64'],validate=True))))
            targets=self.library.get_setting('approved_overlay_targets',{})
            self.validate_approved_target(data['text'],data.get('approved_target'),targets)
            origin=data.get('origin_filename','직접 등록')
            if not isinstance(origin,str) or not origin.strip() or len(origin)>512:raise ValueError('출처 파일명 확인 필요')
            cid=self.library.manual(data['text'],images,filename=origin)
            self.library.set_setting('approved_overlay_targets',targets)
            return {'id':cid}
        if route in ('/api/card-edit','/api/card-history','/api/card-restore'):
            card=next((c for c in self.library.cards() if c['id']==data['id']),None)
            if card is None or card['sha'] in self.approved_hashes:raise ValueError('사용자 신규 카드만 수정·복원할 수 있습니다. 승인 기준은 읽기 전용입니다.')
            if route=='/api/card-history':return {'versions':self.library.card_history(card['id'])}
            if route=='/api/card-restore':
                self.library.restore_card(card['id'],data['version_id']);return {'message':'이전 원문·태그·이미지 연결을 복원했습니다. 출처 이력은 유지합니다.'}
            if hashlib.sha256(data['text'].encode()).hexdigest() in self.approved_hashes:raise ValueError('승인 원문으로 변경해 기준 카드를 대체할 수 없습니다.')
            images=[(str(im['name']),io.BytesIO(base64.b64decode(im['base64'],validate=True))) for im in data.get('images',[])]
            self.library.edit_card(card['id'],data['text'],images,data.get('remove_images',[]),data.get('expected_sha'))
            return {'message':'카드 수정 저장. 이전 원문·연결·태그는 수정 이력에 보존했습니다.'}
        if route=='/api/shutdown':
            return {'shutdown':True}
        if route=='/api/backup':
            p=self.library.backup();return {'file':p.name,'download':'/download/backup/'+p.name}
        if route=='/api/export':
            folder=self.library.root/'exports';folder.mkdir(exist_ok=True)
            p=folder/(uuid.uuid4().hex[:12]+'.xlsx')
            export_xlsx(self.all_cards(),p)
            return {'download':'/download/exports/'+p.name}
        if route=='/api/settings':
            config=data['api']
            # No credentials in config: key must exist as a process environment binding.
            allowed={'enabled','consent','endpoint','model','key_env','timeout','max_calls','max_output_tokens','max_cost_usd','input_usd_per_million','output_usd_per_million','use_approved_examples'}
            if set(config)-allowed: raise ValueError('지원하지 않는 API 설정 필드')
            from .api import APIConfig
            if 'use_approved_examples' in config and type(config['use_approved_examples']) is not bool:raise ValueError('승인 사례 참조 설정은 true/false여야 합니다')
            APIConfig(**{k:v for k,v in config.items() if k!='use_approved_examples'}) # live calls only on /analyze
            self.library.set_setting('api',config);self.api_config=None
            return {'message':'API 설정 저장됨. 키 값은 저장하지 않습니다.'}
        if route=='/api/categories':
            from .categories import CategoryManager
            tags=[dict(t,_card_id=c['id']) for c in self.library.cards() for t in c['tags']]
            manager=CategoryManager(self.categories(),tags,self.library.get_setting('category_history',[]))
            op=data['operation'];cid=data['id']
            if op=='rename': manager.rename(cid,data['name'])
            elif op=='define': manager.define(cid,data['definition'],user_confirmed=True)
            elif op=='deactivate': manager.deactivate(cid)
            elif op=='reactivate': manager.reactivate(cid,restore_tags=data.get('restore_tags'))
            elif op=='add': manager.add(data['category'],user_confirmed=True)
            else: raise ValueError('알 수 없는 분류 작업')
            snap=manager.snapshot()
            self.library.backup()
            self.library.set_setting('categories',snap['categories'])
            self.library.set_setting('category_history',snap['history'])
            # Approved read-only catalogue is never rewritten. User-library tag affiliation follows deactivation policy.
            grouped={}
            for t in snap['tags']:
                t=dict(t);owner=t.pop('_card_id');grouped.setdefault(owner,[]).append(t)
            with self.library.connect() as c:
                for owner,ts in grouped.items():
                    c.execute('UPDATE cards SET tags=? WHERE id=?',(json.dumps(ts,ensure_ascii=False),owner))
            return {'message':'사용자 분류 설정을 저장했습니다. 승인 원본 파일은 불변입니다.'}
        if route=='/api/tags':
            card=next((c for c in self.library.cards() if c['id']==data['id']),None)
            if card is None or card['sha'] in self.approved_hashes:raise ValueError('승인 카드 태그 수정 금지')
            from .api import evidence_spans
            active={c['id'] for c in self.categories() if c.get('enabled',True)}
            tags=[];seen=set()
            for raw in data['tags']:
                name=raw['name'].strip();cat=raw.get('category_id')
                if not name or name in seen:raise ValueError('빈 태그/동일 태그 중복')
                if cat is not None and cat not in active:raise ValueError('활성 분류만 선택할 수 있습니다')
                seen.add(name)
                quote=raw.get('evidence','')
                if quote and quote not in card['source_text']:raise ValueError('근거 구절이 실제 원문에 없습니다')
                tags.append({'name':name,'tag':name,'category_id':cat,'category_column':cat,
                    'category_status':'classified' if cat else 'unclassified',
                    'spans':raw.get('original_spans',evidence_spans(card['source_text'],[quote])),'source':'user_edit','reason':'사용자 직접 수정'})
            self.library.backup()
            self.library.save_analysis(card['id'],{'source_text':card['source_text'],'tags':tags,'status':'user_edited'})
            return {'message':'신규 카드 태그를 저장했습니다. 원문은 불변입니다.'}
        if route=='/api/analyze':
            from .api import APIConfig,analyze_card
            card=next((c for c in self.library.cards() if c['id']==data['id']),None)
            if card is None or card.get('sha') in self.approved_hashes: raise ValueError('신규 등록 카드만 분석 가능합니다. 승인 카드 재분석 금지')
            config=self.library.get_setting('api',{})
            if not config.get('enabled') or not config.get('consent'):
                raise ValueError('외부 전송 동의와 API 활성화가 필요합니다')
            if self.api_config is None:self.api_config=APIConfig(**{k:v for k,v in config.items() if k!='use_approved_examples'})
            from .approved_context import load_approved_context
            context=load_approved_context()
            standards={t['id']:t for t in context['standards']}
            for c in self.library.cards():
                for t in c['tags']:
                    name=t.get('tag',t.get('name',''));cat=t.get('category_id',t.get('category_column'))
                    existing=next((x for x in standards.values() if x['name']==name and x.get('category_id')==cat),None)
                    if existing:continue
                    key='tag-'+hashlib.sha256((str(cat)+'\0'+name).encode()).hexdigest()[:20]
                    standards[key]={'id':key,'name':name,'category_id':cat}
            from .approved_examples import retrieve_approved_examples
            examples=retrieve_approved_examples(card['source_text'],enabled=config.get('use_approved_examples',False))
            from .approval_history import load_approval_history
            history=load_approval_history()
            from .method_guidance import load_method_guidance
            method=load_method_guidance()
            result=analyze_card(card['id'],card['source_text'],self.categories(),list(standards.values()),context,config=self.api_config,examples=examples,approval_history=history,method_guidance=method)
            if result['status'] in ('ok','partial'):
                self.library.backup();self.library.save_analysis(card['id'],result)
            else:self.library.record_analysis_audit(card['id'],result)
            return result
        raise ValueError('지원하지 않는 작업')


def make_server(data,port=0):
    app=Application(data)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass # no prompts, credentials, URLs in access logs
        def send(self,status,body,mime='application/json; charset=utf-8'):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(body)
        def authorized(self):
            host=self.headers.get('Host','')
            if host!=f'127.0.0.1:{self.server.server_port}': return False
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+host: return False
            return self.headers.get('X-Bbolprom-Token')==app.token
        def do_GET(self):
            path=urlsplit(self.path).path
            try:
                if path=='/':
                    page=(Path(__file__).parent/'web'/'index.html').read_text(encoding='utf8')
                    self.send(200,page.replace('__TOKEN__',app.token).replace('__VERSION__',VERSION).encode(),'text/html; charset=utf-8');return
                if path in ('/ui.css','/app.js'):
                    body=(Path(__file__).parent/'web'/path[1:]).read_bytes()
                    self.send(200,body,'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8');return
                if path=='/health':self.send(200,{'ok':True,'version':VERSION,'approved_count':len(app.approved)});return
                if path=='/api/state':
                    if not self.authorized(): self.send(403,{'error':'세션 인증 실패'});return
                    self.send(200,app.state());return
                if path.startswith('/pending-media/'):
                    parts=path.split('/')
                    if len(parts)!=4 or parts[2] not in app.pending:raise ValueError('검토 이미지 없음')
                    source,result=app.pending[parts[2]]
                    refs=[i for c in result['cards'] for i in c['images']]
                    ix=int(parts[3])
                    if not 0<=ix<len(refs):raise ValueError('검토 이미지 없음')
                    with zipfile.ZipFile(source) as archive:body=archive.read(refs[ix]['path'])
                    self.send(200,body,image_mime(body));return
                if path.startswith('/media/'):
                    sha=path.removeprefix('/media/')
                    if len(sha)!=64 or any(ch not in '0123456789abcdef' for ch in sha):raise ValueError('잘못된 이미지 ID')
                    p=app.library.root/'vault'/sha
                    body=p.read_bytes()
                    self.send(200,body,image_mime(body));return
                if path.startswith('/download/'):
                    # Downloads carry only user-selected export/backup files, never arbitrary filesystem paths.
                    parts=path.split('/')
                    if len(parts)!=4 or parts[2] not in ('backup','exports') or Path(parts[3]).name!=parts[3]:raise ValueError('잘못된 다운로드')
                    p=app.library.root/parts[2]/parts[3]
                    self.send(200,p.read_bytes(),'application/octet-stream');return
                self.send(404,{'error':'없음'})
            except (OSError,ValueError,KeyError) as exc:self.send(400,{'error':str(exc)})
        def do_POST(self):
            if not self.authorized():self.send(403,{'error':'세션 인증 실패'});return
            path=urlsplit(self.path).path
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>2*1024**3:raise ValueError('파일 크기 제한 2GB')
                with app.lock:
                    if path in ('/api/upload','/api/baseline-upload'):
                        name=unquote(self.headers.get('X-Filename','import.hwpx'))
                        if not name.lower().endswith('.hwpx'):raise ValueError('HWPX 파일이 필요합니다')
                        pending=app.library.root/'pending';pending.mkdir(exist_ok=True)
                        source=pending/(uuid.uuid4().hex[:12]+'.hwpx')
                        try:
                            with source.open('wb') as f:
                                remain=length
                                while remain:
                                    block=self.rfile.read(min(remain,1024*1024))
                                    if not block:raise ValueError('업로드가 중단됨')
                                    f.write(block);remain-=len(block)
                            prepare=app.prepare_baseline if path=='/api/baseline-upload' else app.prepare
                            result=prepare(source,Path(name.replace('\\','/')).name)
                        except Exception:
                            source.unlink(missing_ok=True);raise
                    else:
                        if length>64*1024**2:raise ValueError('요청 크기 제한 64MB')
                        result=app.action(path,json.loads(self.rfile.read(length)))
                self.send(200,result)
                if path=='/api/shutdown':threading.Thread(target=self.server.shutdown,daemon=True).start()
            except Exception as exc:
                # API exceptions are sanitized inside api.py; never echo credential/header values.
                self.send(400,dict(error=str(exc) if isinstance(exc,(ValueError,KeyError,OSError)) else type(exc).__name__,**getattr(exc,'details',{})))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    server.application=app
    return server


def main(argv=None):
    parser=argparse.ArgumentParser(description='뽈프롬 데스크톱')
    parser.add_argument('--data',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Bbolprom')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args(argv)
    if args.self_test:
        import urllib.request
        with tempfile.TemporaryDirectory() as d:
            server=make_server(d)
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                result=json.load(urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/health'))
                if not result['ok']:raise RuntimeError('health failed')
            finally:server.shutdown();server.server_close();t.join()
        return 0
    args.data.mkdir(parents=True,exist_ok=True)
    try:
        server=make_server(args.data,args.port)
        url=f'http://127.0.0.1:{server.server_port}/'
        (args.data/'runtime.json').write_text(json.dumps({'port':server.server_port,'pid':os.getpid()}))
        if not args.no_browser:webbrowser.open(url)
        if sys.stdout:print('뽈프롬 시작:',url,flush=True)
        server.serve_forever()
    except KeyboardInterrupt:return 0
    except Exception:
        (args.data/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
        raise
    finally:
        if 'server' in locals():server.server_close()
    return 0

if __name__=='__main__':raise SystemExit(main())
