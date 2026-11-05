"""Startup identity, stale process/port recovery and current-error reporting.

All application libraries and HTTP listeners are disposable synthetic fixtures.
"""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch,MagicMock

from bbolprom_engine.app import Application, make_server, main
from bbolprom_engine.portable_storage import prepare_portable_data, database_fingerprint


class StartupRecovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def serve(self, root):
        server=make_server(root)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():
            server.shutdown();server.server_close();thread.join(timeout=3)
        self.addCleanup(close)
        return server

    def runtime(self, root, server, **extra):
        (root/'runtime.json').write_text(json.dumps({'port':server.server_port,**extra}))

    def test_reused_port_for_other_library_cannot_block_migration(self):
        old=self.root/'old';app=Application(old)
        cid=app.library.manual('synthetic card to preserve',[])
        app.action('/api/baseline-tags',{'id':'approved-1','tags':[],'expected_revision':0})
        before=database_fingerprint(old/'library.sqlite3')
        other=self.serve(self.root/'other')
        self.runtime(old,other,pid=os.getpid())
        target=self.root/'program/data'
        prepare_portable_data(target,old)
        copied=Application(target)
        self.assertEqual(copied.library.cards()[0]['id'],cid)
        self.assertEqual(copied.baseline_tag_edits.latest(1)['tags'],[])
        self.assertEqual(database_fingerprint(old/'library.sqlite3'),before)

    def test_legacy_health_at_reused_port_with_dead_saved_pid_is_not_old_app(self):
        old=self.root/'old';Application(old)
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        class LegacyHealth(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=b'{"ok":true,"approved_count":309}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),LegacyHealth)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.runtime(old,server,pid=12345)
            with patch('bbolprom_engine.portable_storage.process_alive',return_value=False):
                prepare_portable_data(self.root/'program/data',old)
            # Unknown/alive pre-0.3.8 owners remain protected. No force option.
            for state in (None,True):
                with patch('bbolprom_engine.portable_storage.process_alive',return_value=state):
                    with self.assertRaises(ValueError):prepare_portable_data(self.root/'another/data',old)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_same_library_still_blocks_and_identifies_exact_local_page(self):
        old=self.root/'old';server=self.serve(old);self.runtime(old,server,pid=os.getpid())
        before=database_fingerprint(old/'library.sqlite3');target=self.root/'program/data'
        with self.assertRaises(ValueError) as caught:prepare_portable_data(target,old)
        self.assertIn(f'http://127.0.0.1:{server.server_port}/',str(caught.exception))
        self.assertFalse(target.exists())
        self.assertEqual(database_fingerprint(old/'library.sqlite3'),before)

    def test_health_identity_exposes_no_raw_path_or_session_token(self):
        server=self.serve(self.root/'private-library-location')
        con=http.client.HTTPConnection('127.0.0.1',server.server_port)
        try:
            con.request('GET','/health');r=con.getresponse();raw=r.read();body=json.loads(raw)
        finally:con.close()
        self.assertEqual(body['pid'],os.getpid());self.assertEqual(len(body['data_id']),64)
        self.assertNotIn(str(self.root).encode(),raw)
        self.assertNotIn(server.application.token.encode(),raw)

    def test_current_failure_shows_reason_and_opens_detected_app_without_killing_it(self):
        profile=self.root/'profile';old=profile/'Bbolprom';server=self.serve(old)
        self.runtime(old,server,pid=os.getpid())
        program=self.root/'program';program.mkdir()
        with patch.dict(os.environ,{'LOCALAPPDATA':str(profile)}),patch('bbolprom_engine.app.webbrowser.open') as opened:
            with self.assertRaises(ValueError):main(['--portable-root',str(program)])
        url=f'http://127.0.0.1:{server.server_port}/'
        self.assertIn(url,[c.args[0] for c in opened.call_args_list])
        message=(program/'startup-error-message.txt').read_text(encoding='utf8')
        self.assertIn(url,message);self.assertIn('앱 종료',message)
        log=(program/'startup-error.log').read_text(encoding='utf8')
        self.assertIn('UTC',log);self.assertIn('버전',log)
        self.assertFalse((program/'data').exists())

    def test_success_removes_previous_failure_and_runtime_records_identity(self):
        profile=self.root/'profile';program=self.root/'program';program.mkdir()
        for name in ('startup-error.log','startup-error-message.txt'):(program/name).write_text('stale failure')
        server=SimpleNamespace(server_port=12345,serve_forever=lambda:None,server_close=lambda:None)
        with patch.dict(os.environ,{'LOCALAPPDATA':str(profile)}),patch('bbolprom_engine.app.make_server',return_value=server):
            self.assertEqual(main(['--portable-root',str(program),'--no-browser']),0)
        for name in ('startup-error.log','startup-error-message.txt'):self.assertFalse((program/name).exists())
        runtime=json.loads((program/'data/runtime.json').read_text())
        self.assertEqual(runtime['pid'],os.getpid());self.assertEqual(len(runtime['data_id']),64)


class WindowsProcessProbe(unittest.TestCase):
    def test_windows_liveness_uses_readonly_wait_and_closes_handles(self):
        from bbolprom_engine.portable_storage import _windows_process_alive
        kernel=MagicMock();kernel.OpenProcess.return_value=42
        with patch('ctypes.WinDLL',return_value=kernel,create=True):
            for result,expected in ((258,True),(0,False),(0xffffffff,None)):
                kernel.WaitForSingleObject.return_value=result
                self.assertIs(_windows_process_alive(12345),expected)
        self.assertEqual(kernel.OpenProcess.call_args.args,(0x00100000,False,12345))
        self.assertEqual(kernel.WaitForSingleObject.call_args.args,(42,0))
        self.assertEqual(kernel.CloseHandle.call_count,3)
        kernel.TerminateProcess.assert_not_called()

    def test_unreadable_windows_process_is_unknown_and_missing_pid_is_dead(self):
        from bbolprom_engine.portable_storage import _windows_process_alive
        kernel=MagicMock();kernel.OpenProcess.return_value=0
        with patch('ctypes.WinDLL',return_value=kernel,create=True):
            with patch('ctypes.get_last_error',return_value=5,create=True):self.assertIsNone(_windows_process_alive(12345))
            with patch('ctypes.get_last_error',return_value=87,create=True):self.assertIs(_windows_process_alive(12345),False)
        kernel.CloseHandle.assert_not_called();kernel.TerminateProcess.assert_not_called()

    def test_windows_dispatch_never_uses_os_kill(self):
        from bbolprom_engine.portable_storage import process_alive
        fake_os=SimpleNamespace(name='nt',kill=MagicMock())
        with patch('bbolprom_engine.portable_storage.os',fake_os),patch('bbolprom_engine.portable_storage._windows_process_alive',return_value=True) as probe:
            self.assertIs(process_alive(12345),True)
            for pid in (None,True,False,-1,0,2**32,'12345'):self.assertIsNone(process_alive(pid))
        probe.assert_called_once_with(12345);fake_os.kill.assert_not_called()


if __name__=='__main__':unittest.main()
