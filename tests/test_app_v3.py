"""Real HTTP requests to a short-lived loopback application, no remote API calls.
In managed sandboxes socket permission is required to execute these tests.
"""
import base64
import copy
from collections import Counter
import hashlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET
from bbolprom_engine.app import make_server, APP_ROOT
from test_library_v3 import source_file


class LocalHTTPApplication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.server=make_server(self.root/'library')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.app=self.server.application
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self,method,path,data=None,*,raw=None,headers=None,authorized=True):
        hs={}
        if authorized:hs['X-Bbolprom-Token']=self.app.token
        body=raw
        if data is not None:body=json.dumps(data,ensure_ascii=False).encode();hs['Content-Type']='application/json'
        if body is not None:hs['Content-Length']=str(len(body))
        hs.update(headers or {})
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=15)
        try:
            con.request(method,path,body=body,headers=hs)
            response=con.getresponse();payload=response.read();mime=response.getheader('Content-Type','')
            return response.status,json.loads(payload) if 'application/json' in mime else payload,mime
        finally:con.close()

    def user_cards(self):
        status,state,_=self.request('GET','/api/state');self.assertEqual(status,200)
        return [c for c in state['cards'] if not c['approved']]

    def test_gallery_page_and_state_and_approved_analyze_protection(self):
        status,body,mime=self.request('GET','/',authorized=False)
        self.assertEqual(status,200);self.assertIn('text/html',mime)
        self.assertNotIn(b'__TOKEN__',body);self.assertIn(self.app.token.encode(),body)
        status,health,_=self.request('GET','/health',authorized=False)
        self.assertEqual(status,200);self.assertTrue(health['ok']);self.assertEqual(health['approved_count'],309)
        status,state,_=self.request('GET','/api/state')
        self.assertEqual(status,200);self.assertEqual(len(state['cards']),309)
        self.assertTrue(all(c['approved'] for c in state['cards']))
        status,error,_=self.request('POST','/api/analyze',{'id':'approved-1'})
        self.assertEqual(status,400);self.assertIn('신규 등록',error['error'])
        self.assertEqual(self.user_cards(),[])

    def test_session_cross_origin_and_rebinding_requests_cannot_mutate(self):
        self.assertEqual(self.request('GET','/api/state',authorized=False)[0],403)
        self.assertEqual(self.request('GET','/api/state',headers={'Origin':'https://unrelated.invalid'})[0],403)
        self.assertEqual(self.request('GET','/api/state',headers={'Host':'unrelated.invalid'})[0],403)
        payload={'text':'등록되면 안 됨','images':[]}
        self.assertEqual(self.request('POST','/api/manual',payload,authorized=False)[0],403)
        self.assertEqual(self.request('POST','/api/manual',payload,headers={'Origin':'https://unrelated.invalid'})[0],403)
        self.assertEqual(self.user_cards(),[])

    def test_manual_register_preserves_raw_text_images_and_duplicate_origins(self):
        text='  😀 원문\n공백  ';first_bytes=b'\x89PNG\r\n\x1a\nfirst-original'
        first_image={'name':'첫 이미지.png','base64':base64.b64encode(first_bytes).decode()}
        status,result,_=self.request('POST','/api/manual',{'text':text,'images':[first_image]})
        self.assertEqual(status,200);cid=result['id']
        second={'name':'같은원문다른이미지.png','base64':base64.b64encode(b'\xff\xd8second-original').decode()}
        status,result,_=self.request('POST','/api/manual',{'text':text,'images':[second,first_image]})
        self.assertEqual(status,200);self.assertEqual(result['id'],cid)
        cards=self.user_cards();self.assertEqual(len(cards),1);card=cards[0]
        self.assertEqual(card['source_text'],text)
        self.assertEqual(card['sha'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(len(card['images']),2);self.assertEqual(len(card['origins']),3)
        first=next(i for i in card['images'] if i['sha']==hashlib.sha256(first_bytes).hexdigest())
        status,image,mime=self.request('GET','/media/'+first['sha'])
        self.assertEqual(status,200);self.assertEqual(image,first_bytes);self.assertEqual(mime,'image/png')
        status,err,_=self.request('POST','/api/analyze',{'id':cid})
        self.assertEqual(status,400);self.assertIn('동의',err['error'])
        self.assertEqual(self.user_cards()[0]['tags'],[])
        self.assertEqual(self.user_cards()[0]['source_text'],text)

    def test_hwpx_upload_review_commit_repeat_import_and_long_original_filename(self):
        source=source_file(self.root/'source.hwpx',['두 문단이 아닌 단일 원문입니다.'],[b'original-picture'])
        payload=source.read_bytes();filename='긴원본파일명_'+'가'*100+'.hwpx'
        status,review,_=self.request('POST','/api/upload',raw=payload,headers={'X-Filename':quote(filename)})
        self.assertEqual(status,200);self.assertEqual(len(review['cards']),1)
        self.assertEqual(review['plan'][0]['action'],'new_card');self.assertEqual(self.user_cards(),[])
        self.assertEqual(review['cards'][0]['tags'],[])
        self.assertEqual(review['stats']['tag_candidates'],0);self.assertEqual(review['stats']['highlight_spans'],0)
        status,committed,_=self.request('POST','/api/commit',{'ticket':review['ticket']})
        self.assertEqual(status,200);self.assertEqual(len(committed['ids']),1)
        card=self.user_cards()[0];self.assertEqual(card['origins'][0]['filename'],filename)
        self.assertEqual(len(card['images']),1)
        status,review2,_=self.request('POST','/api/upload',raw=payload,headers={'X-Filename':'renamed.hwpx'})
        self.assertEqual(status,200);self.assertEqual(review2['plan'][0]['action'],'skip_identical')
        status,result,_=self.request('POST','/api/commit',{'ticket':review2['ticket']})
        self.assertEqual(status,200);self.assertEqual(result['ids'],committed['ids'])
        card=self.user_cards()[0];self.assertEqual(len(card['images']),1);self.assertEqual(len(card['origins']),2)
        self.assertEqual(list((self.app.library.root/'pending').glob('*')),[])
        status,error,_=self.request('POST','/api/commit',{'ticket':review['ticket']})
        self.assertEqual(status,400)

    def test_failed_upload_and_invalid_review_do_not_register_cards(self):
        self.assertEqual(self.request('POST','/api/upload',raw=b'not-a-zip',headers={'X-Filename':'broken.hwpx'})[0],400)
        self.assertEqual(self.user_cards(),[])
        self.assertEqual(list((self.app.library.root/'pending').glob('*')),[])
        source=source_file(self.root/'source.hwpx',['검토 이미지 원문'],[b'image'])
        status,review,_=self.request('POST','/api/upload',raw=source.read_bytes(),headers={'X-Filename':'ok.hwpx'})
        self.assertEqual(status,200)
        revised=[{'source_text':'검토 이미지 원문','images':[{'ref':'missing','path':'BinData/missing.png'}]}]
        status,error,_=self.request('POST','/api/commit',{'ticket':review['ticket'],'cards':revised})
        self.assertEqual(status,400);self.assertEqual(self.user_cards(),[])

    def test_backup_and_xlsx_download_contain_real_persisted_content(self):
        text='내보낼 😀 원문'
        status,result,_=self.request('POST','/api/manual',{'text':text,'images':[{'name':'one.png','base64':base64.b64encode(b'bytes-for-backup').decode()}]})
        self.assertEqual(status,200)
        status,backup,_=self.request('POST','/api/backup',{})
        self.assertEqual(status,200)
        status,payload,_=self.request('GET',backup['download']);self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            self.assertIsNone(z.testzip());self.assertIn('library.sqlite3',z.namelist())
            vault=[n for n in z.namelist() if n.startswith('vault/')]
            self.assertEqual(len(vault),1);self.assertEqual(z.read(vault[0]),b'bytes-for-backup')
        status,export,_=self.request('POST','/api/export',{})
        self.assertEqual(status,200)
        status,payload,_=self.request('GET',export['download']);self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            self.assertIsNone(z.testzip())
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual(len(sheet.findall('x:sheetData/x:row',ns)),311)
            self.assertIn(text,''.join(sheet.itertext()))
        self.assertEqual(self.request('GET','/download/exports/../../library.sqlite3')[0],400)

    def test_category_deactivation_preserves_approved_tags_and_catalog(self):
        catalog=APP_ROOT/'assets/approved_catalog.json';before=catalog.read_bytes()
        original=[copy.deepcopy(c['tags']) for c in self.app.all_cards()]
        status,_,_=self.request('POST','/api/categories',{'operation':'deactivate','id':'F'})
        self.assertEqual(status,200)
        status,state,_=self.request('GET','/api/state');self.assertEqual(status,200)
        self.assertEqual([c['tags'] for c in state['cards']],original)
        self.assertEqual(catalog.read_bytes(),before)
        self.assertTrue(self.app.library.get_setting('category_history'))

    def test_api_failure_and_invalid_json_preserve_previously_accepted_tags(self):
        from bbolprom_engine.api import APIUnavailable
        text='😀 복도에 서 있습니다.'
        cid=self.app.library.manual(text,[])
        accepted=[{'tag':'복도','category_id':'F','category_column':'F',
                   'spans':[{'start_cp':2,'end_cp':4,'evidence':'복도'}]}]
        self.app.library.save_analysis(cid,{'source_text':text,'tags':accepted,'status':'ok'})
        status,_,_=self.request('POST','/api/categories',{'operation':'define','id':'F','definition':'실제 장면의 장소'})
        self.assertEqual(status,200)
        config={'enabled':True,'consent':True,'endpoint':'https://api.openai.com/v1/chat/completions','model':'fixture-model'}
        self.assertEqual(self.request('POST','/api/settings',{'api':config})[0],200)
        for failure,expected in [(APIUnavailable('API HTTP 429; card retained'),'api_unavailable'),(None,'invalid_response')]:
            kwargs={'side_effect':failure} if failure else {'return_value':('malformed json',{})}
            with patch('bbolprom_engine.api._live_transport',**kwargs):
                status,result,_=self.request('POST','/api/analyze',{'id':cid})
            self.assertEqual(status,200)
            self.assertEqual(result['status'],expected)
            card=self.user_cards()[0]
            self.assertEqual(card['source_text'],text)
            self.assertEqual(card['tags'],accepted)

    def test_context_load_failure_is_reported_without_losing_existing_card(self):
        text='원문 유지 및 오류 처리';cid=self.app.library.manual(text,[])
        config={'enabled':True,'consent':True,'endpoint':'https://api.openai.com/v1/chat/completions','model':'fixture-model'}
        self.assertEqual(self.request('POST','/api/settings',{'api':config})[0],200)
        with patch('bbolprom_engine.approved_context.load_approved_context',side_effect=ValueError('승인 사례 파일을 읽을 수 없음')):
            status,error,_=self.request('POST','/api/analyze',{'id':cid})
        self.assertEqual(status,400);self.assertIn('승인 사례',error['error'])
        self.assertEqual(self.user_cards()[0]['source_text'],text)
        self.assertEqual(self.user_cards()[0]['tags'],[])

    def test_existing_approved_prompt_adds_image_source_overlay_without_duplicate_or_reanalysis(self):
        catalog=APP_ROOT/'assets'/'approved_catalog.json';original_bytes=catalog.read_bytes()
        counts=Counter(c['source_text'] for c in self.app.approved)
        approved=next(c for c in self.app.approved if counts[c['source_text']]==1)
        original_card=copy.deepcopy(approved);text=approved['source_text']
        manual_bytes=b'original-manual-overlay';hwpx_bytes=b'original-hwpx-overlay'
        status,result,_=self.request('POST','/api/manual',{'text':text,'images':[
            {'name':'manual-overlay.png','base64':base64.b64encode(manual_bytes).decode()}]})
        self.assertEqual(status,200);overlay_id=result['id']
        status,state,_=self.request('GET','/api/state');self.assertEqual(status,200)
        self.assertEqual(len(state['cards']),309)
        visible=next(c for c in state['cards'] if c['id']==approved['id'])
        self.assertTrue(visible['approved']);self.assertEqual(visible['overlay_id'],overlay_id)
        self.assertEqual(visible['tags'],original_card['tags'])
        self.assertEqual(visible['source_text'],text)
        source=source_file(self.root/'approved-source.hwpx',[text],[hwpx_bytes])
        for filename in ('approved-source.hwpx','same-content-renamed.hwpx'):
            status,review,_=self.request('POST','/api/upload',raw=source.read_bytes(),headers={'X-Filename':filename})
            self.assertEqual(status,200)
            self.assertEqual(review['plan'][0]['action'],'approved_card_image_source_overlay')
            self.assertEqual(review['cards'][0]['source_text'],text)
            status,committed,_=self.request('POST','/api/commit',{'ticket':review['ticket']})
            self.assertEqual(status,200);self.assertEqual(committed['ids'],[overlay_id])
        status,state,_=self.request('GET','/api/state');self.assertEqual(status,200)
        self.assertEqual(len(state['cards']),309)
        visible=next(c for c in state['cards'] if c['id']==approved['id'])
        self.assertEqual(visible['tags'],original_card['tags'])
        self.assertEqual(visible['source_text'],text)
        known_images=[i for i in visible['images'] if i.get('sha')]
        self.assertEqual({i['sha'] for i in known_images},{hashlib.sha256(manual_bytes).hexdigest(),hashlib.sha256(hwpx_bytes).hexdigest()})
        self.assertEqual([x['filename'] for x in visible['origins']],['manual-overlay.png','approved-source.hwpx','same-content-renamed.hwpx'])
        self.assertEqual(len(self.app.library.cards()),1)
        for ident in (approved['id'],overlay_id):
            status,error,_=self.request('POST','/api/analyze',{'id':ident})
            self.assertEqual(status,400);self.assertIn('승인 카드',error['error'])
        self.assertEqual(catalog.read_bytes(),original_bytes)
        self.assertEqual(next(c for c in self.app.approved if c['id']==approved['id']),original_card)

    def test_ambiguous_approved_prompt_requires_manual_target_and_persists_selection(self):
        counts=Counter(c['source_text'] for c in self.app.approved)
        chosen=next(c for c in self.app.approved if counts[c['source_text']]>1)
        matches=[c for c in self.app.approved if c['source_text']==chosen['source_text']]
        other=next(c for c in self.app.approved if c['source_text']!=chosen['source_text'])
        originals=copy.deepcopy(matches)
        payload={'text':chosen['source_text'],'images':[{'name':'ambiguous.png','base64':base64.b64encode(b'ambiguous-original-image').decode()}]}
        status,error,_=self.request('POST','/api/manual',payload)
        self.assertEqual(status,400);self.assertIn('여러 개',error['error'])
        self.assertEqual(self.app.library.cards(),[])
        self.assertEqual(self.app.library.get_setting('approved_overlay_targets',{}),{})
        status,error,_=self.request('POST','/api/manual',dict(payload,approved_target=other['id']))
        self.assertEqual(status,400);self.assertEqual(self.app.library.cards(),[])
        status,result,_=self.request('POST','/api/manual',dict(payload,approved_target=chosen['id']))
        self.assertEqual(status,200);overlay=result['id']
        # A later import uses the saved explicit choice, without changing targets.
        status,again,_=self.request('POST','/api/manual',payload)
        self.assertEqual(status,200);self.assertEqual(again['id'],overlay)
        status,state,_=self.request('GET','/api/state');self.assertEqual(status,200)
        self.assertEqual(len(state['cards']),309)
        for original in originals:
            projected=next(c for c in state['cards'] if c['id']==original['id'])
            self.assertEqual(projected['tags'],original['tags'])
            self.assertEqual(projected['source_text'],original['source_text'])
            if original['id']==chosen['id']:
                self.assertEqual(projected['overlay_id'],overlay)
                self.assertEqual(len(projected['origins']),2)
                self.assertEqual(len(projected['images']),len(original['images'])+1)
            else:
                self.assertEqual(projected['images'],original['images'])
                self.assertEqual(projected['origins'],original['origins'])
                self.assertNotIn('overlay_id',projected)

    def test_ambiguous_approved_hwpx_review_requires_explicit_matching_target(self):
        counts=Counter(c['source_text'] for c in self.app.approved)
        chosen=next(c for c in self.app.approved if counts[c['source_text']]>1)
        other=next(c for c in self.app.approved if c['source_text']!=chosen['source_text'])
        source=source_file(self.root/'ambiguous.hwpx',[chosen['source_text']],[b'hwpx-ambiguous-image'])
        status,review,_=self.request('POST','/api/upload',raw=source.read_bytes(),headers={'X-Filename':'ambiguous.hwpx'})
        self.assertEqual(status,200)
        self.assertGreater(len(review['cards'][0]['approved_matches']),1)
        self.assertIn(chosen['id'],[m['id'] for m in review['cards'][0]['approved_matches']])
        payload={'ticket':review['ticket']}
        self.assertEqual(self.request('POST','/api/commit',payload)[0],400)
        self.assertEqual(self.app.library.cards(),[])
        self.assertEqual(self.request('POST','/api/commit',dict(payload,approved_targets={'1':other['id']}))[0],400)
        self.assertEqual(self.app.library.cards(),[])
        status,result,_=self.request('POST','/api/commit',dict(payload,approved_targets={'1':chosen['id']}))
        self.assertEqual(status,200)
        status,state,_=self.request('GET','/api/state');self.assertEqual(status,200)
        self.assertEqual(len(state['cards']),309)
        projected=next(c for c in state['cards'] if c['id']==chosen['id'])
        self.assertEqual(projected['overlay_id'],result['ids'][0])
        self.assertEqual(projected['tags'],chosen['tags'])
        self.assertEqual(projected['origins'][0]['filename'],'ambiguous.hwpx')

    def test_user_tag_edit_preserves_text_unicode_spans_and_rejects_invalid_changes(self):
        text='😀 복도와 복도. 창문 옆.'
        status,created,_=self.request('POST','/api/manual',{'text':text,'images':[]})
        self.assertEqual(status,200);cid=created['id']
        tags=[{'name':'복도','category_id':'F','evidence':'복도'},
              {'name':'근거 보류','category_id':None,'evidence':''}]
        status,result,_=self.request('POST','/api/tags',{'id':cid,'tags':tags})
        self.assertEqual(status,200)
        card=self.user_cards()[0]
        self.assertEqual(card['source_text'],text);self.assertEqual(card['sha'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(card['analysis_status'],'user_edited')
        self.assertEqual([(x['start_cp'],x['end_cp']) for x in card['tags'][0]['spans']],[(2,4),(6,8)])
        self.assertEqual(card['tags'][1]['spans'],[])
        self.assertIsNone(card['tags'][1]['category_id'])
        # An unchanged UI edit carries its verified multi-span selection intact.
        unchanged=copy.deepcopy(tags)
        unchanged[0].update(evidence='',original_spans=card['tags'][0]['spans'])
        status,result,_=self.request('POST','/api/tags',{'id':cid,'tags':unchanged})
        self.assertEqual(status,200)
        accepted=copy.deepcopy(self.user_cards()[0]['tags'])
        invalids=[
            [{'name':'복도','category_id':'F','evidence':'없는 근거'}],
            [tags[0],dict(tags[0],name=' 복도 ')],
            [dict(tags[0],original_spans=[{'start_cp':3,'end_cp':4,'evidence':'복도'}])],
            [dict(tags[0],category_id='unknown-category')],
        ]
        for invalid in invalids:
            status,error,_=self.request('POST','/api/tags',{'id':cid,'tags':invalid})
            self.assertEqual(status,400)
            card=self.user_cards()[0]
            self.assertEqual(card['tags'],accepted);self.assertEqual(card['source_text'],text)
        counts=Counter(c['source_text'] for c in self.app.approved)
        approved=next(c for c in self.app.approved if counts[c['source_text']]==1)
        original_tags=copy.deepcopy(approved['tags'])
        status,overlay,_=self.request('POST','/api/manual',{'text':approved['source_text'],'images':[]})
        self.assertEqual(status,200)
        for ident in (approved['id'],overlay['id']):
            status,error,_=self.request('POST','/api/tags',{'id':ident,'tags':[]})
            self.assertEqual(status,400);self.assertIn('승인 카드',error['error'])
        self.assertEqual(next(c for c in self.app.approved if c['id']==approved['id'])['tags'],original_tags)

    def test_diagnostic_http_export_keeps_xml_not_images_and_survives_review_cancel(self):
        from test_diagnostics_v3 import diagnostic_source
        source=self.root/'local-original.hwpx';originals,excluded=diagnostic_source(source)
        payload=source.read_bytes();db_before=self.app.library.db.read_bytes()
        status,review,_=self.request('POST','/api/upload',raw=payload,headers={'X-Filename':'review.hwpx'})
        self.assertEqual(status,200);ticket=review['ticket']
        pending_source=self.app.pending[ticket][0]
        self.assertEqual(pending_source.read_bytes(),payload)
        self.assertEqual(self.request('POST','/api/diagnostic',{'ticket':ticket},authorized=False)[0],403)
        status,export,_=self.request('POST','/api/diagnostic',{'ticket':ticket})
        self.assertEqual(status,200);self.assertFalse(export['image_bytes_included'])
        self.assertEqual(export['source_sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(export['cards'],len(review['cards']))
        self.assertTrue(export['file'].endswith('.diagnostic.zip'))
        status,download,_=self.request('GET',export['download']);self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(download)) as z:
            self.assertEqual(set(z.namelist()),{'report.json'}|{'source/'+name for name in originals})
            report=json.loads(z.read('report.json'))
            self.assertEqual(report['source']['sha256'],hashlib.sha256(payload).hexdigest())
            self.assertEqual(report['extraction']['card_count'],len(review['cards']))
            for name,raw in originals.items():self.assertEqual(z.read('source/'+name),raw)
            uncompressed=b''.join(z.read(name) for name in z.namelist())
            for raw in excluded.values():self.assertNotIn(raw,uncompressed)
        self.assertEqual(self.app.library.db.read_bytes(),db_before)
        self.assertEqual(self.app.library.cards(),[])
        self.assertEqual(source.read_bytes(),payload)
        self.assertEqual(pending_source.read_bytes(),payload)
        self.assertEqual(self.request('POST','/api/cancel',{'ticket':ticket})[0],200)
        self.assertFalse(pending_source.exists());self.assertNotIn(ticket,self.app.pending)
        self.assertEqual(self.request('GET',export['download'])[:2],(200,download))
        self.assertEqual(self.request('POST','/api/diagnostic',{'ticket':ticket})[0],400)
        self.assertEqual(self.app.library.db.read_bytes(),db_before)

    def test_ambiguous_commit_returns_precise_review_card_and_choices_without_partial_commit(self):
        counts=Counter(c['source_text'] for c in self.app.approved)
        approved=next(c for c in self.app.approved if counts[c['source_text']]>1)
        matches=[{'id':c['id'],'card_id':c['card_id']} for c in self.app.approved if c['source_text']==approved['source_text']]
        source=source_file(self.root/'two-card-review.hwpx',['첫 번째 신규 카드의 별도 원문입니다.',approved['source_text']],[b'new-card-image',b'approved-overlay-image'])
        payload=source.read_bytes()
        status,review,_=self.request('POST','/api/upload',raw=payload,headers={'X-Filename':'two-card-review.hwpx'})
        self.assertEqual(status,200);self.assertEqual(len(review['cards']),2)
        status,error,_=self.request('POST','/api/commit',{'ticket':review['ticket']})
        self.assertEqual(status,400)
        self.assertEqual(error['review_card'],2);self.assertEqual(error['unresolved_index'],2)
        self.assertEqual(error['approved_matches'],matches)
        self.assertEqual(self.app.library.cards(),[])
        self.assertEqual(self.app.library.get_setting('approved_overlay_targets',{}),{})
        status,committed,_=self.request('POST','/api/commit',{'ticket':review['ticket'],'approved_targets':{'2':approved['id']}})
        self.assertEqual(status,200);self.assertEqual(len(committed['ids']),2)
        status,again,_=self.request('POST','/api/upload',raw=payload,headers={'X-Filename':'two-card-review.hwpx'})
        self.assertEqual(status,200)
        self.assertEqual(again['cards'][1]['approved_target'],approved['id'])
        self.assertEqual(self.request('POST','/api/cancel',{'ticket':again['ticket']})[0],200)


    def test_approved_card_examples_are_explicit_opt_in_and_reach_provider_request(self):
        text='😀 푸른 조명과 카메라 구도, 의상과 장소를 검토한다.'
        status,manual,_=self.request('POST','/api/manual',{'text':text,'images':[]})
        self.assertEqual(status,200)
        cid=manual['id'];requests=[]
        before=(APP_ROOT/'assets/approved_catalog.json').read_bytes()
        def provider(request,config):
            requests.append(copy.deepcopy(request))
            return json.dumps({'card_ref':request['card_ref'],'policy_version':'API-POLICY-1.0',
                'tags':[],'unclassified':[],'create_categories':[],'direct_mutations':[]}),{}
        base={'enabled':True,'consent':True,'endpoint':'https://api.openai.com/v1/chat/completions','model':'mock-model'}
        with patch('bbolprom_engine.api._live_transport',side_effect=provider):
            self.assertEqual(self.request('POST','/api/settings',{'api':base})[0],200)
            with patch('bbolprom_engine.approved_examples.CATALOG_PATH',self.root/'does-not-exist.json'):
                status,response,_=self.request('POST','/api/analyze',{'id':cid})
                self.assertEqual(status,200);self.assertEqual(response['status'],'ok')
            self.assertEqual(requests[-1]['approved_card_examples'],[])
            enabled={**base,'use_approved_examples':True}
            self.assertEqual(self.request('POST','/api/settings',{'api':enabled})[0],200)
            status,response,_=self.request('POST','/api/analyze',{'id':cid})
            self.assertEqual(status,200);self.assertEqual(response['status'],'ok')
        examples=requests[-1]['approved_card_examples']
        self.assertTrue(examples);self.assertLessEqual(len(examples),3)
        self.assertLessEqual(len(json.dumps(examples,ensure_ascii=False,separators=(',',':'))),12000)
        self.assertEqual(requests[-1]['prompt_text'],text)
        for example in examples:
            self.assertIn('provenance',example);self.assertIn('tag_mappings',example)
            self.assertNotIn('images',example)
            for tag in example['tag_mappings']:
                for span in tag['spans']:
                    self.assertEqual(example['source_text'][span['start_cp']:span['end_cp']],span['evidence'])
        self.assertEqual((APP_ROOT/'assets/approved_catalog.json').read_bytes(),before)
        self.assertEqual(self.user_cards()[0]['source_text'],text)
        for invalid in ('true',1,None):
            status,_,_=self.request('POST','/api/settings',{'api':{**base,'use_approved_examples':invalid}})
            self.assertEqual(status,400)

    def test_recorded_workflow_is_sent_and_reference_ids_survive_api_failure(self):
        from bbolprom_engine.api import APIUnavailable
        text='신규 원문: 원형 의자와 유산소 운동기구를 확인한다.'
        status,created,_=self.request('POST','/api/manual',{'text':text,'images':[]})
        self.assertEqual(status,200);cid=created['id']
        self.assertEqual(self.request('POST','/api/tags',{'id':cid,'tags':[{'name':'보존할 태그','category_id':None,'evidence':''}]})[0],200)
        tags_before=copy.deepcopy(self.user_cards()[0]['tags'])
        self.assertEqual(self.request('POST','/api/settings',{'api':{'enabled':True,'consent':True,'endpoint':'https://api.openai.com/v1/chat/completions','model':'mock'}})[0],200)
        captured=[]
        def failed_provider(request,config):
            captured.append(copy.deepcopy(request))
            raise APIUnavailable('API HTTP429; mock failure, card retained')
        with patch('bbolprom_engine.api._live_transport',side_effect=failed_provider):
            status,result,_=self.request('POST','/api/analyze',{'id':cid})
        self.assertEqual(status,200);self.assertEqual(result['status'],'api_unavailable')
        request=captured[0];history=request['approved_processing_history']
        self.assertEqual(len(history['workflow']),8)
        self.assertEqual(len(history['constraints']),19)
        self.assertEqual(len(request['tag_highlight_method']['normalization_phases']),13)
        self.assertTrue(history['decisions'])
        self.assertEqual(request['approved_normalization_examples'],[])
        self.assertTrue(all(r['status'] in ('approved_rule','final_confirmed') for r in history['decisions']))
        card=self.user_cards()[0]
        self.assertEqual(card['source_text'],text);self.assertEqual(card['tags'],tags_before)
        self.assertEqual(card['analysis_references']['decision_ids'],[r['id'] for r in history['decisions']])
        self.assertEqual(card['analysis_references']['status'],'api_unavailable')
        self.assertEqual(len(card['analysis_references']['workflow_ids']),8)
        self.assertEqual(card['analysis_references']['method_guidance']['guidance_sha256'],request['tag_highlight_method']['guidance_sha256'])
        self.assertEqual(len(card['analysis_references']['method_guidance']['clause_ids']),46)
        self.assertNotIn('Authorization',json.dumps(card['analysis_references']))
        with self.app.library.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_references WHERE card_id=?',(cid,)).fetchone()[0],1)

if __name__=='__main__':unittest.main()
