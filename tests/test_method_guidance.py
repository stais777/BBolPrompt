"""Tests of method preservation and request wiring, NOT live AI correctness."""
import copy,hashlib,json,unittest
from pathlib import Path
from bbolprom_engine.method_guidance import load_method_guidance,prepare_method_guidance,METHOD_PATH
from bbolprom_engine.approval_history import load_approval_history
from bbolprom_engine.api import analyze_card

class MethodGuidance(unittest.TestCase):
 def test_reconstructed_method_keeps_semantic_axes_vertical_horizontal_and_highlight_rules(self):
  data=load_method_guidance()
  self.assertEqual(len(data['semantic_axes']),10)
  self.assertEqual(len(data['processing_steps']),7)
  self.assertEqual(len(data['normalization_phases']),13)
  self.assertEqual(len(data['highlight_invariants']),14)
  text=' '.join(c['text'] for key in ('semantic_axes','normalization_phases','highlight_invariants') for c in data[key])
  for meaning in ('부정','과거','누가 행위를','spans=[]'):
   self.assertIn(meaning,text)
  self.assertIn('분화',text);self.assertIn('같은 카드',text)
  self.assertIn('코드포인트',text)
  self.assertIn('not',data['limits'][0])
  self.assertEqual(len(data['historical_exceptions']),2)
  exception_text=' '.join(x['text'] for x in data['historical_exceptions'])
  self.assertIn('초기 제외 규칙만으로 삭제해서는 안 된다',exception_text)

 def test_source_lines_digests_scope_and_bounded_disclosure_are_explicit(self):
  data=load_method_guidance();before=METHOD_PATH.read_bytes()
  outgoing=prepare_method_guidance(data)
  self.assertLessEqual(len(json.dumps(outgoing,ensure_ascii=False,separators=(',',':'))),24000)
  self.assertEqual(len(outgoing['guidance_sha256']),64)
  self.assertIn('Current explicit user scope',outgoing['precedence'])
  for group in ('semantic_axes','processing_steps','normalization_phases','highlight_invariants','historical_exceptions'):
   for c in outgoing[group]:
    source=outgoing['sources'][c['provenance']['source_id']]
    self.assertEqual(source['kind'],'reconstructed_method_description')
    self.assertEqual(len(source['sha256']),64);self.assertGreater(c['provenance']['line'],0)
  self.assertEqual(METHOD_PATH.read_bytes(),before)

 def test_invalid_source_and_modified_schema_rejected_before_transmission(self):
  for mutate in [lambda d:d.update(master_sha256='wrong'),
   lambda d:d.update(extra_instruction='invented'),
   lambda d:next(iter(d['sources'].values())).update(sha256='not-a-digest'),
   lambda d:d['processing_steps'][0]['provenance'].update(source_id='missing'),
   lambda d:d.update(normalization_phases=[])]:
   data=load_method_guidance();mutate(data);calls=[]
   result=analyze_card('new','새 원문',[],[],{'standards':[],'decisions':[]},
       transport=lambda r:calls.append(r),method_guidance=data)
   self.assertEqual(result['status'],'invalid_response');self.assertEqual(calls,[])
   self.assertEqual(result['source_text'],'새 원문')

 def test_provider_gets_actual_method_and_approval_history_in_one_mock_request(self):
  captured=[]
  def provider(request):
   captured.append(request)
   return {'card_ref':'new','policy_version':'API-POLICY-1.0','tags':[],
    'unclassified':[],'create_categories':[],'direct_mutations':[]}
  text='새로운 프롬프트: 기내 좌석에 앉아 원형 의자를 바라본다.'
  result=analyze_card('new',text,[{'id':'user-place','name':'장소','definition':'사용자 정의 장소','enabled':True}],[],
    {'standards':[],'decisions':[]},transport=provider,approval_history=load_approval_history(),method_guidance=load_method_guidance())
  self.assertEqual(result['status'],'ok');self.assertEqual(result['mode'],'mock')
  req=captured[0];self.assertEqual(req['prompt_text'],text)
  self.assertEqual(len(req['tag_highlight_method']['semantic_axes']),10)
  self.assertEqual(len(req['approved_processing_history']['workflow']),8)
  self.assertEqual(req['active_categories'][0]['id'],'user-place')
  audit=result['reference_audit']['method_guidance']
  self.assertEqual(audit['guidance_sha256'],req['tag_highlight_method']['guidance_sha256'])
  self.assertEqual(len(audit['clause_ids']),46)
  self.assertEqual(audit['sources'],req['tag_highlight_method']['sources'])

 def test_user_scope_conflicts_are_reported_not_imported_as_new_engine_commands(self):
  report=json.loads((Path(__file__).parents[1]/'evaluation/method-handoff-analysis.json').read_text())
  self.assertEqual(report['method_package_files_hash_verified'],55)
  self.assertTrue(report['existing_catalog_text_tags_and_spans_match'])
  self.assertEqual(report['verbatim_actions'],287)
  self.assertFalse(report['actual_PT_reparsed']);self.assertFalse(report['live_API_called'])
  notes=json.dumps(report['discrepancies_and_scope_resolutions'],ensure_ascii=False)
  self.assertIn('665',notes);self.assertIn('495',notes)
  self.assertIn('1297',notes);self.assertIn('2573',notes)
  self.assertIn('Latest user scope governs',notes)
  live=json.dumps(load_method_guidance(),ensure_ascii=False)
  self.assertNotIn('665',live)

if __name__=='__main__':unittest.main()
