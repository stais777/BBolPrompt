"""User-shareable evidence of local fixed-baseline operations; no real PT/API."""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bbolprom_engine.app import Application,make_server
from bbolprom_engine.local_diagnostics import collect_local_diagnostic,ImportAudit,MAX_ATTEMPTS,safe_error
from test_baseline import synthetic_source


class LocalDiagnostics(unittest.TestCase):
    def test_windows_storage_error_metadata_excludes_path_and_unknown_operation(self):
        error=PermissionError(13,'private-error-message','private-user-path')
        error.winerror=32;error.bbolprom_operation='backup_temporary_cleanup'
        self.assertEqual(safe_error(error),{'type':'PermissionError','errno':13,'winerror':32,'operation':'backup_temporary_cleanup'})
        error.bbolprom_operation='private-secret-operation'
        self.assertNotIn('operation',safe_error(error))
        self.assertNotIn('private',json.dumps(safe_error(error)))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=Application(self.root/'library');self.source=self.root/'source.hwpx';self.counter=0

    def tearDown(self):self.temp.cleanup()

    def export(self):
        self.counter+=1;dest=self.root/('diagnostic-'+str(self.counter)+'.zip')
        report=collect_local_diagnostic(self.app.baseline,dest)
        with zipfile.ZipFile(dest) as z:
            self.assertEqual(set(z.namelist()),{'report.json','SUMMARY.txt'});self.assertIsNone(z.testzip())
            self.assertEqual(json.loads(z.read('report.json')),report)
        self.assertLess(dest.stat().st_size,2*1024*1024)
        return report,dest

    def prepare(self):
        sha=synthetic_source(self.source,self.app.baseline.paths)
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):review=self.app.prepare_baseline(self.source,'PT.hwpx')
        return sha,review

    def commit(self):
        sha,review=self.prepare()
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):self.app.action('/api/baseline-commit',{'ticket':review['ticket']})
        return sha,review

    def test_initial_report_is_not_a_success_and_excludes_text_media_db_and_keys(self):
        secret='private-diagnostic-sentinel-9381'
        self.app.library.set_setting('api',{'key':secret,'endpoint':'https://user:'+secret+'@invalid.test/'})
        self.app.library.manual('private-user-prompt-sentinel-1284',[])
        before=self.app.baseline.cards();report,path=self.export()
        self.assertEqual(report['acceptance'],'not_imported')
        self.assertEqual(report['counts']['fixed_cards'],309);self.assertEqual(report['counts']['linked_image_references'],0)
        serialized=json.dumps(report,ensure_ascii=False)
        for value in (secret,'private-user-prompt-sentinel-1284',self.app.approved[0]['source_text'],self.app.token):self.assertNotIn(value,serialized)
        self.assertEqual(self.app.baseline.cards(),before)
        self.assertTrue(all(v is False for v in report['disclosure'].values()))

    def test_failed_sha_attempt_is_available_after_source_is_deleted(self):
        self.source.write_bytes(b'unknown HWPX file')
        actual=hashlib.sha256(self.source.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'SHA256'):self.app.prepare_baseline(self.source,r'C:\Users\someone\PT.hwpx')
        self.source.unlink();report,_=self.export();attempt=report['import_attempts'][0]
        self.assertEqual(attempt['status'],'failed');self.assertEqual(attempt['filename'],'PT.hwpx')
        self.assertEqual(attempt['details']['file']['sha256'],actual)
        self.assertNotIn('someone',json.dumps(report))
        self.assertEqual(report['acceptance'],'not_imported')

    def test_review_cancel_and_commit_error_events_are_preserved(self):
        sha,review=self.prepare()
        self.source.write_bytes(b'changed after review')
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            with self.assertRaises(ValueError):self.app.action('/api/baseline-commit',{'ticket':review['ticket']})
        self.app.action('/api/cancel',{'ticket':review['ticket']})
        report,_=self.export();events=report['import_attempts'][0]['details']['events']
        self.assertEqual([e['status'] for e in events],['started','source_checked','review_ready','commit_failed','cancelled'])
        self.assertEqual(report['counts']['linked_image_references'],0)

    def test_committed_source_and_stored_images_are_independently_hashed(self):
        sha,_=self.commit()
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):report,_=self.export()
        self.assertEqual(report['acceptance'],'passed_integrity')
        self.assertEqual(report['counts']['linked_image_references'],531)
        self.assertEqual(report['counts']['unique_stored_media'],522)
        self.assertEqual(report['counts']['tag_mappings'],8471);self.assertEqual(report['counts']['spans'],10358)
        self.assertTrue(report['integrity']['source_image_hashes_available'])
        self.assertEqual(report['cards'][187]['images'],[])
        self.assertEqual([i['ref'] for i in report['cards'][108]['images']],['image195'])
        self.assertEqual(len(report['cards'][109]['images']),14)
        self.assertTrue(all(i['source_matches_stored_media'] for c in report['cards'] for i in c['images']))
        self.assertEqual(report['import_attempts'][0]['status'],'committed')

    def test_corrupt_stored_image_is_detected_even_if_database_count_is_complete(self):
        sha,_=self.commit();image=self.app.baseline.cards()[0]['images'][0]['sha']
        (self.app.library.root/'vault'/image).write_bytes(b'corrupted image bytes')
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):report,_=self.export()
        self.assertTrue(report['baseline_status']['complete'])
        self.assertEqual(report['acceptance'],'failed_integrity')
        self.assertFalse(report['media'][image]['hashes_match']);self.assertTrue(report['integrity']['media_errors'])

    def test_missing_stored_image_is_reported_without_leaking_full_path(self):
        sha,_=self.commit();image=self.app.baseline.cards()[0]['images'][0]['sha']
        (self.app.library.root/'vault'/image).unlink()
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):report,_=self.export()
        self.assertEqual(report['acceptance'],'failed_integrity');self.assertFalse(report['media'][image]['present'])
        self.assertNotIn(str(self.app.library.root),json.dumps(report))

    def test_old_import_without_source_digest_does_not_claim_source_readback_comparison(self):
        sha,_=self.commit()
        with self.app.library.connect() as c:c.execute('DELETE FROM import_attempts')
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):report,_=self.export()
        self.assertEqual(report['acceptance'],'passed_storage_integrity_source_comparison_unavailable')
        self.assertFalse(report['integrity']['source_image_hashes_available'])

    def test_attempt_count_is_bounded_and_original_history_is_retained(self):
        audit=ImportAudit(self.app.library)
        for i in range(MAX_ATTEMPTS+4):audit.update(audit.begin('PT.hwpx'),'failed',error={'type':'fixture'})
        report,_=self.export();self.assertEqual(len(report['import_attempts']),MAX_ATTEMPTS)
        self.assertEqual(report['total_import_attempts'],MAX_ATTEMPTS+4);self.assertTrue(report['attempts_truncated'])


class DiagnosticHTTP(unittest.TestCase):
    def test_export_download_is_authenticated_small_and_UI_values_are_whitelisted(self):
        with tempfile.TemporaryDirectory() as temp:
            server=make_server(temp);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(method,path,body=None,auth=True):
                con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
                try:
                    headers={'X-Bbolprom-Token':server.application.token} if auth else {}
                    con.request(method,path,body=json.dumps(body).encode() if body is not None else None,headers=headers)
                    response=con.getresponse();return response.status,response.read()
                finally:con.close()
            try:
                self.assertEqual(request('POST','/api/local-diagnostic',{},auth=False)[0],403)
                status,raw=request('POST','/api/local-diagnostic',{'ui_observation':{'displayed_cards':0,'scope':'all','private_field':'must-not-appear'}})
                self.assertEqual(status,200);result=json.loads(raw)
                self.assertEqual(result['counts']['fixed_cards'],309)
                status,raw=request('GET',result['download']);self.assertEqual(status,200)
                import io
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    report=json.loads(z.read('report.json'));self.assertEqual(report['ui_observation'],{'displayed_cards':0,'scope':'all'})
                    self.assertNotIn('private_field',z.read('report.json').decode())
            finally:server.shutdown();server.server_close();thread.join(timeout=3)
