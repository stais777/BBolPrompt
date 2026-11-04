"""Packaged Windows runtime smoke check; does not call external APIs or use PT answers."""
from pathlib import Path
import hashlib,json,sqlite3,sys,tempfile,zipfile
package=Path(__file__).resolve().parent
sys.path.insert(0,str(package/'app'))
from bbolprom_engine.hwpx import HWPXReader
from bbolprom_engine.analysis import analyze

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
print(json.dumps({'runtime':sys.version,'platform':sys.platform,'checks':['Unicode path','HWPX import','original text preservation','image MD5+SHA1','SQLite Unicode'],'external_api_called':False,'actual_PT_tested':False},ensure_ascii=False))
