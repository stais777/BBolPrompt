"""Authenticated new engine UI endpoints; all files and keys are synthetic."""
import copy,json,unittest
from unittest.mock import patch
import test_app_v3


class EngineHTTP(unittest.TestCase):
    setUp=test_app_v3.LocalHTTPApplication.setUp
    tearDown=test_app_v3.LocalHTTPApplication.tearDown
    request=test_app_v3.LocalHTTPApplication.request

    def test_new_endpoints_require_auth_and_reject_baseline_targets(self):
        for path,data in [('/api/engine/definitions',{}),('/api/engine/corrections',{}),('/api/engine/status',{}),
                          ('/api/engine/card',{'id':'approved-1'}),('/api/engine/tag-history',{'id':'approved-1'})]:
            self.assertEqual(self.request('POST',path,data,authorized=False)[0],403)
        for path in ('/api/engine/card','/api/engine/tag-history'):
            self.assertEqual(self.request('POST',path,{'id':'approved-1'})[0],400)

    def test_definition_confirmation_is_versioned_separate_from_baseline_and_existing_settings(self):
        original=copy.deepcopy(self.app.baseline.cards());settings=self.app.categories()
        status,view,_=self.request('POST','/api/engine/definitions',{});self.assertEqual(status,200)
        self.assertFalse(any(c['definition_approved'] for c in view['definitions']))
        rows=[{k:c[k] for k in ('id','definition','include','exclude')} for c in view['definitions']]
        data={'operation':'approve','definitions':rows,'expected_token':view['token']}
        self.assertEqual(self.request('POST','/api/engine/definitions',data)[0],200)
        self.assertEqual(self.request('POST','/api/engine/definitions',data)[0],400)
        self.assertEqual(self.app.categories(),settings);self.assertEqual(self.app.baseline.cards(),original)

    def test_manual_token_history_restore_and_correction_withdrawal_use_existing_card(self):
        cid=self.app.library.manual('subway station',[])
        state=self.request('POST','/api/engine/card',{'id':cid})[1]
        data={'id':cid,'tags':[{'name':'my place','category_id':'F','evidence':'subway station'}],'expected_token':state['token']}
        self.assertEqual(self.request('POST','/api/tags',data)[0],200)
        self.assertEqual(self.request('POST','/api/tags',data)[0],400)
        correction=self.request('POST','/api/engine/corrections',{})[1]['corrections'][0]
        self.assertEqual(self.request('POST','/api/engine/corrections',{'operation':'set_active','id':correction['id'],'active':False})[0],200)
        hist=self.request('POST','/api/engine/tag-history',{'id':cid})[1]
        self.assertEqual(hist['versions'][-1]['revision'],0)
        self.assertEqual(self.request('POST','/api/engine/tag-restore',{'id':cid,'version_id':'initial','expected_token':hist['token']})[0],200)
        self.assertEqual(self.app.library.cards()[0]['tags'],[])

    def test_opt_in_setting_type_and_no_paid_call_on_definition_confirmation(self):
        for bad in (1,'yes',None):self.assertEqual(self.request('POST','/api/settings',{'api':{'use_user_corrections':bad}})[0],400)
        self.assertEqual(self.request('POST','/api/settings',{'api':{'use_user_corrections':True}})[0],200)
        with patch('bbolprom_engine.api._live_transport',side_effect=AssertionError('No call on configuration')):
            self.assertEqual(self.request('POST','/api/engine/definitions',{})[0],200)
        self.assertEqual(self.app.api_budget.status()['calls'],0)

    def test_editor_snapshot_returns_the_same_tags_and_source_version_as_its_token(self):
        cid=self.app.library.manual('subway station',[])
        self.request('POST','/api/tags',{'id':cid,'tags':[{'name':'latest saved tag','category_id':'F','evidence':'subway station'}]})
        payload=self.request('POST','/api/engine/card',{'id':cid})[1]
        current=self.app.new_card_engine.repo.snapshot(cid)
        self.assertEqual(payload['token'],current['token']);self.assertEqual(payload['source_sha256'],current['sha'])
        self.assertEqual(payload['tags'],current['tags']);self.assertEqual(payload['tags'][0]['tag'],'latest saved tag')


if __name__=='__main__':unittest.main()
