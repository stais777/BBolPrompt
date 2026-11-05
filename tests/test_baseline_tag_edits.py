"""User-only baseline editions: real SQLite, original hashes, mocked provider."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bbolprom_engine.app import Application,APP_ROOT
from bbolprom_engine.baseline_edits import audit_editions
from bbolprom_engine.local_diagnostics import collect_local_diagnostic
import test_app_v3


def payload(tags):
    return [{'name':t.get('tag',t.get('name')),'category_id':t.get('category_column',t.get('category_id')),
        'source_index':i,'evidence':t.get('spans',[{}])[0].get('evidence','') if t.get('spans') else '',
        'original_spans':copy.deepcopy(t.get('spans',[]))} for i,t in enumerate(tags)]


class BaselineManualEdits(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=Application(self.root/'library');self.edits=self.app.baseline_tag_edits
        self.original=copy.deepcopy(self.app.baseline.cards())
        self.card=self.original[0]

    def fixed_digest(self):
        with self.app.library.connect() as c:
            rows={name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY 1,2')]
                for name in ('baseline_cards','baseline_image_links','baseline_sources')}
        return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()

    def save(self,tags=None,card=None,revision=0):
        card=card or self.card
        rows=payload(card['tags']) if tags is None else tags
        return self.app.action('/api/baseline-tags',{'id':card['id'],'tags':rows,'expected_revision':revision})

    def visible(self,cid=None):return next(c for c in self.app.all_cards() if c['id']==(cid or self.card['id']))

    def test_rename_preserves_multispans_original_and_survives_restart(self):
        card=next(c for c in self.original if any(len(t['spans'])>1 for t in c['tags']))
        rows=payload(card['tags']);index=next(i for i,t in enumerate(card['tags']) if len(t['spans'])>1)
        rows[index]['name']='사용자 수동 확정 이름'
        before=self.fixed_digest();catalog=(APP_ROOT/'assets/approved_catalog.json').read_bytes()
        self.save(rows,card)
        current=self.visible(card['id'])
        self.assertEqual(current['tags'][index]['tag'],'사용자 수동 확정 이름')
        self.assertEqual(current['tags'][index]['spans'],card['tags'][index]['spans'])
        self.assertEqual(current['tag_revision'],1);self.assertEqual(self.fixed_digest(),before)
        self.assertEqual((APP_ROOT/'assets/approved_catalog.json').read_bytes(),catalog)
        restarted=Application(self.app.library.root)
        self.assertEqual(next(c for c in restarted.all_cards() if c['id']==card['id'])['tags'],current['tags'])
        self.assertEqual(self.app.baseline.cards(),self.original)

    def test_all309_untouched_editor_roundtrips_preserve_every_approved_mapping(self):
        for card in self.original:
            tags=self.edits.prepare_tags(card['card_id'],payload(card['tags']),self.app.categories())
            self.assertEqual(tags,card['tags'],card['card_id'])
        self.assertEqual(self.save()['revision'],0)
        self.assertEqual(audit_editions(self.app.library,self.app.baseline.records)['edition_count'],0)

    def test_clear_add_restore_and_original_remain_in_append_only_history(self):
        self.save([]);self.assertEqual(self.visible()['tags'],[])
        rows=[{'name':'명시적인 사용자 태그','category_id':None,'evidence':''}]
        self.save(rows,revision=1);self.assertEqual(self.visible()['tag_revision'],2)
        for target,expected in ((1,[]),(0,self.card['tags']),(2,[{'tag':'명시적인 사용자 태그','category_column':None,'spans':[]}])):
            revision=self.visible()['tag_revision']
            self.app.action('/api/baseline-tag-restore',{'id':self.card['id'],'target_revision':target,'expected_revision':revision})
            self.assertEqual(self.visible()['tags'],expected)
        history=self.edits.history(self.card['card_id'])
        self.assertEqual([h['revision'] for h in history],[5,4,3,2,1,0])
        self.assertEqual(history[-1]['tags'],self.card['tags'])
        self.assertEqual(self.app.baseline.cards(),self.original)

    def test_stale_save_and_restore_do_not_overwrite_latest(self):
        rows=payload(self.card['tags']);rows[0]['name']='첫 창의 수정';self.save(rows)
        with self.assertRaisesRegex(ValueError,'다른 창'):self.save([],revision=0)
        with self.assertRaisesRegex(ValueError,'다른 창'):
            self.app.action('/api/baseline-tag-restore',{'id':self.card['id'],'target_revision':0,'expected_revision':0})
        self.assertEqual(self.visible()['tags'][0]['tag'],'첫 창의 수정');self.assertEqual(len(self.edits.history(self.card['card_id'])),2)

    def test_invalid_evidence_categories_fields_and_revision_leave_data_intact(self):
        bads=[[{'name':'잘못된 근거','category_id':None,'evidence':'this literal cannot exist here 991984'}],
            [{'name':'태그','category_id':'unknown','evidence':''}],
            [{'name':'중복','category_id':None},{'name':'중복','category_id':None}],
            [{'name':'변조','category_id':None,'source_index':0,'original_spans':[],'evidence':''}],
            [{'name':'태그','category_id':None,'source_text':'원문 변경 시도'}]]
        for rows in bads:
            with self.assertRaises(ValueError):self.save(rows)
        with self.assertRaises(ValueError):self.save([],revision=True)
        with self.assertRaises(ValueError):self.edits.card_id('approved-310')
        self.assertEqual(self.edits.latest(self.card['card_id'])['revision'],0)
        self.assertEqual(self.app.baseline.cards(),self.original)

    def test_duplicate_prompt_ids_are_not_merged_by_manual_tag_edit(self):
        groups={}
        for c in self.original:groups.setdefault(c['source_text_sha256'],[]).append(c)
        pair=next(v for v in groups.values() if len(v)>1)
        self.save([],pair[0]);self.assertEqual(self.visible(pair[0]['id'])['tags'],[])
        for untouched in pair[1:]:self.assertEqual(self.visible(untouched['id'])['tags'],untouched['tags'])

    def test_operating_category_changes_do_not_reclassify_original_or_manual_tags(self):
        rows=payload(self.card['tags']);rows[0]['name']='사용자 보호 태그';self.save(rows)
        before=[c['tags'] for c in self.app.all_cards()]
        cat=rows[0]['category_id']
        self.app.action('/api/categories',{'operation':'deactivate','id':cat})
        self.app.action('/api/categories',{'operation':'rename','id':cat,'name':'운영 표시명만 변경'})
        self.assertEqual([c['tags'] for c in self.app.all_cards()],before)
        # A tag rename may retain its now-inactive existing category and evidence.
        rows=payload(self.visible()['tags']);rows[0]['name']='보호된 소속 유지';self.save(rows,revision=1)
        self.assertEqual(self.visible()['tags'][0]['category_column'],cat)

    def test_backup_and_restore_keep_original_and_all_user_editions(self):
        from test_baseline import synthetic_source
        source=self.root/'synthetic.hwpx';sha=synthetic_source(source,self.app.baseline.paths)
        with patch('bbolprom_engine.baseline.SOURCE_SHA',sha):
            review=self.app.prepare_baseline(source,'synthetic.hwpx')
            self.app.action('/api/baseline-commit',{'ticket':review['ticket']})
        self.original=copy.deepcopy(self.app.baseline.cards())
        self.app.library.manual('백업에 함께 들어갈 신규 카드',[('new.png',io.BytesIO(b'original-new-card-image-bytes'))])
        user_cards=self.app.library.cards()
        self.save([]);self.edits.restore(self.card['card_id'],0,1)
        archive=self.app.library.backup();destination=self.root/'restored';destination.mkdir()
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(z.read(name))
        restored=Application(destination)
        self.assertEqual(restored.baseline.cards(),self.original)
        self.assertEqual(restored.baseline_tag_edits.history(self.card['card_id']),self.edits.history(self.card['card_id']))
        self.assertEqual(next(c for c in restored.all_cards() if c['id']==self.card['id'])['tags'],self.card['tags'])
        self.assertEqual(restored.library.cards(),user_cards)
        self.assertEqual(restored.baseline.status()['linked_image_references'],531)
        for card in restored.baseline.cards()+restored.library.cards():
            for image in card['images']:
                self.assertEqual(hashlib.sha256((restored.library.root/image['path']).read_bytes()).hexdigest(),image['sha'])

    def test_history_and_original_SQL_guards_block_update_and_delete(self):
        self.save([])
        for sql in ('DELETE FROM baseline_tag_editions','UPDATE baseline_tag_editions SET revision=9',
                'DELETE FROM baseline_cards','UPDATE baseline_cards SET record_json=record_json'):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.app.library.connect() as c:c.execute(sql)
        self.assertEqual(len(self.edits.history(self.card['card_id'])),2)

    def test_diagnostic_separates_manual_editions_without_disclosing_user_tags(self):
        name='private-user-tag-sentinel-976871'
        self.save([{'name':name,'category_id':None,'evidence':''}])
        report=collect_local_diagnostic(self.app.baseline,self.root/'diagnostic.zip')
        self.assertEqual(report['counts']['tag_mappings'],8471)
        self.assertEqual(report['manual_tag_edits']['edited_card_count'],1)
        self.assertEqual(report['manual_tag_edits']['edition_count'],1)
        self.assertEqual(report['manual_tag_edits']['errors'],[])
        self.assertNotIn(name,json.dumps(report));self.assertEqual(report['integrity']['immutable_card_errors'],[])

    def test_corrupt_manual_history_is_detected_separately_from_fixed_original(self):
        self.save([])
        with self.app.library.connect() as c:
            c.execute('DROP TRIGGER baseline_tag_editions_no_update')
            c.execute("UPDATE baseline_tag_editions SET tags_sha='corrupt'")
        audit=audit_editions(self.app.library,self.app.baseline.records)
        self.assertTrue(audit['errors'])
        with self.assertRaisesRegex(ValueError,'무결성'):self.visible()
        self.assertEqual(self.app.baseline.cards(),self.original)

    def test_api_reference_uses_latest_user_edition_and_excludes_stale_card_history(self):
        name='사용자확정우주조종장소'
        rows=payload(self.card['tags']);rows[0]['name']=name;self.save(rows)
        cid=self.app.library.manual('새로운 장면 '+name+' '+self.card['source_text'],[])
        self.app.action('/api/settings',{'api':{'enabled':True,'consent':True,'endpoint':'https://api.openai.com/v1/chat/completions','model':'mock','use_approved_examples':True}})
        captured=[]
        def provider(request,config):
            captured.append(request)
            return json.dumps({'card_ref':request['card_ref'],'policy_version':'API-POLICY-1.0','tags':[],
                'unclassified':[],'create_categories':[],'direct_mutations':[]}),{}
        with patch('bbolprom_engine.api._live_transport',side_effect=provider):
            result=self.app.action('/api/analyze',{'id':cid})
        self.assertEqual(result['status'],'ok')
        example=next(e for e in captured[0]['approved_card_examples'] if e['approved_card_id']==self.card['card_id'])
        self.assertEqual(example['provenance']['user_tag_revision'],1)
        self.assertIn(name,[t['name'] for t in example['tag_mappings']])
        self.assertTrue(any(t['name']==name for t in captured[0]['existing_tags']))
        self.assertTrue(all(r['card_id']!=self.card['card_id'] for r in captured[0]['approved_processing_history']['decisions']))
        self.assertEqual(result['reference_audit']['example_revisions'][0]['revision'],1)
        self.assertEqual(self.visible()['tags'][0]['tag'],name)
        self.assertEqual(self.app.baseline.cards(),self.original)

    def test_example_opt_out_never_prepares_raw_catalog_and_API_cannot_analyze_baseline(self):
        self.save([]);cid=self.app.library.manual('새 프롬프트',[])
        self.app.action('/api/settings',{'api':{'enabled':True,'consent':True,'endpoint':'https://api.openai.com/v1/chat/completions','model':'mock'}})
        def provider(request,config):
            self.assertEqual(request['approved_card_examples'],[])
            return json.dumps({'card_ref':request['card_ref'],'policy_version':'API-POLICY-1.0','tags':[],
                'unclassified':[],'create_categories':[],'direct_mutations':[]}),{}
        with patch.object(self.edits,'reference_catalog',side_effect=AssertionError('raw examples must stay off')),patch('bbolprom_engine.api._live_transport',side_effect=provider):
            self.assertEqual(self.app.action('/api/analyze',{'id':cid})['status'],'ok')
            with self.assertRaisesRegex(ValueError,'신규 등록 카드'):self.app.action('/api/analyze',{'id':self.card['id']})
        self.assertEqual(self.visible()['tags'],[])


class BaselineManualHTTP(unittest.TestCase):
    setUp=test_app_v3.LocalHTTPApplication.setUp
    tearDown=test_app_v3.LocalHTTPApplication.tearDown
    request=test_app_v3.LocalHTTPApplication.request

    def test_authenticated_manual_endpoint_history_restore_and_bad_fields(self):
        data={'id':'approved-1','tags':[],'expected_revision':0}
        self.assertEqual(self.request('POST','/api/baseline-tags',data,authorized=False)[0],403)
        self.assertEqual(self.request('POST','/api/baseline-tags',data,headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.request('POST','/api/baseline-tags',dict(data,source_text='forbidden'))[0],400)
        self.assertEqual(self.request('POST','/api/baseline-tags',data)[1]['revision'],1)
        history=self.request('POST','/api/baseline-tag-history',{'id':'approved-1'})[1]
        self.assertEqual([v['revision'] for v in history['versions']],[1,0])
        self.assertEqual(self.request('POST','/api/baseline-tag-restore',{'id':'approved-1','target_revision':0,'expected_revision':1})[0],200)
        self.assertEqual(self.request('POST','/api/analyze',{'id':'approved-1'})[0],400)


if __name__=='__main__':unittest.main()
