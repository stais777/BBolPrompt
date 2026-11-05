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
    if '--portable' in sys.argv[2:]:
        from bbolprom_engine.portable_storage import prepare_portable_data
        prepare_portable_data(folder,None)
    server=make_server(folder)
    if '--mock-api-engine' in sys.argv[2:]:
        # A synthetic semantic provider, explicitly marked mock by Engine.
        # No keys, real provider requests or model quality measurements.
        engine=server.application.new_card_engine;original_analyze=engine.analyze
        def mock_provider(request):
            source=request['prompt_text'];quote='subway station' if 'subway station' in source else 'station'
            return {'card_ref':request['card_ref'],'policy_version':'API-POLICY-1.0',
                'tags':[{'name':'지하철역','category_id':'F','category_status':'classified','disposition':'new',
                         'existing_tag_id':None,'evidence_text':[quote],'reason':'synthetic fixture exact quote'}],
                'unclassified':[],'create_categories':[],'direct_mutations':[]}
        def analyze_fixture(*args,**kwargs):return original_analyze(*args,**kwargs,transport=mock_provider)
        engine.analyze=analyze_fixture
    if '--fail-backup-once' in sys.argv[2:]:
        original_backup=server.application.library.backup
        failed=False
        def backup_once(*args,**kwargs):
            nonlocal failed
            if not failed:
                failed=True
                error=PermissionError(13,'Simulated Windows backup cleanup denial')
                error.winerror=32;error.bbolprom_operation='backup_temporary_cleanup'
                raise error
            return original_backup(*args,**kwargs)
        server.application.library.backup=backup_once
    fixture=folder/'sources/PT.hwpx' if '--reuse-source' in sys.argv[2:] else folder/'synthetic.hwpx'
    if not fixture.exists():
        with zipfile.ZipFile(fixture,'w',zipfile.ZIP_DEFLATED) as z:
            for i,name in enumerate(server.application.baseline.paths):
                w,h=[(9,16),(16,9),(1,1)][i%3]
                z.writestr(name,bitmap(w,h)+name.encode())
    baseline.SOURCE_SHA=hashlib.sha256(fixture.read_bytes()).hexdigest()
    (folder/'runtime.json').write_text(json.dumps({'port':server.server_port,'pid':os.getpid(),'synthetic_fixture':str(fixture)}))
    server.serve_forever()

if __name__=='__main__':main()
