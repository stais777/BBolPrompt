"""Packaged Windows runtime smoke check; does not call external APIs or use PT answers."""
from pathlib import Path
import hashlib,json,sqlite3,sys,tempfile,zipfile,uuid
package=Path(__file__).resolve().parent
sys.path.insert(0,str(package/'app'))
from bbolprom_engine.hwpx import HWPXReader
from bbolprom_engine.analysis import analyze
from bbolprom_engine.baseline import BaselineStore,load_dataset,MASTER_SHA
from bbolprom_engine.library import Library
from bbolprom_engine.approval_history import load_approval_history
from bbolprom_engine.method_guidance import load_method_guidance
from bbolprom_engine.baseline_edits import BaselineTagEdits

# Only the manually executed Windows check touches a disposable test target.
# Never overwrite, return or print the user's real Bbolprom credential.
native_vault_tested=False
if sys.platform=='win32':
    import bbolprom_engine.credentials as credentials
    original_target=credentials.TARGET
    credentials.TARGET='Bbolprom/SelfTest/'+uuid.uuid4().hex
    test_key='sk-synthetic-Windows-self-test-123456789'
    vault=credentials.WindowsCredentialStore()
    try:
        vault.save(test_key)
        assert vault.read()==test_key
        vault.delete()
        assert vault.read() is None
        native_vault_tested=True
    finally:
        try:vault.delete()
        finally:credentials.TARGET=original_target

with tempfile.TemporaryDirectory(prefix='bbolprom-smoke-') as folder:
    source=Path(folder)/'짧은_경로_😀.hwpx'
    text='😀 별빛이 비치는 우주선 조종실에서 인물이 홀로그램 패널을 조작한다.'
    image=b'original-unchanged-image-bytes'
    with zipfile.ZipFile(source,'w') as z:
        z.writestr('Contents/section0.xml','<hp:sec xmlns:hp="urn:hancom:hwpml:2011:paragraph"><hp:p><hp:run><hp:t>'+text+'</hp:t><hp:pic binaryItemIDRef="image1"/></hp:run></hp:p></hp:sec>')
        z.writestr('BinData/image1.png',image)
    with HWPXReader(source) as reader:result=analyze(reader)
    assert len(result['cards'])==1,result['result_stats']
    card=result['cards'][0]
    assert card['source_text']==text
    assert len(card['images'])==1
    assert card['images'][0]['digest']['md5']==hashlib.md5(image).hexdigest()
    assert card['images'][0]['digest']['sha1']==hashlib.sha1(image).hexdigest()
    connection=sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE test(text TEXT)')
    connection.execute('INSERT INTO test VALUES (?)',(text,))
    assert connection.execute('SELECT text FROM test').fetchone()[0]==text
    connection.close()
    store=BaselineStore(Library(Path(folder)/'library'),load_dataset())
    baseline=store.cards()
    assert len(baseline)==309
    assert len({c['source_text_sha256'] for c in baseline})==296
    assert sum(len(c['images']) for c in baseline)==531
    assert len(store.paths)==522
    assert baseline[187]['images']==[]
    assert [i['ref'] for i in baseline[108]['images']]==['image195']
    assert [i['ref'] for i in baseline[109]['images']]==['image'+str(i) for i in range(196,210)]
    assert sum(len(c['tags']) for c in baseline)==8471
    assert sum(len(t['spans']) for c in baseline for t in c['tags'])==10358
    assert load_approval_history()['master_sha256']==MASTER_SHA
    assert load_method_guidance()['master_sha256']==MASTER_SHA
    editions=BaselineTagEdits(store.library,store.records)
    tags=baseline[0]['tags']
    rows=[{'name':t['tag'],'category_id':t['category_column'],'source_index':i,
        'evidence':t['spans'][0]['evidence'] if t['spans'] else '', 'original_spans':t['spans']}
        for i,t in enumerate(tags)]
    rows[0]['name']='synthetic-manual-tag-self-test'
    from bbolprom_engine.tags import CATEGORIES
    categories=[{'id':cid,'name':name,'enabled':True} for cid,name in CATEGORIES.items()]
    assert editions.save(1,rows,categories,0)==1
    assert store.cards()==baseline
    assert editions.restore(1,0,1)==2
    assert editions.latest(1)['tags']==tags and len(editions.history(1))==3
    # Regression: Windows must be able to remove the backup's temporary DB.
    backup=store.library.backup()
    with zipfile.ZipFile(backup) as z:
        assert z.testzip() is None and 'library.sqlite3' in z.namelist()
    assert not list((store.library.root/'backup').glob('*.sqlite3'))
print(json.dumps({'runtime':sys.version,'platform':sys.platform,'native_vault_tested':native_vault_tested,'checks':['Unicode path','legacy diagnostic HWPX import','original text preservation','image MD5+SHA1','SQLite Unicode','309 fixed IDs including repeated prompts','531 image refs and 522 paths','109/110 and 188 baseline cases','8471 tags and 10358 spans','approval history and tagging method provenance','backup temporary SQLite closed before cleanup','baseline manual tags/history/original restore'],'external_api_called':False,'actual_PT_tested':False},ensure_ascii=False))
