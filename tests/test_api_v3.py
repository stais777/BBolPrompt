"""Mock contract tests, never a live semantic-quality benchmark."""
import copy
import json
import os
import unittest
from unittest.mock import patch
from bbolprom_engine.api import (analyze_card,APIConfig,build_request,
    validate_response,evidence_spans,select_evidence_spans,APIValidationError,_live_transport)
from bbolprom_engine.approved_context import load_approved_context,retrieve_context
from bbolprom_engine.categories import CategoryManager

CATS=[{'id':'place','name':'장소','definition':'실제 장면의 물리적 장소','enabled':True},
      {'id':'prop','name':'소품','definition':'장면에서 사용하는 물건','enabled':True},
      {'id':'hidden','name':'비활성','definition':'사용하지 않음','enabled':False}]
TAGS=[{'id':'tag1','name':'우주선 조종실','category_id':'place'}]
CONTEXT={'schema':'bbolprom-approved-context-1','source_sha256':'fixture','standards':TAGS,'decisions':[]}

def tag(name='우주선 조종실',disposition='existing',ident='tag1',category='place',quotes=None,reason='원문 장소 명시'):
    return {'name':name,'disposition':disposition,'existing_tag_id':ident,'category_id':category,
            'category_status':'classified' if category else 'unclassified',
            'evidence_text':['우주선 조종실'] if quotes is None else quotes,'reason':reason}

def response(*tags):
    return {'card_ref':'new-1','policy_version':'API-POLICY-1.0','tags':list(tags),
            'unclassified':[],'create_categories':[],'direct_mutations':[]}

class APIContract(unittest.TestCase):
    def call(self,res,text='😀 우주선 조종실에서 패널을 조작한다.',cats=None):
        return analyze_card('new-1',text,cats or CATS,TAGS,CONTEXT,transport=lambda req:copy.deepcopy(res))

    def test_unicode_exact_multiple_evidence(self):
        text='😀 우주선 조종실, 다시 우주선 조종실.'
        result=self.call(response(tag()),text)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['mode'],'mock')
        self.assertEqual(result['source_text'],text)
        self.assertEqual(len(result['tags'][0]['spans']),2)
        self.assertEqual(result['tags'][0]['spans'][0]['start_cp'],2)
        for s in result['tags'][0]['spans']:self.assertEqual(text[s['start_cp']:s['end_cp']],s['evidence'])

    def test_fabricated_quote_preserved_unclassified_no_highlight(self):
        result=self.call(response(tag(quotes=['없는 문구'])))
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['tags'],[])
        self.assertEqual(result['unclassified'][0]['spans'],[])
        self.assertEqual(result['unclassified'][0]['name'],'우주선 조종실')

    def test_empty_evidence_preserves_candidate(self):
        result=self.call(response(tag(quotes=[])))
        self.assertEqual(result['unclassified'][0]['spans'],[])

    def test_duplicate_merge_and_independent_concepts(self):
        item=tag(name='패널',disposition='new',ident=None,category='prop',quotes=['패널'])
        result=self.call(response(tag(),tag(),item))
        self.assertEqual(len(result['tags']),2)
        self.assertIn('duplicate_merged:우주선 조종실',result['warnings'])

    def test_new_exact_existing_name_reuses_id(self):
        result=self.call(response(tag(disposition='new',ident=None)))
        self.assertEqual(result['tags'][0]['existing_tag_id'],'tag1')
        self.assertEqual(result['tags'][0]['disposition'],'existing')

    def test_illegal_mutations_and_categories(self):
        for key,value in [('create_categories',['new']),('direct_mutations',['db-write'])]:
            res=response(tag());res[key]=value
            self.assertEqual(self.call(res)['status'],'invalid_response')
        for cat in ['hidden','invented']:
            self.assertEqual(self.call(response(tag(category=cat)))['status'],'invalid_response')

    def test_ids_names_card_and_additional_properties(self):
        for bad in [tag(ident='unknown'),tag(name='틀린 대표어'),tag(name='틀린 대표어',disposition='unclassified',category=None)]:
            self.assertEqual(self.call(response(bad))['status'],'invalid_response')
        res=response(tag());res['card_ref']='wrong'
        self.assertEqual(self.call(res)['status'],'invalid_response')
        res=response(tag());res['tags'][0]['offset']=999
        self.assertEqual(self.call(res)['status'],'invalid_response')

    def test_wrong_types_and_invalid_json(self):
        res=response(tag());res['tags'][0]['evidence_text']='우주선 조종실'
        self.assertEqual(self.call(res)['status'],'invalid_response')
        self.assertEqual(self.call('{bad-json')['status'],'invalid_response')

    def test_unclassified_candidate_not_forced(self):
        result=self.call(response(tag(disposition='unclassified',category=None,reason='분류 불명확')))
        self.assertEqual(result['unclassified'][0]['category_id'],None)
        self.assertTrue(result['unclassified'][0]['spans'])

    def test_existing_category_cannot_silently_move(self):
        result=self.call(response(tag(category='prop')))
        self.assertEqual(result['unclassified'][0]['category_id'],None)

    def test_missing_user_definition_not_in_request(self):
        request=build_request('new-1','text',[{'id':'x','name':'이름뿐','enabled':True}],TAGS,CONTEXT)
        self.assertEqual(request['active_categories'],[])

    def test_offline_no_transport_and_preserved_prompt(self):
        with patch('urllib.request.build_opener',side_effect=AssertionError('No network expected')):
            result=analyze_card('new-1','😀 original',CATS,TAGS,CONTEXT)
        self.assertEqual(result['status'],'api_disabled')
        self.assertEqual(result['source_text'],'😀 original')

    def test_missing_key_or_consent_never_calls_network(self):
        for consent in [False,True]:
            with patch.dict(os.environ,{},clear=True),patch('urllib.request.build_opener',side_effect=AssertionError('No network expected')):
                config=APIConfig(enabled=True,consent=consent,endpoint='https://api.example.com/v1/chat/completions',model='user-selected')
                result=analyze_card('new-1','original',CATS,TAGS,CONTEXT,config=config)
            self.assertEqual(result['status'],'api_unavailable')
            self.assertEqual(result['source_text'],'original')

    def test_call_cost_budget_and_tls_endpoint(self):
        for cfg in [APIConfig(endpoint='https://api.example.com/x',max_calls=0),
                    APIConfig(endpoint='https://api.example.com/x',max_cost_usd=0,input_usd_per_million=1,output_usd_per_million=1)]:
            cfg.enabled=True;cfg.consent=True;cfg.model='test'
            with patch.dict(os.environ,{'BBOLPROM_API_KEY':'test-only-not-real'}),patch('urllib.request.build_opener',side_effect=AssertionError('No network expected')):
                result=analyze_card('new-1','original',CATS,TAGS,CONTEXT,config=cfg)
            self.assertEqual(result['status'],'api_unavailable')
            self.assertEqual(cfg.calls,0)

    def test_connection_timeout_preserves_original(self):
        config=APIConfig(enabled=True,consent=True,endpoint='https://api.example.com/v1/chat/completions',model='test')
        with patch.dict(os.environ,{'BBOLPROM_API_KEY':'test-only-not-real'}),patch('urllib.request.OpenerDirector.open',side_effect=TimeoutError):
            result=analyze_card('new-1','original',CATS,TAGS,CONTEXT,config=config)
        self.assertEqual(result['status'],'api_unavailable')
        self.assertEqual(result['source_text'],'original')
        self.assertEqual(config.calls,1)
        self.assertNotIn('test-only-not-real',json.dumps(result))

    def test_quota_error_does_not_leak_provider_body_or_retry(self):
        from urllib.error import HTTPError
        from io import BytesIO
        config=APIConfig(enabled=True,consent=True,endpoint='https://api.example.com/v1/chat/completions',model='test')
        error=HTTPError(config.endpoint,429,'quota',{},BytesIO(b'never-expose-server-secret'))
        with patch.dict(os.environ,{'BBOLPROM_API_KEY':'test-only-not-real'}),patch('urllib.request.OpenerDirector.open',side_effect=error) as called:
            result=analyze_card('new-1','original',CATS,TAGS,CONTEXT,config=config)
        self.assertEqual(result['status'],'api_unavailable')
        self.assertIn('HTTP 429',result['warnings'][0])
        self.assertNotIn('never-expose',json.dumps(result))
        self.assertEqual(called.call_count,1)
        self.assertEqual(result['source_text'],'original')

    def test_config_rejects_invalid_numeric_values(self):
        for key,value in [('timeout',float('nan')),('timeout',float('inf')),('timeout',True),
                          ('max_calls','10'),('max_calls',True),('max_calls',-1),
                          ('max_output_tokens',0),('max_output_tokens',1.5),
                          ('max_input_chars',0),('max_cost_usd',float('nan')),
                          ('input_usd_per_million',-1),('output_usd_per_million',float('inf')),
                          ('enabled','true'),('key_env','KEY=secret'),('endpoint','http://api.example.com/x'),
                          ('endpoint','https://u:secret@api.example.com/x'),('endpoint','https://api.example.com/x?key=secret'),
                          ('endpoint','https://api.example.com:secret/x')]:
            with self.subTest(key=key,value=value),self.assertRaises(APIValidationError):APIConfig(**{key:value})

    def test_context_selector_disambiguates_repeated_source_evidence(self):
        text='😀 빨간 패널을 보지만 파란 패널은 보지 않는다.'
        with self.assertRaises(APIValidationError):select_evidence_spans(text,'패널')
        selected=select_evidence_spans(text,'패널',prefix='빨간 ',suffix='을')
        self.assertEqual(len(selected),1)
        span=selected[0]
        self.assertEqual(text[span['start_cp']:span['end_cp']],'패널')
        self.assertEqual(span['start_cp'],5)
        with self.assertRaises(APIValidationError):select_evidence_spans(text,'패널',prefix='없는 ')

    def test_provider_usage_reconciles_budget_and_blocks_next_call(self):
        from io import BytesIO
        config=APIConfig(enabled=True,consent=True,endpoint='https://api.example.com/v1/chat/completions',model='test',
                         max_calls=2,max_cost_usd=0.1,input_usd_per_million=1,output_usd_per_million=1)
        envelope={'choices':[{'message':{'content':json.dumps(response(tag()),ensure_ascii=False)},'finish_reason':'stop'}],
                  'usage':{'prompt_tokens':200,'completion_tokens':50}}
        def fake_open(*args,**kwargs):return BytesIO(json.dumps(envelope).encode())
        with patch.dict(os.environ,{'BBOLPROM_API_KEY':'test-only-not-real'}),patch('urllib.request.OpenerDirector.open',side_effect=fake_open) as called:
            first=analyze_card('new-1','우주선 조종실',CATS,TAGS,CONTEXT,config=config)
            self.assertEqual(first['status'],'ok')
            self.assertEqual(first['usage']['prompt_tokens'],200)
            self.assertEqual(config.total_input_tokens,200)
            self.assertEqual(config.total_output_tokens,50)
            self.assertAlmostEqual(config.estimated_cost_usd,0.00025)
            self.assertAlmostEqual(config.reserved_cost_usd,0.00025)
            config.max_cost_usd=0.000251
            second=analyze_card('new-1','우주선 조종실',CATS,TAGS,CONTEXT,config=config)
            self.assertEqual(second['status'],'api_unavailable')
            self.assertEqual(called.call_count,1)
            self.assertEqual(config.calls,1)

    def test_malformed_provider_envelope_preserves_card(self):
        from io import BytesIO
        config=APIConfig(enabled=True,consent=True,endpoint='https://api.example.com/v1/chat/completions',model='test')
        with patch.dict(os.environ,{'BBOLPROM_API_KEY':'test-only-not-real'}),patch('urllib.request.OpenerDirector.open',return_value=BytesIO(b'[]')):
            result=analyze_card('new-1','original',CATS,TAGS,CONTEXT,config=config)
        self.assertEqual(result['status'],'api_unavailable')
        self.assertEqual(result['source_text'],'original')

    def test_approved_context_is_real_and_contains_no_source_prompts(self):
        data=load_approved_context()
        self.assertEqual(data['source_sha256'],'b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe')
        self.assertEqual(len({t['name'] for t in data['standards']}),2200)
        self.assertGreater(len(data['decisions']),200)
        result=retrieve_context('카페에서 카메라를 응시한다.',data)
        self.assertTrue(result['decisions'])
        self.assertTrue(all('provenance' in d for d in result['decisions']))
        for d in data['decisions']:
            self.assertNotIn('source_text',d)
            self.assertNotIn('prompt_text',d)
            self.assertNotIn('spans',d)

class Categories(unittest.TestCase):
    def test_rename_definition_do_not_mutate_old_cards(self):
        original=[{'name':'우주선 조종실','category_id':'place','spans':[{'start_cp':2,'end_cp':9}]}]
        m=CategoryManager(CATS,original)
        m.rename('place','장면 위치')
        m.define('place','새 정의',user_confirmed=True)
        self.assertEqual(m.tags,original)
        self.assertEqual(CATS[0]['name'],'장소')

    def test_deactivate_preserves_evidence_and_history_no_automatic_reassign(self):
        m=CategoryManager(CATS,[{'name':'우주선 조종실','category_id':'place','spans':[{'start_cp':2,'end_cp':9}]}])
        m.deactivate('place')
        self.assertIsNone(m.tags[0]['category_id'])
        self.assertEqual(m.tags[0]['spans'],[{'start_cp':2,'end_cp':9}])
        self.assertEqual(m.tags[0]['category_history'][0]['category_id'],'place')
        self.assertIsNone(m.tags[0]['category_column'])
        with self.assertRaises(ValueError):m.reactivate('place')
        m.reactivate('place',restore_tags=False)
        self.assertIsNone(m.tags[0]['category_id'])
        self.assertFalse(m.history[-1]['restore_tags'])
        m.reactivate('place',restore_tags=True)
        self.assertEqual(m.tags[0]['category_id'],'place')
        self.assertEqual(m.tags[0]['category_column'],'place')
        self.assertTrue(m.history[-1]['restore_tags'])

    def test_user_category_creation_requires_confirmed_definition(self):
        m=CategoryManager()
        with self.assertRaises(ValueError):m.add({'id':'x','name':'새분류','definition':'새정의'})
        m.add({'id':'x','name':'새분류','definition':'새정의'},user_confirmed=True)
        self.assertEqual(len(m.active()),1)

if __name__=='__main__':unittest.main()
