"""Actual child-process startup/migration/redirect, still Linux and fake data."""
import http.client
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from bbolprom_engine.app import Application


class PortableProcessStartup(unittest.TestCase):
    def run_app(self,legacy_data=False,progress_page=False):
        with tempfile.TemporaryDirectory(prefix='bbol-portable-process-') as folder:
            root=Path(folder);program=root/'프로그램 폴더 #1';program.mkdir()
            profile=root/'다른 Windows 사용자 #2';legacy=profile/'Bbolprom'
            cid=None
            if legacy_data:
                old=Application(legacy);cid=old.library.manual('이전 사용자 원문',[('x.png',io.BytesIO(b'original image'))])
                old.action('/api/baseline-tags',{'id':'approved-1','tags':[],'expected_revision':0})
            env=os.environ.copy();env['LOCALAPPDATA']=str(profile)
            if progress_page:
                script="from pathlib import Path; import sys; import bbolprom_engine.app as app; app.webbrowser.open=lambda url:Path(sys.argv[1]).write_text(url); raise SystemExit(app.main(['--portable-root',sys.argv[2]]))"
                command=[sys.executable,'-c',script,str(root/'startup-url.txt'),str(program)]
            else:command=[sys.executable,'-m','bbolprom_engine.app','--portable-root',str(program),'--no-browser']
            child=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                runtime=program/'data/runtime.json';deadline=time.monotonic()+20
                while not runtime.is_file():
                    if child.poll() is not None:
                        stdout,stderr=child.communicate();self.fail(stderr.decode()+stdout.decode())
                    if time.monotonic()>deadline:self.fail('portable child startup timeout')
                    time.sleep(0.05)
                port=json.loads(runtime.read_text())['port']
                def request(method,path,body=None,token=None,target_port=port):
                    con=http.client.HTTPConnection('127.0.0.1',target_port,timeout=5)
                    try:
                        con.request(method,path,body=json.dumps(body).encode() if body is not None else None,headers={'X-Bbolprom-Token':token} if token else {})
                        r=con.getresponse();return r.status,r.read()
                    finally:con.close()
                status,html=request('GET','/');self.assertEqual(status,200)
                token=re.search(rb"window.BBOLPROM_TOKEN='([^']+)'",html).group(1).decode()
                status,raw=request('GET','/api/state',token=token);self.assertEqual(status,200);state=json.loads(raw)
                self.assertEqual(state['storage']['data_path'],str(program/'data'))
                self.assertEqual(state['storage']['mode'],'portable');
                if not legacy_data:self.assertFalse((profile/'Bbolprom/library.sqlite3').exists())
                self.assertEqual(state['baseline']['registered_cards'],309)
                if legacy_data:
                    self.assertEqual(next(c for c in state['cards'] if c['id']=='approved-1')['tags'],[])
                    self.assertTrue((program/'data/new_cards'/cid).is_dir());self.assertTrue((legacy/'library.sqlite3').is_file())
                if progress_page:
                    from urllib.parse import urlsplit
                    progress_port=urlsplit((root/'startup-url.txt').read_text()).port
                    status,raw=request('GET','/status',target_port=progress_port);self.assertEqual(status,200)
                    self.assertEqual(json.loads(raw)['url'],f'http://127.0.0.1:{port}/')
                self.assertEqual(request('POST','/api/shutdown',{},token)[0],200)
                child.communicate(timeout=10);self.assertEqual(child.returncode,0)
            finally:
                if child.poll() is None:child.kill();child.communicate()

    def test_fresh_child_uses_program_data_instead_of_profile_library(self):self.run_app()
    def test_child_migrates_legacy_and_progress_redirects_to_ready_app(self):self.run_app(True,True)


if __name__=='__main__':unittest.main()
