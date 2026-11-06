"""Delayed synthetic provider: local operations stay usable and never duplicate billing."""
import concurrent.futures
import copy
import json
import threading
import unittest
from bbolprom_engine.api_engine.definitions import approve
import test_app_v3


class APIOperationResponsiveness(unittest.TestCase):
    setUp=test_app_v3.LocalHTTPApplication.setUp
    tearDown=test_app_v3.LocalHTTPApplication.tearDown
    request=test_app_v3.LocalHTTPApplication.request

    def prepare(self):
        self.text='A person waits at a subway station.'
        self.cid=self.app.library.manual(self.text,[])
        engine=self.app.new_card_engine
        view=engine.definition_view(self.app.categories())
        approve(engine.repo,self.app.categories(),[{k:x[k] for k in ('id','definition','include','exclude')} for x in view['definitions']],view['token'])
        self.app.library.set_setting('api',{'enabled':True,'consent':True,'model':'gpt-6.1-sol'})
        entered=threading.Event();release=threading.Event();calls=[]
        original=engine.analyze
        def provider(r):
            calls.append(r['card_ref']);entered.set()
            if not release.wait(10):raise RuntimeError('synthetic provider timed out')
            return {'card_ref':r['card_ref'],'policy_version':'API-POLICY-1.0',
                'tags':[{'name':'지하철역','disposition':'new','existing_tag_id':None,'category_id':'F','category_status':'classified','evidence_text':['subway station'],'reason':'synthetic exact source'}],
                'unclassified':[],'create_categories':[],'direct_mutations':[]}
        engine.analyze=lambda *a,**k:original(*a,**k,transport=provider)
        return entered,release,calls

    def test_ui_save_finishes_while_provider_is_waiting(self):
        entered,release,calls=self.prepare();baseline=copy.deepcopy(self.app.baseline.cards())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.request,'POST','/api/analyze',{'id':self.cid})
            try:
                self.assertTrue(entered.wait(3))
                other=pool.submit(self.request,'POST','/api/ui',{'hidden_cards':[self.cid]})
                self.assertEqual(other.result(timeout=1)[0],200)
            finally:release.set()
            self.assertEqual(first.result(timeout=5)[0],200)
        self.assertEqual(calls,[self.cid]);self.assertEqual(self.app.baseline.cards(),baseline)
        self.assertEqual(self.app.library.get_setting('ui')['hidden_cards'],[self.cid])
        self.assertEqual(self.app.api_budget.status()['calls'],0)

    def test_duplicate_is_rejected_without_waiting_or_second_provider_call(self):
        entered,release,calls=self.prepare()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.request,'POST','/api/analyze',{'id':self.cid})
            try:
                self.assertTrue(entered.wait(3))
                duplicate=pool.submit(self.request,'POST','/api/analyze',{'id':self.cid})
                status,body,_=duplicate.result(timeout=1)
                self.assertEqual(status,400);self.assertIn('진행',body['error'])
            finally:release.set()
            self.assertEqual(first.result(timeout=5)[0],200)
        self.assertEqual(len(calls),1)

    def test_user_edit_during_provider_wait_is_preserved_and_marks_stale(self):
        entered,release,_=self.prepare()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.request,'POST','/api/analyze',{'id':self.cid})
            try:
                self.assertTrue(entered.wait(3))
                tags={'id':self.cid,'tags':[{'name':'사용자 확정 장소','category_id':'F','evidence':'subway station'}]}
                edit=pool.submit(self.request,'POST','/api/tags',tags)
                self.assertEqual(edit.result(timeout=1)[0],200)
            finally:release.set()
            self.assertEqual(first.result(timeout=5)[1]['status'],'stale_result')
        self.assertEqual(self.app.library.cards()[0]['tags'][0]['tag'],'사용자 확정 장소')

    def test_status_route_is_authenticated_small_and_reports_activity(self):
        entered,release,_=self.prepare()
        self.assertEqual(self.request('GET','/api/analysis-status',authorized=False)[0],403)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.request,'POST','/api/analyze',{'id':self.cid})
            try:
                self.assertTrue(entered.wait(3))
                status,body,_=self.request('GET','/api/analysis-status')
                self.assertEqual(status,200);self.assertTrue(body['activity']['running'])
                self.assertEqual(body['activity']['card_id'],self.cid)
                self.assertNotIn(self.text,json.dumps(body));self.assertLess(len(json.dumps(body)),10000)
            finally:release.set()
            first.result(timeout=5)
        body=self.request('GET','/api/analysis-status')[1]
        self.assertFalse(body['activity']['running']);self.assertEqual(body['recent'][0]['status'],'ok')


if __name__=='__main__':unittest.main()
