"""Fixed master registration and synthetic media transport; not an actual PT run."""
import copy
import hashlib
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bbolprom_engine.app import Application, make_server
from bbolprom_engine.baseline import BaselineStore, load_dataset
from bbolprom_engine.library import Library


def synthetic_source(path, paths, missing=None):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        # Intentionally no parseable sections/metadata: baseline attachment may
        # use only manifest paths, never inference or text resegmentation.
        for name in paths:
            if name != missing:
                z.writestr(name, (b'BM' if name.endswith('.BMP') else b'\xff\xd8')+b'synthetic transport fixture: '+name.encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FixedBaseline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = Library(self.root/'library')
        self.records = load_dataset()
        self.store = BaselineStore(self.library, self.records)
        self.source = self.root/'synthetic.hwpx'

    def tearDown(self):
        self.temp.cleanup()

    def prepare_fixture(self):
        sha = synthetic_source(self.source, self.store.paths)
        with patch('bbolprom_engine.baseline.SOURCE_SHA', sha):
            result = self.store.prepare(self.source, 'synthetic.hwpx')
        return sha, result

    def test_registers_309_fixed_ids_without_merging_repeated_prompts(self):
        cards = self.store.cards()
        self.assertEqual([c['card_id'] for c in cards], list(range(1,310)))
        self.assertEqual(len({c['source_text_sha256'] for c in cards}), 296)
        self.assertEqual(sum(len(c['images']) for c in cards), 531)
        self.assertEqual(len(self.store.paths), 522)
        self.assertEqual(cards[187]['images'], [])
        self.assertEqual([im['ref'] for im in cards[108]['images']], ['image195'])
        self.assertEqual([im['ref'] for im in cards[109]['images']], ['image'+str(i) for i in range(196,210)])
        self.assertNotEqual(cards[108]['source_text'],cards[109]['source_text'])
        self.assertEqual(sum(len(c['tags']) for c in cards), 8471)
        self.assertEqual(sum(len(t['spans']) for c in cards for t in c['tags']), 10358)
        self.assertEqual(sum(not t['spans'] for c in cards for t in c['tags']), 17)
        self.assertEqual(self.library.cards(), [])
        self.assertEqual(self.store.status()['linked_image_references'], 0)

    def test_unknown_or_updated_source_is_rejected_without_changing_user_data(self):
        cid = self.library.manual('사용자가 보관하는 신규 카드', [])
        before = self.store.cards()
        synthetic_source(self.source, self.store.paths)
        with self.assertRaisesRegex(ValueError,'SHA256'):
            self.store.prepare(self.source, 'PT.hwpx')
        self.assertEqual(self.store.cards(), before)
        self.assertEqual(self.library.cards()[0]['id'], cid)
        self.assertEqual(self.store.status()['source_imports'], 0)

    def test_synthetic_attach_restart_repeat_and_shared_paths(self):
        sha, result = self.prepare_fixture()
        before = [c['tags'] for c in self.store.cards()]
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha), \
             patch('bbolprom_engine.app.analyze',side_effect=AssertionError('no segmentation')), \
             patch('bbolprom_engine.hwpx.HWPXReader',side_effect=AssertionError('no text parser')):
            first = self.store.commit(self.source,result)
            second = self.store.commit(self.source,result)
        self.assertEqual(first,second)
        self.assertTrue(first['complete'])
        self.assertEqual(first['source_imports'],1)
        restarted = BaselineStore(Library(self.library.root),load_dataset())
        cards = restarted.cards()
        self.assertEqual([c['tags'] for c in cards],before)
        self.assertEqual(sum(bool(im['sha']) for c in cards for im in c['images']),531)
        self.assertEqual(cards[54]['images'][0]['sha'],cards[81]['images'][0]['sha'])
        with self.library.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM media').fetchone()[0],522)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM cards').fetchone()[0],0)
        backups = sorted((self.library.root/'backup').glob('*.zip'))
        with zipfile.ZipFile(backups[-1]) as z:
            self.assertIn('library.sqlite3',z.namelist())
            self.assertEqual(len([p for p in z.namelist() if p.startswith('vault/')]),522)

    def test_missing_reference_refuses_preparation(self):
        sha = synthetic_source(self.source,self.store.paths,missing=self.store.paths[-1])
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            with self.assertRaisesRegex(ValueError,'경로'):
                self.store.prepare(self.source,'synthetic.hwpx')
        self.assertEqual(self.store.status()['linked_image_references'],0)

    def test_changed_source_after_review_and_edited_card_are_rejected(self):
        sha,result = self.prepare_fixture()
        changed = copy.deepcopy(result)
        changed['cards'][108]['card_id'] = 110
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            with self.assertRaisesRegex(ValueError,'변경 금지'):
                self.store.commit(self.source,changed)
            self.source.write_bytes(b'changed after review')
            with self.assertRaisesRegex(ValueError,'변경'):
                self.store.commit(self.source,result)
        self.assertEqual(self.store.status()['linked_image_references'],0)

    def test_image_digest_failure_rolls_back_every_db_link(self):
        sha,result = self.prepare_fixture()
        for c in result['cards']:
            for im in c['images']:
                if im['path']==self.store.paths[1]:im['digest']['sha256']='0'*64
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            with self.assertRaisesRegex(ValueError,'해시 불일치'):
                self.store.commit(self.source,result)
        with self.library.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM media').fetchone()[0],0)
        self.assertEqual(self.store.status()['linked_image_references'],0)
        self.assertEqual(self.store.status()['source_imports'],0)

    def test_approved_database_rows_and_link_identity_cannot_be_rewritten(self):
        with self.library.connect() as c:
            for statement in ("UPDATE baseline_cards SET record_json='{}' WHERE card_id=1",
                              'DELETE FROM baseline_cards WHERE card_id=1',
                              "UPDATE baseline_image_links SET ref='other' WHERE card_id=1",
                              'DELETE FROM baseline_image_links WHERE card_id=1'):
                with self.assertRaises(sqlite3.IntegrityError):c.execute(statement)

    def test_cancel_and_cross_route_cannot_commit_baseline_as_generic_cards(self):
        app=Application(self.library.root)
        sha=synthetic_source(self.source,self.store.paths)
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            result=app.prepare_baseline(self.source,'synthetic.hwpx')
        with self.assertRaisesRegex(ValueError,'등록 경로'):
            app.action('/api/commit',{'ticket':result['ticket']})
        with self.assertRaisesRegex(ValueError,'편집 없이'):
            app.action('/api/baseline-commit',{'ticket':result['ticket'],'cards':[]})
        self.assertTrue(app.action('/api/cancel',{'ticket':result['ticket']})['cancelled'])
        self.assertFalse(self.source.exists())
        self.assertEqual(self.store.status()['linked_image_references'],0)


class BaselineHTTP(unittest.TestCase):
    def test_authenticated_upload_review_commit_state_and_idempotent_reupload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            server=make_server(root/'library')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            app=server.application
            source=root/'synthetic.hwpx'
            sha=synthetic_source(source,app.baseline.paths)
            raw=source.read_bytes()
            def request(route,body,auth=True):
                con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
                headers={'X-Bbolprom-Token':app.token} if auth else {}
                try:
                    con.request('POST',route,body=body,headers=headers)
                    response=con.getresponse()
                    return response.status,json.loads(response.read())
                finally:con.close()
            try:
                self.assertEqual(request('/api/baseline-upload',raw,False)[0],403)
                self.assertEqual(request('/api/baseline-upload',raw)[0],400)
                with patch('bbolprom_engine.baseline.SOURCE_SHA',sha), \
                     patch('bbolprom_engine.app.analyze',side_effect=AssertionError('no segmentation')), \
                     patch('bbolprom_engine.hwpx.HWPXReader',side_effect=AssertionError('no parsing')):
                    for _ in range(2):
                        status,review=request('/api/baseline-upload',raw)
                        self.assertEqual(status,200)
                        self.assertEqual(len(review['cards']),309)
                        self.assertEqual(review['cards'][187]['images'],[])
                        con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                        try:
                            con.request('GET','/pending-media/'+review['ticket']+'/0')
                            response=con.getresponse()
                            self.assertEqual(response.getheader('Content-Type'),'image/bmp')
                            self.assertTrue(response.read().startswith(b'BM'))
                        finally:con.close()
                        status,done=request('/api/baseline-commit',json.dumps({'ticket':review['ticket']}))
                        self.assertEqual(status,200)
                        self.assertTrue(done['baseline']['complete'])
                state=app.state()
                self.assertEqual(len(state['cards']),309)
                self.assertEqual(sum(bool(im.get('sha')) for c in state['cards'] for im in c['images']),531)
                self.assertEqual(state['baseline']['source_imports'],1)
                self.assertEqual(list((app.library.root/'pending').glob('*')),[])
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)
