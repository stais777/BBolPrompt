"""Disposable browser-test server with synthetic assets, never distributed.

Only this test process substitutes the fixture SHA after normal source validation
and app initialization. Production accepts only the pinned official PT hash.
"""
import hashlib
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bbolprom_engine.app import make_server
import bbolprom_engine.baseline as baseline

def bitmap(width,height):
    row=bytes([64,128,192])*width
    row+=bytes((-len(row))%4)
    data=row*height
    return (b'BM'+struct.pack('<IHHI',54+len(data),0,0,54)+
            struct.pack('<IiiHHIIiiII',40,width,height,1,24,0,len(data),2835,2835,0,0)+data)

def main():
    folder=Path(sys.argv[1]);folder.mkdir(parents=True,exist_ok=True)
    server=make_server(folder)
    fixture=folder/'synthetic.hwpx'
    with zipfile.ZipFile(fixture,'w',zipfile.ZIP_DEFLATED) as z:
        for i,name in enumerate(server.application.baseline.paths):
            w,h=[(9,16),(16,9),(1,1)][i%3]
            z.writestr(name,bitmap(w,h)+name.encode())
    baseline.SOURCE_SHA=hashlib.sha256(fixture.read_bytes()).hexdigest()
    (folder/'runtime.json').write_text(json.dumps({'port':server.server_port,'pid':os.getpid(),'synthetic_fixture':str(fixture)}))
    server.serve_forever()

if __name__=='__main__':main()
