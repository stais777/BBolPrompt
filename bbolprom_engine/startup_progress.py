"""Small loopback progress page while large legacy data is copied/verified."""
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from datetime import datetime,timezone


def clear_startup_error(root):
    for name in ('startup-error.log','startup-error-message.txt'):
        try:(Path(root)/name).unlink(missing_ok=True)
        except OSError:pass


def write_startup_error(root,error,trace,version):
    """Local current-run details; do not put tracebacks in the native popup."""
    stamp=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    header='뽈프롬 버전 '+version+' · '+stamp+'\n'
    if isinstance(error,ValueError):reason=str(error)
    elif isinstance(error,PermissionError):reason='자료 폴더에 접근하지 못했습니다. 이전 앱을 종료하고 쓰기 가능한 폴더에서 실행하세요.'
    elif isinstance(error,OSError):reason='자료 준비 중 파일 또는 로컬 연결 오류가 발생했습니다. startup-error.log를 확인해주세요.'
    else:reason='프로그램 시작 중 오류가 발생했습니다. startup-error.log를 확인해주세요.'
    message=header+reason+'\n\n기존 자료는 삭제하지 않았습니다. 자세한 기록: 실행 폴더의 startup-error.log'
    for name,body in (('startup-error.log',header+'\n'+trace),('startup-error-message.txt',message[:7000])):
        try:(Path(root)/name).write_text(body,encoding='utf8')
        except OSError:pass

PAGE='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>뽈프롬 자료 준비</title>
<style>body{font:17px sans-serif;max-width:720px;margin:12vh auto;padding:24px;color:#24314a}progress{width:100%;height:24px}p{line-height:1.7}</style>
<h1>뽈프롬 자료 준비</h1><p>최초 원본과 사용자 수정 이력을 보존하며 자료 폴더를 준비합니다.</p>
<p id="status">준비 중…</p><progress id="progress"></progress><p id="amount"></p><script src="/progress.js"></script></html>'''
SCRIPT='''async function tick(){try{const r=await fetch('/status');if(!r.ok)throw Error();const d=await r.json();
document.getElementById('status').textContent=d.message;const p=document.getElementById('progress');if(d.total){p.max=d.total;p.value=d.done;document.getElementById('amount').textContent=Math.round(d.done/d.total*100)+'%'}else p.removeAttribute('value');
if(d.url){location.replace(d.url);return}if(!d.failed)setTimeout(tick,500)}catch(e){document.getElementById('status').textContent='프로그램의 자료 준비가 중단됐습니다. 실행 폴더의 startup-error.log를 확인한 뒤 다시 실행하세요.'}}tick();'''


class StartupProgress:
    def __init__(self):
        self.state={'message':'자료 폴더를 준비하고 있습니다.','done':0,'total':0}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':self.send_error(403);return
                if self.path=='/':body=PAGE.encode();mime='text/html; charset=utf-8'
                elif self.path=='/progress.js':body=SCRIPT.encode();mime='text/javascript; charset=utf-8'
                elif self.path=='/status':body=json.dumps(owner.state,ensure_ascii=False).encode();mime='application/json; charset=utf-8'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'")
                self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}/'

    def update(self,message,done=0,total=0):self.state={'message':message,'done':done,'total':total}
    def ready(self,url):self.state={'message':'자료 확인이 끝났습니다. 프로그램을 엽니다.','done':1,'total':1,'url':url}
    def fail(self):self.state={'message':'자료 준비에 실패했습니다. 기존 자료는 유지됩니다. 실행 폴더의 startup-error.log를 확인하세요.','failed':True}
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
