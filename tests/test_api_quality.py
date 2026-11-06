"""Contract tests with neutral synthetic responses, not model-quality claims."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from bbolprom_engine.app import Application
from bbolprom_engine.api import evidence_spans
from bbolprom_engine.api_engine import quality, retrieval, reference_reader
from bbolprom_engine.xlsx_export import export_xlsx


CATS = [{'id': c, 'name': c, 'definition': '원문에 명시된 검색 개념', 'enabled': True}
        for c in ['C', 'D', 'E', 'F', 'G', 'H', 'I', 'appearance']]


def candidate(label, quote, category='appearance', disposition='new', ident=None):
    return {'name': label, 'category_id': category, 'category_status': 'classified',
            'disposition': disposition, 'existing_tag_id': ident,
            'evidence_text': [quote], 'reason': 'synthetic exact source assertion'}


class QualityReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(Path(self.temp.name) / 'library')
        self.engine = self.app.new_card_engine
        self.standards = retrieval.index(reference_reader.read(self.app.library.db))

    def run_result(self, text, tags=(), pending=(), focus=''):
        cid = self.app.library.manual(text, [])
        captured = []
        def transport(req):
            captured.append(copy.deepcopy(req))
            return {'card_ref': req['card_ref'], 'policy_version': 'API-POLICY-1.0',
                    'tags': copy.deepcopy(list(tags)), 'unclassified': copy.deepcopy(list(pending)),
                    'create_categories': [], 'direct_mutations': []}
        result = self.engine.analyze(cid, CATS, transport=transport, review_focus=focus)
        return cid, result, captured[0]

    def standard(self, label):
        return next(t for t in self.standards.values() if t['name'] == label)

    def test_explicit_standard_reuse_keeps_current_category_and_original_proposal(self):
        std = self.standard('하체 근육 발달')
        self.assertEqual(std['category_id'], 'I')
        cid, result, _ = self.run_result('하체 근육 발달이 명시된 성인 인물.', [
            candidate(std['name'], '하체 근육 발달', ident=std['id'], disposition='existing')])
        self.assertEqual(result['status'], 'ok')
        saved = self.engine.repo.snapshot(cid)['tags'][0]
        self.assertEqual(saved['category_id'], 'I')
        self.assertEqual(saved['api_proposals'][0]['category_id'], 'appearance')
        self.assertEqual(saved['standard_reference']['id'], std['id'])
        self.assertTrue(saved['normalization_notes'])

    def test_missing_evidence_does_not_get_repaired_into_classified(self):
        std = self.standard('큰 눈')
        _, result, _ = self.run_result('성인 인물의 정면 구도.', [
            candidate(std['name'], 'large eyes', ident=std['id'], disposition='existing')])
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['tags'])
        self.assertFalse(result['unclassified'][0]['spans'])

    def test_explicit_pending_is_not_auto_approved_by_matching_standard_name(self):
        raw = candidate('큰 눈', 'large eyes', None, 'unclassified')
        raw['category_status'] = 'unclassified'
        _, result, _ = self.run_result('An adult with large eyes.', pending=[raw])
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['unclassified'][0]['category_id'])

    def test_wrong_existing_name_or_id_still_fails_validation(self):
        std = self.standard('큰 눈')
        _, result, _ = self.run_result('An adult with large eyes.', [
            candidate('다른 의미', 'large eyes', ident=std['id'], disposition='existing')])
        self.assertEqual(result['status'], 'invalid_response')

    def test_approved_synonym_reuses_canonical_E_tag_and_keeps_exact_offsets(self):
        text = '😀 An adult with white pedicure.'
        _, result, _ = self.run_result(text, [candidate('흰색 페디큐어', 'white pedicure')])
        tag = result['tags'][0]
        self.assertEqual((tag['name'], tag['category_id']), ('하얀 패디큐어', 'E'))
        self.assertEqual(tag['api_proposals'][0]['name'], '흰색 페디큐어')
        self.assertEqual(tag['spans'], evidence_spans(text, ['white pedicure']))

    def test_synonym_without_color_evidence_is_not_forced_to_existing_standard(self):
        _, result, _ = self.run_result('An adult with pedicure.', [candidate('흰색 페디큐어', 'pedicure')])
        self.assertEqual(result['tags'][0]['name'], '흰색 페디큐어')
        self.assertNotIn('standard_reference', result['tags'][0])

    def test_negative_sections_excluded_while_ordinary_negation_is_preserved(self):
        text = '안경은 착용하지 않았다.\nnegative: red hair, earrings'
        cid, result, request = self.run_result(text, [candidate('안경 미착용', '안경은 착용하지 않았다.', 'E'),
            candidate('빨간 머리', 'red hair'), candidate('귀걸이', 'earrings', 'E')])
        self.assertEqual([t['tag'] for t in result['tags']], ['안경 미착용'])
        self.assertEqual(len(result['quality_audit']['excluded_candidates']), 2)
        self.assertTrue(request['new_card_engine']['review']['excluded_negative_sections'])
        self.assertEqual(self.engine.repo.snapshot(cid)['text'], text)

    def test_negative_extends_to_end_unless_explicit_positive_header(self):
        text = 'An adult.\nnegative: red hair, 추가 긍정처럼 보이는 문장\npositive: blue jacket'
        _, result, _ = self.run_result(text, [candidate('빨간 머리', 'red hair'),
            candidate('문장 후보', '추가 긍정처럼 보이는 문장'), candidate('파란 상의', 'blue jacket', 'E')])
        self.assertEqual([t['tag'] for t in result['tags']], ['파란 상의'])

    def test_negative_only_repeated_evidence_does_not_return_as_pending_tag(self):
        _, result, _ = self.run_result('An adult.\nnegative: red hair, red hair', [candidate('빨간 머리', 'red hair')])
        self.assertFalse(result['tags'])
        self.assertFalse(result['unclassified'])
        self.assertEqual(len(result['quality_audit']['excluded_candidates']), 1)

    def test_one_positive_occurrence_is_not_ambiguous_because_of_negative_duplicates(self):
        text = '😀 An adult with red hair.\nnegative: red hair, red hair'
        _, result, _ = self.run_result(text, [candidate('빨간 머리', 'red hair')])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['tags'][0]['spans']), 1)
        self.assertEqual(result['tags'][0]['spans'][0]['start_cp'], text.index('red hair'))
        self.assertNotIn('evidence_ambiguous', result['tags'][0])

    def test_evidence_crossing_negative_boundary_is_pending_not_silently_deleted(self):
        text = 'An adult with red hair.\nnegative: blue jacket'
        _, result, _ = self.run_result(text, [candidate('복합 후보', text)])
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['unclassified'][0]['spans'])
        self.assertIn('경계', result['unclassified'][0]['reason'])

    def test_user_protected_tag_survives_negative_filter_while_API_tag_is_excluded(self):
        text = 'An adult.\nnegative: red hair'
        cid = self.app.library.manual(text, [])
        manual = {'tag': '사용자 검수 메모', 'category_id': 'I', 'category_column': 'I',
                  'spans': [], 'source': 'user_edit'}
        self.engine.repo.manual(cid, [manual])
        def transport(request):
            return {'card_ref': cid, 'policy_version': 'API-POLICY-1.0', 'tags': [candidate('빨간 머리', 'red hair')],
                    'unclassified': [], 'create_categories': [], 'direct_mutations': []}
        self.engine.analyze(cid, CATS, transport=transport)
        self.assertEqual(self.engine.repo.snapshot(cid)['tags'], [manual])

    def test_synonym_normalization_does_not_resurrect_a_user_removed_alias(self):
        text = 'An adult with white pedicure.'
        cid = self.app.library.manual(text, [])
        manual = {'tag': '흰색 페디큐어', 'category_id': 'appearance', 'category_column': 'appearance',
                  'spans': [], 'source': 'user_edit'}
        self.engine.repo.manual(cid, [manual])
        self.engine.repo.manual(cid, [])
        def transport(request):
            return {'card_ref': cid, 'policy_version': 'API-POLICY-1.0', 'tags': [candidate('흰색 페디큐어', 'white pedicure')],
                    'unclassified': [], 'create_categories': [], 'direct_mutations': []}
        self.engine.analyze(cid, CATS, transport=transport)
        self.assertFalse(self.engine.repo.snapshot(cid)['tags'])

    def test_protected_user_alias_is_not_duplicated_by_canonical_API_tag(self):
        text = 'An adult with white pedicure.'
        cid = self.app.library.manual(text, [])
        manual = {'tag': '흰색 페디큐어', 'category_id': 'appearance', 'category_column': 'appearance',
                  'spans': [], 'source': 'user_edit'}
        self.engine.repo.manual(cid, [manual])
        def transport(request):
            return {'card_ref': cid, 'policy_version': 'API-POLICY-1.0', 'tags': [candidate('하얀 패디큐어', 'white pedicure', 'E')],
                    'unclassified': [], 'create_categories': [], 'direct_mutations': []}
        self.engine.analyze(cid, CATS, transport=transport)
        self.assertEqual(self.engine.repo.snapshot(cid)['tags'], [manual])

    def test_review_focus_reaches_request_without_adding_source_features(self):
        focus = '얼굴·헤어·체형·피부 대비, 관계·시점 점검'
        cid, result, request = self.run_result('A person reads a brochure in a cafe.', focus=focus)
        self.assertEqual(request['new_card_engine']['review']['review_focus'], focus)
        self.assertEqual(self.engine.repo.snapshot(cid)['text'], request['prompt_text'])
        self.assertFalse(result['tags'])
        self.assertEqual(self.app.api_budget.status()['calls'], 0)

    def test_reviewed_standard_IDs_are_supplied_even_when_general_ranking_omits_them(self):
        _, result, request = self.run_result('An adult with large open-looking eyes and developed thigh muscles.')
        names={t['name'] for t in request['existing_tags']}
        self.assertIn('큰 눈',names)
        self.assertIn('하체 근육 발달',names)
        self.assertLessEqual(len(request['existing_tags']),100)
        self.assertFalse(result['tags'])

    def test_negative_only_cues_do_not_become_priority_reference_hints(self):
        hints=quality.identity_hints('An adult.\nnegative: large eyes, muscular lower body, white pedicure',self.standards)
        self.assertFalse(hints)

    def test_review_focus_settings_validate_without_saving_keys(self):
        for bad in [[], 'a' * 2001, 'sk-synthetic-secret']:
            with self.assertRaises(ValueError): self.app.action('/api/settings', {'api': {'review_focus': bad}})
        self.app.action('/api/settings', {'api': {'review_focus': '근육·피부 대비'}})
        self.assertEqual(self.app.library.get_setting('api')['review_focus'], '근육·피부 대비')

    def test_focus_change_during_provider_call_makes_result_stale(self):
        cid = self.app.library.manual('An adult in a blue jacket.', [])
        def transport(request):
            self.app.action('/api/settings', {'api': {'review_focus': 'changed'}})
            return {'card_ref': cid, 'policy_version': 'API-POLICY-1.0', 'tags': [candidate('푸른 상의', 'blue jacket', 'E')],
                    'unclassified': [], 'create_categories': [], 'direct_mutations': []}
        result = self.engine.analyze(cid, CATS, transport=transport)
        self.assertEqual(result['status'], 'stale_reference')
        self.assertFalse(self.engine.repo.snapshot(cid)['tags'])

    def test_fixed_baseline_and_manual_user_tags_remain_unchanged(self):
        before = copy.deepcopy(self.app.baseline.cards())
        edits = self.app.baseline_tag_edits.editions()
        self.run_result('An adult in a blue jacket.\nnegative: red hair', [candidate('빨간 머리', 'red hair')])
        self.assertEqual(self.app.baseline.cards(), before)
        self.assertEqual(self.app.baseline_tag_edits.editions(), edits)
        self.assertEqual(self.app.baseline.status()['registered_cards'], 309)

    def test_xlsx_fourth_sheet_contains_original_proposal_reason_and_standard(self):
        std = self.standard('하체 근육 발달')
        cid, _, _ = self.run_result('하체 근육 발달이 명시된 성인 인물.', [
            candidate(std['name'], '하체 근육 발달', ident=std['id'], disposition='existing')])
        path = Path(self.temp.name) / 'review.xlsx'
        export_xlsx(self.app.all_cards(), path)
        ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(path) as z:
            self.assertIn('태그검수', z.read('xl/workbook.xml').decode())
            sheet = ET.fromstring(z.read('xl/worksheets/sheet4.xml'))
            rows = [[t.text or '' for t in r.findall('.//m:t', ns)] for r in sheet.findall('m:sheetData/m:row', ns)]
        row = next(r for r in rows[1:] if r[0] == cid)
        self.assertEqual(row[2], 'I')
        self.assertEqual(json.loads(row[4])[0]['category_id'], 'appearance')
        self.assertEqual(row[7], std['id'])
        # Older fixed tags did not store a model proposal; do not invent one.
        original = next(r for r in rows[1:] if r[0] == 'approved-1')
        self.assertEqual(original[4], '')


if __name__ == '__main__':
    unittest.main()
