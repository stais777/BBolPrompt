"""Synthetic portable migration/retained-originals tests, never user data/API."""
import copy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from bbolprom_engine.app import Application,make_server,main
from bbolprom_engine.portable_storage import (prepare_portable_data,preserve_basefile,verify_data,
    database_fingerprint,relative_file,audit_original_storage,atomic_copy,previous_data_root,remember_data_root)
from bbolprom_engine.local_diagnostics import collect_local_diagnostic
from bbolprom_engine.startup_progress import StartupProgress
from test_baseline import synthetic_source
import test_app_v3


class PortableStorage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def legacy(self):
        old=self.root/'이전 PC 사용자 #1';app=Application(old)
        source=self.root/'PT.hwpx';sha=synthetic_source(source,app.baseline.paths)
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            review=app.prepare_baseline(source,'PT.hwpx');app.action('/api/baseline-commit',{'ticket':review['ticket']})
        cid=app.library.manual('원문\r\n띄어쓰기  😀',[('한글 원본.PNG',io.BytesIO(b'unchanged-original-image'))])
        app.library.edit_card(cid,'수정한 원문 😀',[('추가.jpg',io.BytesIO(b'next-original-image'))])
        app.action('/api/baseline-tags',{'id':'approved-1','tags':[],'expected_revision':0})
        app.api_budget.reserve(0.01,SimpleNamespace(max_calls=10,max_cost_usd=1))
        # Model the old0.3.6 layout: image vault/DB exist, no retained PT or
        # per-card exported originals. These are only disposable fixture files.
        with app.library.connect() as c:
            c.execute('DROP TABLE source_documents');c.execute('DROP TABLE card_original_files')
        shutil.rmtree(old/'sources');shutil.rmtree(old/'new_cards')
        return old,app,cid

    def test_verified_legacy_copy_preserves309_editions_images_history_and_quota(self):
        old,app,cid=self.legacy();before=database_fingerprint(old/'library.sqlite3')
        expected=copy.deepcopy(app.baseline.cards());editions=app.baseline_tag_edits.history(1)
        user_cards=app.library.cards();versions=app.library.card_history(cid);progress=[]
        target=self.root/'새 Windows 이름 #2'/'뽈프롬'/'data'
        self.assertEqual(prepare_portable_data(target,old,lambda *args:progress.append(args)),target.resolve())
        self.assertEqual(database_fingerprint(old/'library.sqlite3'),before)
        copied=database_fingerprint(target/'library.sqlite3')
        self.assertTrue(all(copied[k]==v for k,v in before.items()))
        new=Application(target)
        self.assertEqual(new.baseline.cards(),expected)
        self.assertEqual(new.baseline_tag_edits.history(1),editions)
        self.assertEqual(new.library.cards(),user_cards);self.assertEqual(new.library.card_history(cid),versions)
        self.assertEqual(new.api_budget.status()['calls'],1)
        self.assertEqual(verify_data(new.library)['linked_image_references'],531)
        self.assertTrue((target/'new_cards'/cid).is_dir());self.assertTrue(progress)
        self.assertEqual(json.loads((target/'portable.json').read_text())['migrated_legacy'],True)
        self.assertTrue(all(not Path(r['path']).is_absolute() for card in new.library.cards() for r in card['images']))

    def test_whole_data_folder_copy_to_another_path_needs_no_document_relink(self):
        old,_,_=self.legacy();first=self.root/'first'/'data';prepare_portable_data(first,old)
        destination=self.root/'다른 컴퓨터 #3'/'data';shutil.copytree(first,destination)
        before=database_fingerprint(destination/'library.sqlite3')
        prepare_portable_data(destination,None)
        self.assertEqual(database_fingerprint(destination/'library.sqlite3'),before)
        app=Application(destination);self.assertEqual(verify_data(app.library)['linked_image_references'],531)
        self.assertEqual(app.baseline_tag_edits.latest(1)['tags'],[])
        self.assertEqual(app.api_budget.status()['calls'],1)

    def test_existing_portable_library_wins_over_legacy_without_merging(self):
        target=self.root/'program'/'data';prepare_portable_data(target,None)
        current=Application(target);cid=current.library.manual('이 폴더의 현재 사용자 카드',[])
        old,_,_=self.legacy();before=database_fingerprint(target/'library.sqlite3')
        prepare_portable_data(target,old)
        self.assertEqual(database_fingerprint(target/'library.sqlite3'),before)
        self.assertEqual([c['id'] for c in Application(target).library.cards()],[cid])

    def test_partial_target_without_database_is_not_overwritten(self):
        target=self.root/'data';target.mkdir();(target/'important.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'덮어쓰지'):prepare_portable_data(target,None)
        self.assertEqual((target/'important.txt').read_text(),'keep')

    def test_interrupted_copy_leaves_legacy_intact_and_cleans_staging(self):
        old,_,_=self.legacy();before=database_fingerprint(old/'library.sqlite3');target=self.root/'data'
        with patch('bbolprom_engine.portable_storage.atomic_copy',side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):prepare_portable_data(target,old)
        self.assertFalse((target/'library.sqlite3').exists())
        self.assertEqual(database_fingerprint(old/'library.sqlite3'),before)
        self.assertEqual(list(self.root.glob('.bbolprom-data-copy-*')),[])

    def test_source_file_change_during_copy_cannot_be_published(self):
        source=self.root/'source';destination=self.root/'copy';source.write_bytes(b'a'*1024)
        def changed(_):
            with source.open('ab') as stream:stream.write(b'changed')
        # One callback only; an extra appended chunk must not keep growing.
        called=False
        def once(size):
            nonlocal called
            if not called:called=True;changed(size)
        with self.assertRaisesRegex(ValueError,'변경'):atomic_copy(source,destination,progress=once)
        self.assertFalse(destination.exists())

    def test_source_database_change_during_migration_keeps_newest_legacy_and_aborts(self):
        old,app,_=self.legacy();target=self.root/'data';changed=False
        def progress(*args):
            nonlocal changed
            if not changed and args[1]>0:
                changed=True;app.library.set_setting('concurrent-change','keep newest source')
        with self.assertRaisesRegex(ValueError,'이전 자료가 변경'):prepare_portable_data(target,old,progress)
        self.assertFalse((target/'library.sqlite3').exists())
        self.assertEqual(app.library.get_setting('concurrent-change'),'keep newest source')

    def test_insufficient_space_fails_before_switching(self):
        old,_,_=self.legacy();target=self.root/'data'
        with patch('bbolprom_engine.portable_storage.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError,'공간'):prepare_portable_data(target,old)
        self.assertFalse((target/'library.sqlite3').exists());self.assertTrue((old/'library.sqlite3').is_file())

    def test_corrupt_legacy_asset_is_not_accepted_as_successful_migration(self):
        old,app,_=self.legacy();image=app.baseline.cards()[0]['images'][0]
        (old/image['path']).write_bytes(b'corrupt');target=self.root/'data'
        with self.assertRaises(ValueError):prepare_portable_data(target,old)
        self.assertFalse((target/'library.sqlite3').exists());self.assertEqual((old/image['path']).read_bytes(),b'corrupt')

    def test_live_old_application_must_be_closed_before_copy(self):
        old=self.root/'legacy';server=make_server(old)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        (old/'runtime.json').write_text(json.dumps({'port':server.server_port}))
        try:
            with self.assertRaisesRegex(ValueError,'이전 뽈프롬'):prepare_portable_data(self.root/'data',old)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_retained_PT_exact_bytes_survive_original_path_removal_and_reject_wrong_input(self):
        app=Application(self.root/'data');source=self.root/'PT.hwpx';sha=synthetic_source(source,app.baseline.paths)
        original=source.read_bytes()
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            preserve_basefile(app.library,source);source.unlink()
            self.assertTrue(app.state()['storage']['baseline_source_saved'])
            bad=self.root/'bad.hwpx';bad.write_bytes(b'wrong document')
            with self.assertRaisesRegex(ValueError,'SHA256'):preserve_basefile(app.library,bad)
        self.assertEqual((app.library.root/'sources/PT.hwpx').read_bytes(),original)
        self.assertEqual(app.baseline.status()['linked_image_references'],0)

    def test_card_originals_keep_exact_text_images_and_prior_versions(self):
        app=Application(self.root/'data');text='  😀 원문\r\n공백  '
        cid=app.library.manual(text,[('한글 원본.PNG',io.BytesIO(b'raw-image-one'))])
        first=app.library.cards()[0]
        app.library.edit_card(cid,'변경한 원문',[('다음.jpg',io.BytesIO(b'raw-image-two'))])
        with app.library.connect() as c:files=[dict(r) for r in c.execute('SELECT * FROM card_original_files WHERE card_id=?',(cid,))]
        self.assertEqual(len(files),4)
        oldtext=next(r for r in files if r['kind']=='text' and r['sha256']==hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual((app.library.root/oldtext['path']).read_bytes(),text.encode())
        image=next(r for r in files if r['original_name']=='한글 원본.PNG')
        self.assertTrue(image['path'].endswith('한글 원본.PNG'));self.assertEqual((app.library.root/image['path']).read_bytes(),b'raw-image-one')
        app.library.restore_card(cid,app.library.card_history(cid)[0]['id'])
        self.assertEqual(app.library.cards()[0]['source_text'],first['source_text'])
        self.assertEqual(audit_original_storage(app.library)['errors'],[])

    def test_original_file_tampering_is_detected_without_silent_overwrite(self):
        app=Application(self.root/'data');cid=app.library.manual('원문',[('x.png',io.BytesIO(b'original'))])
        with app.library.connect() as c:row=c.execute("SELECT path FROM card_original_files WHERE kind='image'").fetchone()
        path=app.library.root/row['path'];path.write_bytes(b'external change')
        with self.assertRaises(ValueError):app.library.manual('원문',[])
        self.assertEqual(path.read_bytes(),b'external change');self.assertEqual(app.library.cards()[0]['id'],cid)
        self.assertTrue(audit_original_storage(app.library)['errors'])

    def test_full_backup_has_source_and_card_originals_automatic_snapshot_skips_large_PT(self):
        app=Application(self.root/'data');source=self.root/'PT.hwpx';sha=synthetic_source(source,app.baseline.paths)
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):preserve_basefile(app.library,source)
        app.library.manual('원문',[('x.png',io.BytesIO(b'original'))])
        with zipfile.ZipFile(app.library.backup()) as z:
            self.assertIn('sources/PT.hwpx',z.namelist());self.assertTrue(any(n.startswith('new_cards/') for n in z.namelist()))
            self.assertNotIn('api-safety.sqlite3',z.namelist())
        with zipfile.ZipFile(app.library.backup(include_sources=False)) as z:self.assertNotIn('sources/PT.hwpx',z.namelist())

    def test_diagnostic_reports_original_integrity_without_private_names_or_paths(self):
        app=Application(self.root/'data');app.library.manual('private-prompt-78391',[('private-filename-78391.png',io.BytesIO(b'original'))])
        report=collect_local_diagnostic(app.baseline,self.root/'report.zip')
        self.assertEqual(report['original_storage']['new_card_original_files'],2)
        self.assertEqual(report['original_storage']['errors'],[])
        body=json.dumps(report);self.assertNotIn('private-filename-78391',body);self.assertNotIn('private-prompt-78391',body);self.assertNotIn(str(app.library.root),body)

    def test_escaping_relative_paths_are_rejected(self):
        for value in ('../outside','/outside','C:/Users/else','vault\\outside','vault/../../outside'):
            with self.assertRaises(ValueError):relative_file(self.root,value)

    def test_main_selects_exe_relative_data_directory(self):
        folder=self.root/'program';folder.mkdir();target=folder/'data';target.mkdir()
        server=SimpleNamespace(server_port=12345,serve_forever=lambda:None,server_close=lambda:None)
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'profile')}),patch('bbolprom_engine.portable_storage.prepare_portable_data',return_value=target) as prepare,patch('bbolprom_engine.app.make_server',return_value=server) as make:
            self.assertEqual(main(['--portable-root',str(folder),'--no-browser']),0)
        self.assertEqual(prepare.call_args.args[0],target);self.assertEqual(make.call_args.args[0],target)

    def test_later_update_prefers_latest_portable_folder_over_stale_profile_library(self):
        profile=self.root/'profile';latest=self.root/'latest'/'data';prepare_portable_data(latest,None)
        self.assertTrue(remember_data_root(latest,profile))
        (profile/'Bbolprom').mkdir();(profile/'Bbolprom/library.sqlite3').write_bytes(b'stale')
        self.assertEqual(previous_data_root(self.root/'new-program/data',profile),latest)

    def test_missing_previous_portable_data_does_not_fall_back_to_old_library(self):
        profile=self.root/'profile';missing=self.root/'deleted-data';remember_data_root(missing,profile)
        with self.assertRaisesRegex(ValueError,'이전에 사용한 data'):previous_data_root(self.root/'new-data',profile)

    def test_existing_data_folder_is_independent_of_other_PC_location_hint(self):
        profile=self.root/'profile';remember_data_root(self.root/'unavailable-other-PC',profile)
        current=self.root/'copied/data';prepare_portable_data(current,None)
        self.assertIsNone(previous_data_root(current,profile))


class PortableHTTP(unittest.TestCase):
    setUp=test_app_v3.LocalHTTPApplication.setUp
    tearDown=test_app_v3.LocalHTTPApplication.tearDown
    request=test_app_v3.LocalHTTPApplication.request

    def test_source_only_upload_is_authenticated_and_does_not_rewrite309(self):
        path=self.root/'PT.hwpx';sha=synthetic_source(path,self.app.baseline.paths);before=copy.deepcopy(self.app.baseline.cards())
        self.assertEqual(self.request('POST','/api/source-upload',raw=path.read_bytes(),headers={'X-Filename':'PT.hwpx'},authorized=False)[0],403)
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            status,result,_=self.request('POST','/api/source-upload',raw=path.read_bytes(),headers={'X-Filename':'PT.hwpx'})
        self.assertEqual(status,200);self.assertEqual(result['sha256'],sha)
        self.assertEqual(self.app.baseline.cards(),before)
        self.assertEqual(self.request('POST','/api/source-upload',raw=b'wrong',headers={'X-Filename':'wrong.hwpx'})[0],400)

    def test_folder_open_does_not_accept_arbitrary_paths(self):
        self.assertEqual(self.request('POST','/api/open-data-folder',{'path':'C:/else'})[0],400)
        self.assertEqual(self.request('POST','/api/open-card-folder',{'id':'../else'})[0],400)
        self.assertEqual(self.request('POST','/api/open-data-folder',{},authorized=False)[0],403)
        cid=self.app.library.manual('폴더 열기 검사',[])
        with patch('bbolprom_engine.app.os.startfile',create=True) as opened:
            self.assertEqual(self.request('POST','/api/open-data-folder',{})[0],200)
            self.assertEqual(opened.call_args.args[0],str(self.app.library.root))
            self.assertEqual(self.request('POST','/api/open-card-folder',{'id':cid})[0],200)
            self.assertEqual(opened.call_args.args[0],str(self.app.library.root/'new_cards'/cid))


class StartupPage(unittest.TestCase):
    def test_local_progress_has_no_external_dependency_and_checks_host(self):
        progress=StartupProgress()
        def get(path,host=None):
            con=http.client.HTTPConnection('127.0.0.1',progress.server.server_port)
            try:
                con.request('GET',path,headers={'Host':host} if host else {});response=con.getresponse();return response.status,response.read()
            finally:con.close()
        try:
            progress.update('원본 확인 중',10,20)
            self.assertEqual(json.loads(get('/status')[1])['done'],10)
            self.assertEqual(get('/status','evil.invalid')[0],403)
            progress.ready('http://127.0.0.1:12345/')
            self.assertEqual(json.loads(get('/status')[1])['url'],'http://127.0.0.1:12345/')
            self.assertEqual(get('/')[0],200);self.assertEqual(get('/progress.js')[0],200)
        finally:progress.close()


if __name__=='__main__':unittest.main()
