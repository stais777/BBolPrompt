"""Persisted UI state, editable operational cards and immutable master boundary."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from bbolprom_engine.app import Application
from bbolprom_engine.library import Library
from bbolprom_engine.ui import preferences,save_preferences


class UserInterfaceOperations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.library=Library(self.root/'library')

    def tearDown(self):self.temp.cleanup()

    def test_preferences_survive_new_app_instance_without_changing_baseline(self):
        app=Application(self.library.root)
        before=app.baseline.cards()
        patch={'theme':'carbon','tone':'mint','view':'detail','inspector_width':520,
               'hidden_cards':['approved-1'],'order':['approved-2','approved-1'],
               'selected_tags':['공통 태그'],'applied_tags':['공통 태그'],'filter_active':True,
               'pinned_tags':{'approved-1':['대표 태그']},'sort':'user'}
        app.action('/api/ui',patch)
        restarted=Application(self.library.root)
        state=restarted.state()
        for key,value in patch.items():self.assertEqual(state['ui'][key],value)
        self.assertEqual(restarted.baseline.cards(),before)
        self.assertEqual(len(state['cards']),309)

    def test_invalid_settings_do_not_overwrite_existing_preferences(self):
        save_preferences(self.library,{'theme':'vision'})
        for bad in ({'theme':{}},{'inspector_width':0},{'filter_active':'true'},
                    {'hidden_cards':['x','x']},{'view':'old-list'},{'tag_master':'rewrite'}):
            with self.assertRaises(ValueError):save_preferences(self.library,bad)
        self.assertEqual(preferences(self.library)['theme'],'vision')

    def test_edit_review_values_preserve_id_tags_provenance_and_restore_exact_snapshot(self):
        old_text='🙂 푸른 실험실의 모니터'
        cid=self.library.manual(old_text,[('old.bmp',io.BytesIO(b'BMold'))],filename='출처.hwpx')
        tags=[{'tag':'실험실','category_column':'F','spans':[{'start_cp':5,'end_cp':8,'evidence':'실험실'}]}]
        self.library.save_analysis(cid,{'source_text':old_text,'tags':tags,'status':'user_edited'})
        before=self.library.cards()[0];old_sha=before['images'][0]['sha']
        self.library.edit_card(cid,'수정한 새 원문',[('new.bmp',io.BytesIO(b'BMnew'))],[old_sha],before['sha'])
        after=self.library.cards()[0]
        self.assertEqual(after['id'],cid)
        self.assertEqual(after['tags'][0]['tag'],'실험실');self.assertEqual(after['tags'][0]['spans'],[])
        self.assertEqual(len(after['images']),1);self.assertNotEqual(after['images'][0]['sha'],old_sha)
        self.assertTrue({r['id'] for r in before['origins']}.issubset({r['id'] for r in after['origins']}))
        history=self.library.card_history(cid);self.assertEqual(history[0]['source_text'],old_text)
        self.library.restore_card(cid,history[0]['id'])
        restored=self.library.cards()[0]
        self.assertEqual(restored['source_text'],old_text);self.assertEqual(restored['tags'],tags)
        self.assertEqual(restored['images'][0]['sha'],old_sha)
        self.assertEqual(len(self.library.card_history(cid)),2)
        self.assertGreaterEqual(len(list((self.library.root/'backup').glob('*.zip'))),3)

    def test_collision_stale_editor_and_foreign_restore_roll_back(self):
        first=self.library.manual('첫 원문',[]);second=self.library.manual('다른 원문',[])
        with self.assertRaisesRegex(ValueError,'동일한 원문'):self.library.edit_card(first,'다른 원문',[])
        with self.assertRaisesRegex(ValueError,'다른 창'):self.library.edit_card(first,'바뀐 원문',[],expected_sha='0'*64)
        self.assertEqual(self.library.card_history(first),[])
        self.library.edit_card(second,'수정된 다른 원문',[])
        foreign=self.library.card_history(second)[0]['id']
        with self.assertRaisesRegex(ValueError,'이력'):self.library.restore_card(first,foreign)
        self.assertEqual(self.library.cards()[0]['source_text'],'첫 원문')

    def test_approved_cards_are_not_edit_or_restore_targets(self):
        app=Application(self.library.root)
        for route in ('/api/card-edit','/api/card-history','/api/card-restore'):
            with self.assertRaisesRegex(ValueError,'읽기 전용'):
                app.action(route,{'id':'approved-1','text':'새 원문','version_id':'unknown'})
        cid=app.library.manual('사용자 신규 원문',[])
        with self.assertRaisesRegex(ValueError,'승인 원문'):
            app.action('/api/card-edit',{'id':cid,'text':app.approved[0]['source_text']})

    def test_manual_origin_is_preserved_as_metadata_with_images(self):
        app=Application(self.library.root)
        app.action('/api/manual',{'text':'신규 원문','images':[], 'origin_filename':'한글2.hwpx'})
        self.assertEqual(app.library.cards()[0]['origins'][0]['filename'],'한글2.hwpx')
