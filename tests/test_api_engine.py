"""New-card engine integration with synthetic provider responses; no paid API."""
import copy,hashlib,json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from bbolprom_engine.app import Application
from bbolprom_engine.api import APIConfig,APIUnavailable,evidence_spans
from bbolprom_engine.api_engine import definitions,retrieval,reference_reader
from bbolprom_engine.api_engine.service import Engine
from bbolprom_engine.api_engine.repository import Repository,StaleResult
from bbolprom_engine.library import Library
from bbolprom_engine.baseline import load_dataset

CATS=[{'id':'F','name':'장소','definition':'실제로 명시된 장소','enabled':True}]
def tag(label='지하철역',quote='subway station',category='F'):
    return {'name':label,'disposition':'new','existing_tag_id':None,'category_id':category,
        'category_status':'classified','evidence_text':[quote],'reason':'synthetic exact source evidence'}
def provider(tags=(),unclassified=()):
    def transport(request):return {'card_ref':request['card_ref'],'policy_version':'API-POLICY-1.0',
        'tags':copy.deepcopy(list(tags)),'unclassified':copy.deepcopy(list(unclassified)),
        'create_categories':[],'direct_mutations':[]}
    return transport
def manual(label,text,quote=None):
    return {'tag':label,'name':label,'category_id':'F','category_column':'F','source':'user_edit',
        'spans':evidence_spans(text,[quote]) if quote else []}


class NewCardEngine(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.app=Application(self.root/'library');self.cid=self.app.library.manual('A person waits at a subway station.',[])
        self.engine=self.app.new_card_engine;self.repo=self.engine.repo

    def tags(self):return next(c['tags'] for c in self.app.library.cards() if c['id']==self.cid)
    def run_api(self,tags=(),**kw):return self.engine.analyze(self.cid,CATS,transport=provider(tags),**kw)

    def test_new_result_persists_but_baseline_records_and_user_editions_do_not_change(self):
        before=copy.deepcopy(self.app.baseline.cards());editions=self.app.baseline_tag_edits.editions()
        result=self.run_api([tag()]);self.assertEqual(result['status'],'ok');self.assertTrue(self.tags())
        self.assertEqual(self.app.baseline.cards(),before);self.assertEqual(self.app.baseline_tag_edits.editions(),editions)
        self.assertEqual(self.repo.summary()['api_runs'],1)

    def test_baseline_ids_and_exact_baseline_prompts_are_rejected_before_provider(self):
        calls=[]
        with self.assertRaises(ValueError):self.engine.analyze('approved-1',CATS,transport=lambda r:calls.append(r))
        cid=self.app.library.manual(self.app.baseline.records[0]['source_text'],[])
        with self.assertRaises(ValueError):self.engine.analyze(cid,CATS,transport=lambda r:calls.append(r))
        self.assertEqual(calls,[])

    def test_repository_authorizer_denies_baseline_manual_editions_media_and_source_writes(self):
        statements=["UPDATE baseline_cards SET record_json='{}' WHERE card_id=1",
            "DELETE FROM baseline_tag_editions","DELETE FROM baseline_image_links","DELETE FROM media",
            "UPDATE cards SET text='changed'","DROP TABLE baseline_cards","ATTACH DATABASE ':memory:' AS other"]
        for sql in statements:
            with self.repo.connect() as c:
                with self.assertRaises(sqlite3.DatabaseError,msg=sql):c.execute(sql)

    def test_manual_tags_survive_reanalysis_and_deleted_tags_are_not_resurrected(self):
        self.run_api([tag('old place')]);text=self.repo.snapshot(self.cid)['text']
        self.repo.manual(self.cid,[manual('my place',text,'subway station')])
        result=self.run_api([tag('old place'),tag('my place'),tag('new place')])
        self.assertEqual({t['tag'] for t in self.tags()},{'my place','new place'})
        self.assertEqual(next(t for t in self.tags() if t['tag']=='my place')['source'],'user_edit')
        self.assertEqual(result['engine_version'],'api-engine-1')

    def test_removed_manual_tag_can_be_explicitly_added_again(self):
        text=self.repo.snapshot(self.cid)['text'];t=manual('my place',text)
        self.repo.manual(self.cid,[t]);self.repo.manual(self.cid,[]);self.assertTrue(self.repo.snapshot(self.cid)['excluded'])
        self.repo.manual(self.cid,[t]);self.assertFalse(self.repo.snapshot(self.cid)['excluded'])
        self.run_api([]);self.assertEqual(self.tags()[0]['tag'],'my place')

    def test_preengine_unknown_tags_are_preserved_conservatively(self):
        self.app.library.save_analysis(self.cid,{'source_text':self.repo.snapshot(self.cid)['text'],
            'tags':[manual('previously saved',self.repo.snapshot(self.cid)['text'])],'status':'ok'})
        self.run_api([]);self.assertEqual(self.tags()[0]['tag'],'previously saved')

    def test_late_result_does_not_overwrite_concurrent_user_edits(self):
        def transport(request):
            self.repo.manual(self.cid,[manual('newest user edit',request['prompt_text'])])
            return provider([tag()])(request)
        r=self.engine.analyze(self.cid,CATS,transport=transport)
        self.assertEqual(r['status'],'stale_result');self.assertEqual(self.tags()[0]['tag'],'newest user edit')

    def test_source_change_during_analysis_prevents_old_highlights(self):
        def transport(request):
            self.app.library.edit_card(self.cid,'Changed source.',[])
            return provider([tag()])(request)
        r=self.engine.analyze(self.cid,CATS,transport=transport)
        self.assertEqual(r['status'],'stale_result');self.assertFalse(self.tags())

    def test_reference_edition_change_during_analysis_marks_result_stale(self):
        def transport(request):
            self.app.action('/api/baseline-tags',{'id':'approved-1','tags':[],'expected_revision':0})
            return provider([tag()])(request)
        r=self.engine.analyze(self.cid,CATS,transport=transport)
        self.assertEqual(r['status'],'stale_reference');self.assertFalse(self.tags())

    def test_provider_failure_or_bad_json_retains_previous_manual_tags(self):
        self.repo.manual(self.cid,[manual('keep me',self.repo.snapshot(self.cid)['text'])])
        for transport in (lambda r:'not json',lambda r:(_ for _ in ()).throw(APIUnavailable('synthetic timeout'))):
            r=self.engine.analyze(self.cid,CATS,transport=transport)
            self.assertIn(r['status'],('invalid_response','api_unavailable'));self.assertEqual(self.tags()[0]['tag'],'keep me')

    def test_repeated_short_quote_is_not_highlighted_at_arbitrary_occurrences(self):
        self.app.library.edit_card(self.cid,'😀 station beside the station.',[])
        r=self.run_api([tag('place','station')]);self.assertEqual(r['status'],'partial')
        self.assertEqual(self.tags()[0]['spans'],[]);self.assertIsNone(self.tags()[0]['category_id'])

    def test_longer_unique_quote_selects_context_after_emoji(self):
        self.app.library.edit_card(self.cid,'😀 station beside the station.',[])
        r=self.run_api([tag('place','the station')]);self.assertEqual(r['status'],'ok')
        span=self.tags()[0]['spans'][0];self.assertEqual(span['start_cp'],17)
        self.assertEqual(self.repo.snapshot(self.cid)['text'][span['start_cp']:span['end_cp']],'the station')

    def test_live_adapter_and_cost_gate_remain_in_charge(self):
        cfg=APIConfig(enabled=True,consent=True,endpoint='https://api.openai.com/v1/chat/completions',model='synthetic-model')
        r=self.engine.analyze(self.cid,CATS,config=cfg)
        self.assertEqual(r['status'],'api_unavailable');self.assertEqual(cfg.calls,0);self.assertFalse(self.tags())

    def test_bilingual_reference_reaches_request_without_raw_examples_when_disabled(self):
        requests=[]
        def transport(request):requests.append(copy.deepcopy(request));return provider()(request)
        self.engine.analyze(self.cid,CATS,transport=transport)
        self.assertTrue(any(t['name']=='지하철역' for t in requests[0]['existing_tags']))
        self.assertEqual(requests[0]['approved_card_examples'],[])
        self.assertEqual(requests[0]['new_card_engine']['related_user_corrections'],[])

    def test_correction_examples_are_opt_in_bounded_and_withdrawable(self):
        text=self.repo.snapshot(self.cid)['text'];self.repo.manual(self.cid,[manual('my station',text,'subway station')])
        other=self.app.library.manual('Another person waits at the subway station.',[]);captured=[]
        def transport(request):captured.append(copy.deepcopy(request));return provider()(request)
        self.engine.analyze(other,CATS,transport=transport,use_corrections=False)
        self.assertEqual(captured[-1]['new_card_engine']['related_user_corrections'],[])
        self.engine.analyze(other,CATS,transport=transport,use_corrections=True)
        rows=captured[-1]['new_card_engine']['related_user_corrections'];self.assertEqual(len(rows),1)
        self.assertLessEqual(len(json.dumps(rows,ensure_ascii=False)),8000)
        self.repo.correction_active(rows[0]['correction_id'],False)
        self.engine.analyze(other,CATS,transport=transport,use_corrections=True)
        self.assertEqual(captured[-1]['new_card_engine']['related_user_corrections'],[])
        self.assertEqual(self.tags()[0]['tag'],'my station')

    def test_new_manual_revision_supersedes_old_correction_and_text_change_excludes_it(self):
        self.repo.manual(self.cid,[manual('first',self.repo.snapshot(self.cid)['text'])]);old=self.repo.corrections()[0]['id']
        self.repo.manual(self.cid,[manual('latest',self.repo.snapshot(self.cid)['text'])])
        self.assertNotEqual(self.repo.corrections()[0]['id'],old);self.assertEqual(len(self.repo.corrections()),1)
        self.app.library.edit_card(self.cid,'Changed source.',[]);self.assertEqual(self.repo.corrections(),[])

    def test_tag_history_restore_is_separate_and_stale_restore_rejected(self):
        self.repo.manual(self.cid,[manual('first',self.repo.snapshot(self.cid)['text'])])
        version=self.repo.history(self.cid)[0]['id']
        self.repo.manual(self.cid,[manual('second',self.repo.snapshot(self.cid)['text'])]);snapshot=self.repo.snapshot(self.cid)
        self.repo.restore(self.cid,version,snapshot['token']);self.assertEqual(self.tags()[0]['tag'],'first')
        with self.assertRaises(StaleResult):self.repo.restore(self.cid,version,snapshot['token'])

    def test_invalid_manual_spans_roll_back_history_and_current_card(self):
        t=manual('bad',self.repo.snapshot(self.cid)['text']);before=self.repo.summary()
        t['spans']=[{'start_cp':0,'end_cp':4,'evidence':'wrong'}]
        with self.assertRaises(ValueError):self.repo.manual(self.cid,[t])
        self.assertEqual(self.repo.summary(),before);self.assertEqual(self.tags(),[])

    def test_tag_operations_do_not_copy_PT_or_recompress_vault_and_full_backup_contains_history(self):
        with patch.object(Library,'backup',side_effect=AssertionError('No full media archive per tag')):
            self.repo.manual(self.cid,[manual('manual',self.repo.snapshot(self.cid)['text'])]);self.run_api([])
        archive=self.app.library.backup()
        with zipfile.ZipFile(archive) as z:
            restored=self.root/'restore.sqlite3';restored.write_bytes(z.read('library.sqlite3'))
        with sqlite3.connect(restored) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM baseline_cards').fetchone()[0],309)
            self.assertEqual(c.execute('SELECT count(*) FROM api_tag_editions').fetchone()[0],2)
        self.assertTrue(list((self.app.library.root/'backup').glob('*.db-snapshot')))

    def test_drafts_are_not_active_until_explicit_confirmation_and_tokens_guard_updates(self):
        cats=self.app.categories();v=self.engine.definition_view(cats)
        self.assertFalse(definitions.effective(self.repo,cats));self.assertEqual(len(v['definitions']),7)
        items=[{k:c[k] for k in ('id','definition','include','exclude')} for c in v['definitions']]
        definitions.approve(self.repo,cats,items,v['token'])
        self.assertEqual(len(definitions.effective(self.repo,cats)),7)
        with self.assertRaises(ValueError):definitions.approve(self.repo,cats,items,v['token'])
        self.assertEqual(self.app.baseline.status()['registered_cards'],309)

    def test_baseline_manual_example_revisions_and_no_source_mutation(self):
        before=copy.deepcopy(self.app.baseline.cards());self.app.action('/api/baseline-tags',{'id':'approved-1','tags':[],'expected_revision':0})
        snapshot=reference_reader.read(self.repo.db)
        self.assertEqual(snapshot['cards'][0]['tags'],[]);self.assertEqual(snapshot['edited_card_ids'],[1])
        snapshot['cards'][1]['tags'].clear()
        self.assertEqual(self.app.baseline.cards(),before)

    def test_run_audit_failure_rolls_back_tags_and_history_atomically(self):
        self.repo.snapshot(self.cid);before=self.repo.summary()
        with self.app.library.connect() as c:
            c.execute("CREATE TRIGGER fail_run BEFORE INSERT ON api_runs BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.run_api([tag()])
        self.assertEqual(self.tags(),[]);self.assertEqual(self.repo.summary(),before)

    def test_correction_withdrawal_during_call_prevents_result_application(self):
        self.repo.manual(self.cid,[manual('my place',self.repo.snapshot(self.cid)['text'])])
        correction=self.repo.corrections()[0]['id'];other=self.app.library.manual('Another person at the subway station.',[])
        def transport(request):
            self.repo.correction_active(correction,False);return provider([tag()])(request)
        r=self.engine.analyze(other,CATS,transport=transport,use_corrections=True)
        self.assertEqual(r['status'],'stale_reference')
        self.assertEqual(self.repo.snapshot(other)['tags'],[])

    def test_unexpected_provider_exception_does_not_echo_payload_or_key(self):
        def transport(request):raise RuntimeError('private-source sk-not-a-real-key-secret-12839')
        r=self.engine.analyze(self.cid,CATS,transport=transport)
        self.assertEqual(r['status'],'provider_error');self.assertNotIn('12839',json.dumps(r));self.assertFalse(self.tags())

    def test_initial_tag_state_is_recoverable(self):
        self.repo.manual(self.cid,[manual('new manual',self.repo.snapshot(self.cid)['text'])])
        self.repo.restore(self.cid,'initial',self.repo.snapshot(self.cid)['token'])
        self.assertEqual(self.tags(),[]);self.assertEqual(self.repo.history(self.cid)[-1]['revision'],0)

    def test_external_card_restore_does_not_keep_stale_correction_in_future_requests(self):
        text=self.repo.snapshot(self.cid)['text'];self.repo.manual(self.cid,[manual('old manual',text)])
        self.assertTrue(self.repo.corrections())
        self.app.library.save_analysis(self.cid,{'source_text':text,'tags':[manual('restored other',text)],'status':'user_edited'})
        self.assertEqual(self.repo.corrections(),[])
        self.repo.snapshot(self.cid);self.assertEqual(self.repo.corrections(),[])

    def test_engine_diagnostic_contains_only_counts_statuses_and_hashes(self):
        from bbolprom_engine.api_engine.diagnostics import collect
        self.repo.manual(self.cid,[manual('private-tag-734128',self.repo.snapshot(self.cid)['text'])]);self.run_api([])
        report=collect(self.app.library);raw=json.dumps(report)
        self.assertEqual(report['counts']['api_runs'],1);self.assertEqual(len(report['ledger_sha256']),64)
        for secret in ('private-tag-734128','subway station',str(self.root),'sk-'):self.assertNotIn(secret,raw)

    def test_false_quote_cannot_regain_partial_highlights_through_context_refinement(self):
        self.app.library.edit_card(self.cid,'station beside station and a subway.',[])
        candidate=tag('place','station');candidate['evidence_text']=['station','subway','invented phrase']
        self.run_api([candidate]);self.assertEqual(self.tags()[0]['spans'],[])
        self.assertIsNone(self.tags()[0]['category_id'])

    def test_reference_change_in_last_gap_before_commit_is_checked_under_write_lock(self):
        original=self.repo.finish
        def changed(*args,**kwargs):
            self.app.action('/api/baseline-tags',{'id':'approved-1','tags':[],'expected_revision':0})
            return original(*args,**kwargs)
        with patch.object(self.repo,'finish',side_effect=changed):result=self.run_api([tag()])
        self.assertEqual(result['status'],'stale_reference');self.assertFalse(self.tags())

    def test_baseline_ui_and_registration_do_not_initialize_optional_api_engine(self):
        app=Application(self.root/'another-library')
        with patch('bbolprom_engine.api_engine.service.Engine',side_effect=AssertionError('not required')):
            self.assertEqual(app.state()['baseline']['registered_cards'],309)
            self.assertFalse(app.state()['api_engine']['initialized'])
        with app.library.connect() as c:self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='api_runs'").fetchone())


if __name__=='__main__':unittest.main()
