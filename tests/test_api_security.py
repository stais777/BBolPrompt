"""Security boundary tests with synthetic keys and mocked Win32/provider calls.

These do not use a real key, a remote provider, or a native Windows vault.
"""
import concurrent.futures
import ctypes
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from bbolprom_engine.api import APIConfig, APIValidationError, OPENAI_ENDPOINT, _live_transport, build_request, analyze_card
from bbolprom_engine.api_budget import APIBudget, BudgetError
from bbolprom_engine.credentials import WindowsCredentialStore, CredentialError, CREDENTIALW, BYTE, TARGET, validate_key
import test_app_v3
from test_api_v3 import CATS, TAGS, CONTEXT, response, tag

KEY = 'sk-synthetic-security-fixture-123456789'


class MemoryStore:
    supported = True
    def __init__(self):self.key=None
    def save(self,key):self.key=validate_key(key)
    def read(self):return self.key
    def present(self):return bool(self.key)
    def delete(self):self.key=None


class Function:
    def __init__(self,fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)


class FakeWin32:
    def __init__(self):
        self.secret=None;self.error=0;self.freed=0
        self.CredWriteW=Function(self.write);self.CredReadW=Function(self.read)
        self.CredDeleteW=Function(self.delete);self.CredFree=Function(self.free)
    def write(self,ptr,flags):
        entry=ctypes.cast(ptr,ctypes.POINTER(CREDENTIALW)).contents
        assert entry.Type==1 and entry.Persist==2 and entry.TargetName==TARGET and flags==0
        self.secret=ctypes.string_at(entry.CredentialBlob,entry.CredentialBlobSize)
        return 1
    def read(self,target,kind,flags,ptr):
        assert target==TARGET and kind==1 and flags==0
        if self.secret is None:self.error=1168;return 0
        self.blob=(BYTE*len(self.secret)).from_buffer_copy(self.secret)
        self.entry=CREDENTIALW(Type=1,CredentialBlobSize=len(self.secret),CredentialBlob=self.blob)
        ctypes.cast(ptr,ctypes.POINTER(ctypes.POINTER(CREDENTIALW)))[0]=ctypes.pointer(self.entry)
        return 1
    def delete(self,target,kind,flags):
        assert target==TARGET and kind==1 and flags==0
        if self.secret is None:self.error=1168;return 0
        self.secret=None;return 1
    def free(self,ptr):self.freed+=1


class CredentialBoundary(unittest.TestCase):
    def test_win32_roundtrip_replacement_and_idempotent_delete(self):
        dll=FakeWin32();store=WindowsCredentialStore(_dll=dll,_last_error=lambda:dll.error)
        self.assertIsNone(store.read());store.save(KEY)
        self.assertEqual(store.read(),KEY);self.assertEqual(dll.freed,1)
        store.save(KEY+'changed');self.assertEqual(store.read(),KEY+'changed')
        store.delete();store.delete();self.assertFalse(store.present())
        self.assertEqual(ctypes.sizeof(CREDENTIALW),80) # x64 Win32 ABI

    def test_native_error_or_corrupt_credential_has_no_secret_in_error(self):
        dll=FakeWin32();store=WindowsCredentialStore(_dll=dll,_last_error=lambda:dll.error)
        dll.secret=b'bad-value'
        with self.assertRaises(CredentialError) as error:store.read()
        self.assertNotIn('bad-value',str(error.exception));self.assertEqual(dll.freed,1)
        dll.CredWriteW=Function(lambda *args:0)
        with self.assertRaises(CredentialError) as error:store.save(KEY)
        self.assertNotIn(KEY,str(error.exception))

    def test_unavailable_platform_does_not_fall_back_to_environment_or_files(self):
        with patch('bbolprom_engine.credentials.os.name','posix'),patch.dict(os.environ,{'BBOLPROM_API_KEY':KEY}):
            store=WindowsCredentialStore()
            self.assertFalse(store.supported);self.assertFalse(store.present())
            for operation in (lambda:store.read(),lambda:store.save(KEY),lambda:store.delete()):
                with self.assertRaises(CredentialError):operation()

    def test_reject_key_injection_and_secret_in_model(self):
        for key in (KEY+'\r\nAuthorization: bad','',None,' '+KEY,KEY+' ',KEY+'\u200b'):
            with self.assertRaises(CredentialError):validate_key(key)
        for model in (KEY,' '+KEY,KEY+' ',KEY+'\n'):
            with self.assertRaises(APIValidationError):APIConfig(model=model)


class PaidCallBoundary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'api-safety.sqlite3'
        self.store=MemoryStore();self.store.save(KEY)
        self.request=build_request('new-1','우주선 조종실',CATS,TAGS,CONTEXT)
    def config(self,**kwargs):
        values=dict(enabled=True,consent=True,endpoint=OPENAI_ENDPOINT,model='fixture',
            max_cost_usd=10,input_usd_per_million=1,output_usd_per_million=1)
        values.update(kwargs);config=APIConfig(**values)
        config._budget=APIBudget(self.path);config._credentials=self.store
        return config
    def call(self,config):
        return analyze_card('new-1','우주선 조종실',CATS,TAGS,CONTEXT,config=config)

    def test_nonofficial_destinations_rejected_before_credential_read_or_network(self):
        for endpoint in ('https://api.openai.com.evil.invalid/v1/chat/completions',
            'https://evil.invalid/v1/chat/completions',OPENAI_ENDPOINT+'?api_key='+KEY,
            'https://api.openai.com:444/v1/chat/completions',
            'https://user:'+KEY+'@api.openai.com/v1/chat/completions',
            OPENAI_ENDPOINT+'#fragment',OPENAI_ENDPOINT+'/',
            'http://api.openai.com/v1/chat/completions'):
            with patch.object(self.store,'read',side_effect=AssertionError('must not read')),patch('urllib.request.build_opener',side_effect=AssertionError('must not connect')):
                with self.assertRaises(APIValidationError) as error:self.config(endpoint=endpoint)
                self.assertNotIn(KEY,str(error.exception))

    def test_auth_header_only_no_retry_and_tls_redirect_guard(self):
        import urllib.request
        config=self.config()
        envelope={'choices':[{'message':{'content':json.dumps(response(tag()))},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':20}}
        def opened(req,**kwargs):
            self.assertEqual(req.full_url,OPENAI_ENDPOINT)
            self.assertEqual(req.get_header('Authorization'),'Bearer '+KEY)
            self.assertNotIn(KEY.encode(),req.data)
            return io.BytesIO(json.dumps(envelope).encode())
        original=urllib.request.build_opener
        with patch('urllib.request.build_opener',wraps=original) as built,patch('urllib.request.OpenerDirector.open',side_effect=opened) as network:
            result=self.call(config)
        self.assertEqual(result['status'],'ok');self.assertEqual(network.call_count,1)
        handlers=built.call_args.args
        redirect=next(h for h in handlers if isinstance(h,urllib.request.HTTPRedirectHandler))
        self.assertIsNone(redirect.redirect_request(None,None,302,'',{},'https://evil.invalid/'))
        https=next(h for h in handlers if isinstance(h,urllib.request.HTTPSHandler))
        self.assertTrue(https._context.check_hostname)
        self.assertEqual(https._context.verify_mode,2)
        self.assertNotIn(KEY,json.dumps(result));self.assertNotIn(KEY,repr(config))

    def test_missing_budget_prices_or_definitions_never_spends(self):
        for kwargs in ({'max_cost_usd':None},{'max_cost_usd':0},
            {'input_usd_per_million':None},{'output_usd_per_million':0}):
            with patch('urllib.request.build_opener',side_effect=AssertionError('no paid call')):
                self.assertEqual(self.call(self.config(**kwargs))['status'],'api_unavailable')
        config=self.config();config._budget=None
        with patch('urllib.request.build_opener',side_effect=AssertionError('no paid call')):
            self.assertEqual(self.call(config)['status'],'api_unavailable')
            request=dict(self.request,active_categories=[])
            with self.assertRaises(ValueError):_live_transport(request,self.config())

    def test_failed_call_reservation_survives_recreation_and_reconfiguration(self):
        config=self.config(max_calls=1)
        with patch('urllib.request.OpenerDirector.open',side_effect=TimeoutError(KEY)) as network:
            first=self.call(config);second=self.call(self.config(max_calls=1))
        self.assertEqual(first['status'],'api_unavailable');self.assertEqual(second['status'],'api_unavailable')
        self.assertEqual(network.call_count,1);self.assertNotIn(KEY,json.dumps([first,second]))
        usage=APIBudget(self.path).status()
        self.assertEqual(usage['calls'],1);self.assertGreater(usage['reserved_cost_usd'],0)
        self.assertNotIn(KEY,self.path.read_bytes().decode('latin1'))

    def test_failed_cost_reservation_cannot_be_reset_by_restarting_config(self):
        config=self.config(max_output_tokens=1)
        with patch('urllib.request.OpenerDirector.open',side_effect=TimeoutError):self.call(config)
        held=APIBudget(self.path).status()['reserved_cost_usd']
        with patch('urllib.request.build_opener',side_effect=AssertionError('cost cap bypass')):
            second=self.call(self.config(max_output_tokens=1,max_cost_usd=held*1.1))
        self.assertEqual(second['status'],'api_unavailable');self.assertEqual(APIBudget(self.path).status()['calls'],1)

    def test_atomic_concurrent_reservation_prevents_double_spend(self):
        config=self.config(max_calls=1)
        def reserve(_):
            try:APIBudget(self.path).reserve(0.01,config);return True
            except BudgetError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(reserve,range(6)))
        self.assertEqual(sum(results),1);self.assertEqual(APIBudget(self.path).status()['calls'],1)

    def test_budget_io_failure_stops_before_send(self):
        import sqlite3
        config=self.config()
        with patch.object(config._budget,'reserve',side_effect=sqlite3.OperationalError(KEY)),patch('urllib.request.build_opener',side_effect=AssertionError('no paid call')):
            result=self.call(config)
        self.assertEqual(result['status'],'api_unavailable');self.assertNotIn(KEY,json.dumps(result))


class KeyHTTPBoundary(unittest.TestCase):
    setUp=test_app_v3.LocalHTTPApplication.setUp
    tearDown=test_app_v3.LocalHTTPApplication.tearDown
    request=test_app_v3.LocalHTTPApplication.request

    def test_key_save_state_diagnostic_and_backup_contain_no_key(self):
        self.app.credentials=MemoryStore()
        before=[c['source_text_sha256'] for c in self.app.baseline.cards()]
        status,saved,_=self.request('POST','/api/key',{'operation':'save','key':KEY})
        self.assertEqual(status,200);self.assertNotIn(KEY,json.dumps(saved))
        status,state,_=self.request('GET','/api/state');self.assertTrue(state['api_key_present'])
        self.assertNotIn(KEY,json.dumps(state));self.assertNotIn(KEY,self.app.library.db.read_bytes().decode('latin1'))
        for route in ('/api/backup','/api/local-diagnostic'):
            status,result,_=self.request('POST',route,{})
            self.assertEqual(status,200)
            status,body,_=self.request('GET',result['download']);self.assertEqual(status,200)
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                for name in z.namelist():self.assertNotIn(KEY.encode(),z.read(name))
                self.assertNotIn('api-safety.sqlite3',z.namelist())
        self.assertEqual(before,[c['source_text_sha256'] for c in self.app.baseline.cards()])
        self.assertEqual(self.request('POST','/api/key',{'operation':'delete'})[0],200)
        self.assertFalse(self.app.credentials.present())

    def test_auth_origin_and_host_protect_key_writes(self):
        self.app.credentials=MemoryStore()
        data={'operation':'save','key':KEY}
        self.assertEqual(self.request('POST','/api/key',data,authorized=False)[0],403)
        self.assertEqual(self.request('POST','/api/key',data,headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.request('POST','/api/key',data,headers={'Host':'evil.invalid'})[0],403)
        self.assertIsNone(self.app.credentials.key)
        self.assertEqual(self.request('GET','/',headers={'Host':'evil.invalid'})[0],403)

    def test_key_errors_are_sanitized_and_settings_reject_embedded_keys(self):
        self.app.credentials=MemoryStore()
        for data in ({'operation':'save','key':KEY+'\n'}, {'operation':'save','key':KEY,'path':KEY},
            {'operation':'delete','key':KEY}):
            status,result,_=self.request('POST','/api/key',data)
            self.assertEqual(status,400);self.assertNotIn(KEY,json.dumps(result))
        with patch.object(self.app.credentials,'save',side_effect=OSError(KEY)):
            status,result,_=self.request('POST','/api/key',{'operation':'save','key':KEY})
        self.assertEqual(status,400);self.assertNotIn(KEY,json.dumps(result))
        for config in ({'api_key':KEY},{'key_env':KEY},{'model':KEY},{'endpoint':'https://evil.invalid/'+KEY}):
            status,result,_=self.request('POST','/api/settings',{'api':config})
            self.assertEqual(status,400);self.assertNotIn(KEY,json.dumps(result))
        self.assertNotIn(KEY,self.app.library.db.read_bytes().decode('latin1'))

    def test_key_does_not_get_returned_via_settings_and_http_request_size_limit(self):
        self.app.credentials=MemoryStore()
        status,result,_=self.request('POST','/api/key',{'operation':'save','key':KEY+'x'*3000})
        self.assertEqual(status,400);self.assertNotIn(KEY,json.dumps(result))
        self.assertIsNone(self.app.credentials.key)

    def test_application_settings_and_restart_do_not_reset_call_ledger(self):
        from bbolprom_engine.app import Application
        self.app.credentials=MemoryStore();self.app.credentials.save(KEY)
        cid=self.app.library.manual('우주선 조종실에서 패널을 본다.',[])
        self.assertEqual(self.request('POST','/api/categories',{'operation':'define','id':'F','definition':'장면의 장소'})[0],200)
        config=dict(enabled=True,consent=True,endpoint=OPENAI_ENDPOINT,model='fixture',
            max_calls=1,max_cost_usd=10,input_usd_per_million=1,output_usd_per_million=1)
        self.assertEqual(self.request('POST','/api/settings',{'api':config})[0],200)
        with patch('urllib.request.OpenerDirector.open',side_effect=TimeoutError) as network:
            self.assertEqual(self.request('POST','/api/analyze',{'id':cid})[1]['status'],'api_unavailable')
            self.assertEqual(self.request('POST','/api/settings',{'api':config})[0],200)
            self.assertEqual(self.request('POST','/api/analyze',{'id':cid})[1]['status'],'api_unavailable')
            restarted=Application(self.app.library.root);restarted.credentials=self.app.credentials
            self.assertEqual(restarted.action('/api/analyze',{'id':cid})['status'],'api_unavailable')
        self.assertEqual(network.call_count,1)
        self.assertEqual(restarted.state()['api_usage']['calls'],1)


if __name__=='__main__':unittest.main()
