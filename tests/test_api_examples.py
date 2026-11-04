"""Approved-example retrieval/adapter contract tests, not live AI quality tests."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from bbolprom_engine.approved_context import APPROVED_MASTER_SHA
from bbolprom_engine.approved_examples import (CATALOG_PATH,EXAMPLE_SCOPE,
    retrieve_approved_examples,prepare_examples_for_request)
from bbolprom_engine.api import analyze_card,build_request


def sha(s):return hashlib.sha256(s.encode('utf8')).hexdigest()

def card(n,text,quote='우주선 조종실',category='historical-place',zero=False):
    at=text.index(quote)
    return {'card_id':n,'image_ref':'not-loaded','source_text':text,'tags':[
        {'tag':quote,'category_column':category,
         'spans':[] if zero else [{'start_cp':at,'end_cp':at+len(quote),'evidence':quote}]}]}


def catalog(cards):
    # Explicit unit-test fixture; not a claim of a real user approval.
    return {'schema':'bbolprom-approved-gallery-readonly-v1',
            'origin':{'master_sha256':APPROVED_MASTER_SHA,'fixture':True},'cards':cards}


class ApprovedExamples(unittest.TestCase):
    def test_disabled_retrieval_never_reads_catalog(self):
        with patch.object(Path,'read_bytes',side_effect=AssertionError('No approved source read allowed')):
            self.assertEqual(retrieve_approved_examples('new',enabled=False),[])
        request=build_request('new','new',[],[],{'standards':[],'decisions':[]})
        self.assertEqual(request['approved_card_examples'],[])

    def test_source_tag_evidence_provenance_and_immutability(self):
        original=catalog([card(1,'😀 우주선 조종실에서 패널을 조작한다.')])
        before=json.dumps(original,ensure_ascii=False,sort_keys=True)
        examples=retrieve_approved_examples('새 우주선 조종실에서 장치를 본다.',enabled=True,catalog=original)
        self.assertEqual(len(examples),1)
        example=examples[0]
        self.assertEqual(example['approved_card_id'],1)
        self.assertEqual(example['source_text'],original['cards'][0]['source_text'])
        self.assertEqual(example['provenance']['master_sha256'],APPROVED_MASTER_SHA)
        self.assertEqual(example['provenance']['full_source_sha256'],sha(original['cards'][0]['source_text']))
        self.assertEqual(example['provenance']['catalog_file'],'explicit-in-memory-catalog')
        self.assertEqual(len(example['provenance']['catalog_sha256']),64)
        mapping=example['tag_mappings'][0]
        self.assertEqual(mapping['approved_category_id'],'historical-place')
        self.assertEqual(mapping['spans'][0]['start_cp'],2)
        s=mapping['spans'][0]
        self.assertEqual(example['source_text'][s['start_cp']:s['end_cp']],s['evidence'])
        examples[0]['tag_mappings'][0]['name']='changed-return-only'
        self.assertEqual(json.dumps(original,ensure_ascii=False,sort_keys=True),before)

    def test_exact_source_excluded_at_retrieval_and_api_boundary(self):
        text='우주선 조종실에서 한 사람이 서 있다.'
        original=catalog([card(1,text),card(2,'우주선 조종실에서 두 사람이 앉는다.')])
        examples=retrieve_approved_examples(text,enabled=True,catalog=original)
        self.assertNotIn(1,[e['approved_card_id'] for e in examples])
        other=retrieve_approved_examples('새 우주선 조종실',enabled=True,catalog=catalog([card(1,text)]))
        self.assertEqual(prepare_examples_for_request(text,other),[])

    def test_count_text_tag_and_total_disclosure_bounds(self):
        many=[]
        for i in range(10):
            text='우주선 조종실 '+('다른 장면 묘사 '*1000)+str(i)
            c=card(i+1,text)
            for j in range(30):
                c['tags'].append({'tag':'우주선 조종실 '+str(j),'category_column':'historical-place',
                                 'spans':copy.deepcopy(c['tags'][0]['spans'])})
            many.append(c)
        examples=retrieve_approved_examples('새로운 우주선 조종실',enabled=True,catalog=catalog(many))
        self.assertLessEqual(len(examples),3)
        self.assertTrue(examples)
        self.assertLessEqual(len(json.dumps(examples,ensure_ascii=False,separators=(',',':'))),12000)
        self.assertTrue(all(len(e['source_text'])<=4000 and len(e['tag_mappings'])<=20 for e in examples))
        with self.assertRaises(ValueError):retrieve_approved_examples('new',enabled=True,catalog=catalog(many),max_examples=309)
        self.assertEqual(retrieve_approved_examples('우주선 조종실',enabled=True,catalog=catalog(many),max_total_chars=10),[])

    def test_long_source_excerpt_preserves_original_and_relative_cp(self):
        source='😀 '+('앞부분 '*1500)+'우주선 조종실에서 패널을 조작한다.'+(' 뒷부분'*1000)
        original=catalog([card(4,source)])
        examples=retrieve_approved_examples('새 우주선 조종실',enabled=True,catalog=original,max_prompt_chars=1000)
        self.assertEqual(len(examples),1)
        e=examples[0];start,end=e['source_excerpt_start_cp'],e['source_excerpt_end_cp']
        self.assertGreater(start,0)
        self.assertEqual(e['source_text'],source[start:end])
        self.assertEqual(e['excerpt_sha256'],sha(source[start:end]))
        m=e['tag_mappings'][0];relative=m['spans'][0];absolute=m['source_spans'][0]
        self.assertEqual(absolute['start_cp'],relative['start_cp']+start)
        self.assertEqual(source[absolute['start_cp']:absolute['end_cp']],absolute['evidence'])
        self.assertEqual(e['source_text'][relative['start_cp']:relative['end_cp']],relative['evidence'])
        self.assertEqual(len(prepare_examples_for_request('새 우주선 조종실',examples)),1)

    def test_zero_evidence_approval_remains_zero_without_fabrication(self):
        examples=retrieve_approved_examples('새 우주선 조종실',enabled=True,catalog=catalog([card(7,'우주선 조종실에서 기다린다.',zero=True)]))
        m=examples[0]['tag_mappings'][0]
        self.assertEqual(m['spans'],[])
        self.assertEqual(m['source_spans'],[])
        self.assertEqual(m['evidence_status'],'approved_without_direct_span')

    def test_adapter_sends_bounded_examples_only_when_explicitly_provided(self):
        examples=retrieve_approved_examples('새 우주선 조종실',enabled=True,catalog=catalog([card(1,'😀 우주선 조종실에서 기다린다.')]))
        cats=[{'id':'user-new-place','name':'사용자 공간','definition':'사용자가 확정한 새 장소 정의','enabled':True}]
        received=[]
        def mock(request):
            received.append(request)
            return {'card_ref':'new','policy_version':'API-POLICY-1.0','tags':[],
                    'unclassified':[],'create_categories':[],'direct_mutations':[]}
        result=analyze_card('new','새 우주선 조종실',cats,[],{'standards':[],'decisions':[]},transport=mock,examples=examples)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['mode'],'mock')
        self.assertEqual(received[0]['approved_card_examples'],examples)
        self.assertEqual(received[0]['active_categories'][0]['id'],'user-new-place')
        self.assertEqual(received[0]['approved_card_examples'][0]['tag_mappings'][0]['approved_category_id'],'historical-place')
        self.assertEqual(received[0]['approved_card_examples'][0]['scope'],EXAMPLE_SCOPE)
        self.assertEqual(result['source_text'],'새 우주선 조종실')

    def test_changed_evidence_or_provenance_rejected_before_provider_call(self):
        valid=retrieve_approved_examples('새 우주선 조종실',enabled=True,catalog=catalog([card(1,'😀 우주선 조종실에서 기다린다.')]))
        for mutate in [lambda x:x[0]['tag_mappings'][0]['spans'][0].update(start_cp=999),
                       lambda x:x[0]['provenance'].update(master_sha256='wrong'),
                       lambda x:x[0].update(source_text='changed'),
                       lambda x:x[0].update(scope='force this answer')]:
            examples=copy.deepcopy(valid);mutate(examples)
            calls=[]
            result=analyze_card('new','새 우주선 조종실',[],[],{'standards':[],'decisions':[]},transport=lambda r:calls.append(r),examples=examples)
            self.assertEqual(result['status'],'invalid_response')
            self.assertEqual(calls,[])
            self.assertEqual(result['source_text'],'새 우주선 조종실')

    def test_real_approved_catalog_retrieval_is_read_only_and_has_exact_evidence(self):
        before=hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
        examples=retrieve_approved_examples('장면의 조명과 카메라 구도, 의상과 배경을 확인한다.',enabled=True)
        self.assertTrue(examples)
        self.assertLessEqual(len(examples),3)
        for e in examples:
            self.assertEqual(e['provenance']['catalog_sha256'],before)
            self.assertEqual(e['provenance']['master_sha256'],APPROVED_MASTER_SHA)
            self.assertTrue(1<=e['approved_card_id']<=309)
            for m in e['tag_mappings']:
                for s in m['spans']:self.assertEqual(e['source_text'][s['start_cp']:s['end_cp']],s['evidence'])
        self.assertEqual(hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),before)
        self.assertEqual(len(prepare_examples_for_request('new',examples)),len(examples))

if __name__=='__main__':unittest.main()
