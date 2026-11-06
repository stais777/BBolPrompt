"""Synthetic provider metadata; no real credentials, network or model billing."""
import io,json,unittest
from unittest.mock import patch
from bbolprom_engine.api import _live_transport,APIUnavailable
from bbolprom_engine.api_engine.operation_status import safe_summary
import test_api_security as security
KEY=security.KEY


class ProviderMetadata(unittest.TestCase):
    setUp=security.PaidCallBoundary.setUp
    config=security.PaidCallBoundary.config

    def envelope(self,finish='length',refusal=None):
        return {'choices':[{'finish_reason':finish,'message':{'content':None,'refusal':refusal}}],
            'usage':{'prompt_tokens':120,'completion_tokens':4096,'completion_tokens_details':{'reasoning_tokens':4000}}}

    def test_output_limit_keeps_specific_reason_usage_and_single_reservation(self):
        c=self.config(max_output_tokens=4096)
        with patch('urllib.request.OpenerDirector.open',return_value=io.BytesIO(json.dumps(self.envelope()).encode())) as remote:
            with self.assertRaises(APIUnavailable) as error:_live_transport(self.request,c)
        self.assertIn('출력 토큰 한도',str(error.exception));self.assertEqual(remote.call_count,1)
        self.assertEqual(c._response_meta['error_code'],'output_limit')
        self.assertEqual(c._response_meta['reasoning_tokens'],4000)
        self.assertEqual(c._budget.status()['calls'],1);self.assertEqual(c._budget.status()['total_output_tokens'],4096)
        self.assertNotIn(KEY,json.dumps(c._response_meta));self.assertNotIn(KEY,str(error.exception))

    def test_provider_refusal_text_and_synthetic_secret_are_never_reported(self):
        c=self.config()
        with patch('urllib.request.OpenerDirector.open',return_value=io.BytesIO(json.dumps(self.envelope('stop','private refusal '+KEY)).encode())):
            with self.assertRaises(APIUnavailable) as error:_live_transport(self.request,c)
        self.assertEqual(c._response_meta['error_code'],'refused')
        self.assertNotIn('private refusal',str(error.exception));self.assertNotIn(KEY,json.dumps(c._response_meta))

    def test_timeout_is_specific_and_never_retried(self):
        c=self.config()
        with patch('urllib.request.OpenerDirector.open',side_effect=TimeoutError('private '+KEY)) as remote:
            with self.assertRaises(APIUnavailable) as error:_live_transport(self.request,c)
        self.assertEqual(remote.call_count,1);self.assertEqual(c._response_meta['error_code'],'timeout')
        self.assertIn('대기시간',str(error.exception));self.assertNotIn(KEY,str(error.exception));self.assertEqual(c._budget.status()['calls'],1)

    def test_whitelist_excludes_provider_text_keys_and_unknown_fields(self):
        value={'phase':'received','finish_reason':'length','error_code':'output_limit','input_tokens':10,'output_tokens':20,
            'reasoning_tokens':True,'refusal':False,'prompt':KEY,'content':KEY,'headers':{'Authorization':KEY},'model':KEY}
        result=safe_summary(value)
        self.assertEqual(result,{'phase':'received','finish_reason':'length','error_code':'output_limit','input_tokens':10,'output_tokens':20,'refusal':False})
        self.assertNotIn(KEY,json.dumps(result));self.assertEqual(safe_summary(None),{})
        self.assertEqual(safe_summary({'phase':{},'finish_reason':[],'error_code':True}),{})


if __name__=='__main__':unittest.main()
