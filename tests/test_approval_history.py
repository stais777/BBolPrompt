"""Approval evidence/precedence tests. No live provider or PT quality claims."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bbolprom_engine.approval_history import load_approval_history,validate_history,retrieve_approval_history,HISTORY_PATH,LIVE_STATUSES
from bbolprom_engine.approved_context import APPROVED_MASTER_SHA
from bbolprom_engine.api import analyze_card,build_request
from tools.build_approval_history import approved_status,operation,targets

class ApprovalHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.history=load_approval_history()

    def test_explicit_approval_status_never_promotes_pending_words(self):
        for value in ['미승인','신규·미승인','사용자 승인 대기','사용자 미결정','UNAPPROVED','not approved','disapproved','승인 철회','승인 취소','pending approval','미확정']:
            with self.subTest(value=value):self.assertFalse(approved_status(value))
        for value in ['사용자 승인','승인 완료','사용자 최종 확정 — 수행/준비 충돌 해결','사용자 일괄 승인 · 본 엑셀 반영 대기']:
            self.assertTrue(approved_status(value))

    def test_all_original_workflow_steps_and_exact_policy_provenance_are_available(self):
        h=self.history
        self.assertEqual(h['master_sha256'],APPROVED_MASTER_SHA)
        self.assertEqual(len(h['workflow']),8);self.assertEqual(len(h['constraints']),19)
        self.assertEqual(len(h['records']),6416)
        for item in h['workflow']+h['constraints']:
            self.assertIn(item['provenance']['source_id'],h['sources'])
            self.assertGreater(item['provenance']['line'],0)
        coverage=json.loads((Path(__file__).parents[1]/'evaluation/approval-history-coverage.json').read_text())
        self.assertEqual(coverage['master_sheets_inventoried'],106)
        self.assertEqual(coverage['selected_sheets'],24)

    def test_highlight_actions_include_early_nested_history_and_final18_approval(self):
        cases=[r for r in self.history['records'] if r['family']=='highlight_decision']
        self.assertEqual(len(cases),287)
        self.assertTrue(all(r['status']=='final_confirmed' for r in cases))
        self.assertTrue(any(r['card_id']==3 and r['operation']=='delete' for r in cases))
        final18=[r for r in cases if r['card_id']>=296]
        self.assertEqual(len(final18),12)
        self.assertTrue(all(self.history['sources'][r['provenance']['source_id']]['kind']=='final_highlight_approval' for r in final18))
        empty_kept=[r for r in final18 if r['operation']=='keep']
        self.assertEqual(len(empty_kept),7)
        moved=[r for r in cases if r['card_id']==151 and r['operation']=='move']
        self.assertEqual({r['after'][0]['category_id'] for r in moved},{'G','H'})

    def test_stale_pending_row_status_keeps_proof_and_final_mapping_resolution(self):
        cases=[r for r in self.history['records'] if r.get('source_status_conflict')]
        self.assertEqual(len(cases),9)
        for r in cases:
            self.assertEqual(r['status'],'final_confirmed')
            self.assertTrue(r['approval_proofs'])
            proof=r['approval_proofs'][0]
            self.assertEqual(proof['approved_count'],9)
            self.assertEqual(self.history['sources'][proof['source_id']]['kind'],'approval_handoff')
            self.assertIn('current_card_tags',r)

    def test_column_epoch_and_explicit_later_changes_are_not_silently_rewritten(self):
        old=next(r for r in self.history['records'] if r['family']=='vertical_props' and r['card_id']==3)
        self.assertEqual(old['before']['category_id'],'I')
        self.assertIn('H태그',' '.join(old['fields']))
        self.assertEqual(old['status'],'historical_conflict')
        self.assertEqual(old['after'][0]['name'],'의자')
        self.assertTrue(old['final_comparison']['supported_later_decision_ids'])
        self.assertNotIn('의자',old['current_card_tags']['I'])

    def test_retrieval_excludes_conflicts_pending_and_keeps_final_companions(self):
        before=hashlib.sha256(HISTORY_PATH.read_bytes()).hexdigest()
        r=retrieve_approval_history('원형 의자와 유산소 운동기구, 시트 위에 옷가지가 있다.',self.history)
        self.assertEqual(len(r['workflow']),8)
        self.assertLessEqual(len(r['decisions']),12)
        self.assertLessEqual(len(json.dumps(r,ensure_ascii=False,separators=(',',':'))),32000)
        by_id={x['id']:x for x in self.history['records']};chosen={x['id'] for x in r['decisions']}
        self.assertTrue(chosen)
        for rec in r['decisions']:
            self.assertIn(rec['status'],LIVE_STATUSES)
            for ident in rec.get('later_card_decision_ids',[]):
                if by_id[ident]['status'] in LIVE_STATUSES:self.assertIn(ident,chosen)
            self.assertIn(rec['provenance']['source_id'],r['sources'])
        self.assertEqual(before,hashlib.sha256(HISTORY_PATH.read_bytes()).hexdigest())

    def test_new_api_request_replaces_old_partial_decisions_and_keeps_dynamic_categories(self):
        legacy={'standards':[],'decisions':[{'fields':{'bad':'legacy pending'},'id':'bad'}]}
        categories=[{'id':'user-place','name':'사용자 장소','definition':'장면의 실제 장소','enabled':True}]
        captured=[]
        def transport(request):
            captured.append(request)
            return {'card_ref':'new','policy_version':'API-POLICY-1.0','tags':[],
                    'unclassified':[],'create_categories':[],'direct_mutations':[]}
        text='새 원문: 유산소 운동기구가 놓인 공간'
        result=analyze_card('new',text,categories,[],legacy,transport=transport,approval_history=self.history)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['mode'],'mock')
        req=captured[0];history=req['approved_processing_history']
        self.assertEqual(req['approved_normalization_examples'],[])
        self.assertTrue(history['decisions'])
        self.assertNotIn('bad',{r['id'] for r in history['decisions']})
        self.assertEqual(req['active_categories'][0]['id'],'user-place')
        self.assertEqual(result['source_text'],text)
        self.assertEqual(result['reference_audit']['decision_ids'],[r['id'] for r in history['decisions']])
        self.assertEqual(len(result['reference_audit']['workflow_ids']),8)

    def test_invalid_provenance_or_unknown_status_rejected(self):
        for mutation in [lambda d:d.update(master_sha256='wrong'),
                         lambda d:d['workflow'][0]['provenance'].update(source_id='unknown'),
                         lambda d:d['records'][0].update(status='approved by guessing'),
                         lambda d:d['records'][0]['provenance'].update(row=-1)]:
            data=copy.deepcopy(self.history);mutation(data)
            with self.assertRaises(ValueError):validate_history(data)

    def test_duplicated_historical_rule_labels_have_distinct_source_row_ids(self):
        rules=[r for r in self.history['records'] if r['family']=='approved_rule' and r['fields'].get('규칙ID')=='2차-N01']
        self.assertEqual(len(rules),2)
        self.assertNotEqual(rules[0]['id'],rules[1]['id'])
        self.assertNotEqual(rules[0]['provenance']['row'],rules[1]['provenance']['row'])
        moved=next(r for r in rules if r['fields']['기준 종류']=='대분류 이동')
        self.assertEqual(moved['before']['category_id'],'G')
        self.assertEqual(moved['after'][0]['category_id'],'H')

    def test_normalization_parses_actual_moved_targets_without_universal_replacement(self):
        self.assertEqual(operation('move'),'move')
        self.assertEqual(targets('H:다른 자세 / G:관계','I'),[
            {'category_id':'H','name':'다른 자세'},{'category_id':'G','name':'관계'}])
        self.assertEqual(targets('태그 삭제','I'),[])

if __name__=='__main__':unittest.main()
