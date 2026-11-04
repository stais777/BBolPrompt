"""User-library persistence tests using real SQLite/vault/OOXML output."""
import copy
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from bbolprom_engine.analysis import analyze
from bbolprom_engine.hwpx import HWPXReader
from bbolprom_engine.library import Library, sha_text
from bbolprom_engine.xlsx_export import export_xlsx


def source_file(path, texts, images):
    paragraphs=[]
    for i,text in enumerate(texts,1):
        paragraphs.append('<hp:p><hp:run><hp:t>'+escape(text)+'</hp:t><hc:img binaryItemIDRef="image'+str(i)+'"/></hp:run></hp:p>')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('Contents/section0.xml','<hp:sec xmlns:hp="urn:hwp:paragraph" xmlns:hc="urn:hwp:core">'+''.join(paragraphs)+'</hp:sec>')
        for i,image in enumerate(images,1):z.writestr('BinData/image'+str(i)+'.PNG',image)
    return path


def analyze_source(path):
    with HWPXReader(path) as reader:return analyze(reader)


class LibraryPersistence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.library=Library(self.root/'db')
    def tearDown(self):self.temp.cleanup()

    def test_exact_prompt_identity_and_same_prompt_image_merge(self):
        text='  😀 원문\n공백과 줄바꿈  '
        first=self.library.manual(text,[('같은파일.PNG',io.BytesIO(b'image-one'))])
        again=self.library.manual(text,[('다른파일.PNG',io.BytesIO(b'image-one'))])
        different=self.library.manual(text,[('같은파일.PNG',io.BytesIO(b'image-two'))])
        self.assertEqual(first,again);self.assertEqual(first,different)
        card=self.library.cards()[0]
        self.assertEqual(card['source_text'],text)
        self.assertEqual(card['sha'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(len(card['images']),2)
        self.assertEqual([x['position'] for x in card['images']],[0,1])
        self.assertEqual([x['filename'] for x in card['origins']],['같은파일.PNG','다른파일.PNG','같은파일.PNG'])
        for media in card['images']:
            payload=(self.library.root/media['path']).read_bytes()
            self.assertEqual(hashlib.md5(payload).hexdigest(),media['md5'])
            self.assertEqual(hashlib.sha1(payload).hexdigest(),media['sha1'])
            self.assertEqual(hashlib.sha256(payload).hexdigest(),media['sha'])
        whitespace_changed=self.library.manual(text.strip(),[])
        self.assertNotEqual(first,whitespace_changed)
        self.assertEqual(len(self.library.cards()),2)

    def test_hwpx_repeated_import_preserves_provenance_and_bytes(self):
        path=source_file(self.root/'first.hwpx',['프롬프트 한 장입니다.'],[b'original-unchanged-image'])
        result=analyze_source(path)
        before=path.read_bytes()
        first=self.library.commit_hwpx(path,result)
        renamed=self.root/'same-prompt-other-name.hwpx';renamed.write_bytes(before)
        renamed_result=analyze_source(renamed)
        self.assertEqual(self.library.plan(renamed_result)[0]['action'],'skip_identical')
        second=self.library.commit_hwpx(renamed,renamed_result)
        self.assertEqual(first,second)
        card=self.library.cards()[0]
        self.assertEqual(len(card['images']),1)
        self.assertEqual([x['filename'] for x in card['origins']],['first.hwpx','same-prompt-other-name.hwpx'])
        self.assertEqual((self.library.root/card['images'][0]['path']).read_bytes(),b'original-unchanged-image')
        self.assertEqual(path.read_bytes(),before)

    def test_same_batch_same_prompt_merges_multiple_images(self):
        path=source_file(self.root/'batch.hwpx',['같은 원문입니다.','같은 원문입니다.'],[b'first-image',b'second-image'])
        result=analyze_source(path)
        plan=self.library.plan(result)
        self.assertEqual([r['action'] for r in plan],['new_card','add_images'])
        ids=self.library.commit_hwpx(path,result)
        self.assertEqual(ids[0],ids[1]);self.assertEqual(len(self.library.cards()),1)
        self.assertEqual(len(self.library.cards()[0]['images']),2)

    def test_tampered_source_or_media_digest_rejected_and_database_rolls_back(self):
        path=source_file(self.root/'source.hwpx',['손상 검증 원문입니다.'],[b'untampered'])
        result=analyze_source(path)
        bad=copy.deepcopy(result);bad['cards'][0]['images'][0]['digest']['md5']='0'*32
        with self.assertRaisesRegex(ValueError,'해시'):self.library.commit_hwpx(path,bad)
        self.assertEqual(self.library.cards(),[])
        with self.library.connect() as c:
            for table in ('cards','media','card_media','origins'):
                self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'원본 파일'):self.library.commit_hwpx(path,result)
        self.assertEqual(self.library.cards(),[])

    def test_unresolved_images_cannot_be_silently_registered(self):
        path=source_file(self.root/'source.hwpx',['이미지 없는 참조'],[])
        result=analyze_source(path)
        with self.assertRaisesRegex(ValueError,'이미지'):self.library.commit_hwpx(path,result)
        self.assertEqual(self.library.cards(),[])

    def test_analysis_saves_unicode_spans_and_empty_evidence_without_changing_text(self):
        text='😀 복도에 서 있습니다.';cid=self.library.manual(text,[])
        result={'source_text':text,'status':'analyzed','tags':[{'tag':'복도','category_id':'F','spans':[{'start_cp':2,'end_cp':4,'evidence':'복도'}]}],
                'unclassified':[{'tag':'근거 없는 승인 보류','category_id':None,'spans':[]}]}
        self.library.save_analysis(cid,result)
        c=self.library.cards()[0];self.assertEqual(c['source_text'],text)
        self.assertEqual(len(c['tags']),2);self.assertEqual(c['tags'][1]['spans'],[])
        bad=copy.deepcopy(result);bad['tags'][0]['spans'][0]['start_cp']=3
        with self.assertRaisesRegex(ValueError,'근거'):self.library.save_analysis(cid,bad)
        self.assertEqual(self.library.cards()[0]['tags'],c['tags'])
        with self.assertRaisesRegex(ValueError,'원문'):self.library.save_analysis(cid,dict(result,source_text=text+' '))

    def test_backup_contains_restorable_db_and_original_media(self):
        cid=self.library.manual('백업 원문',[('sample.PNG',io.BytesIO(b'vault-image'))])
        self.library.set_setting('theme','dark')
        backup=self.library.backup()
        with zipfile.ZipFile(backup) as z:
            self.assertIsNone(z.testzip());self.assertIn('library.sqlite3',z.namelist())
            self.assertEqual(len([n for n in z.namelist() if n.startswith('vault/')]),1)
            restore=self.root/'restore';z.extractall(restore)
        restored=Library(restore)
        self.assertEqual(restored.cards(),self.library.cards())
        self.assertEqual(restored.get_setting('theme'),'dark')
        m=restored.cards()[0]['images'][0]
        self.assertEqual((restore/m['path']).read_bytes(),b'vault-image')

    def test_xlsx_preserves_text_spans_and_index_and_never_overwrites(self):
        text='  😀 <복도> & "장면"\n줄바꿈  '
        cards=[{'id':'card-1','source_text':text,'images':[],
                 'tags':[{'name':'복도','category_id':'F','spans':[{'start_cp':5,'end_cp':7,'evidence':'복도'}]},
                         {'name':'미분류 태그','category_id':None,'spans':[]}]}]
        out=self.root/'새 마스터.xlsx';export_xlsx(cards,out)
        ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(out) as z:
            self.assertIsNone(z.testzip())
            for n in z.namelist():ET.fromstring(z.read(n))
            text_values=[''.join(t.itertext()) for t in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//x:t',ns)]
            self.assertIn(text,text_values)
            index=z.read('xl/worksheets/sheet2.xml').decode()
            self.assertIn('복도',index);self.assertIn('미분류 태그',index)
            evidence=z.read('xl/worksheets/sheet3.xml').decode()
            self.assertIn('복도',evidence);self.assertIn('card-1',evidence)
        before=out.read_bytes()
        with self.assertRaises(FileExistsError):export_xlsx(cards,out)
        self.assertEqual(out.read_bytes(),before)

    def test_xlsx_keeps_user_created_category_in_per_card_export(self):
        cards=[{'id':'new-card','source_text':'우주선 조종실의 별 지도','images':[],
                'tags':[{'name':'별 지도','category_id':'user-category-space','spans':[]}]}]
        out=self.root/'custom-categories.xlsx'
        export_xlsx(cards,out,category_names={'user-category-space':'사용자 우주 소품'})
        ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(out) as z:
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            rows=sheet.findall('x:sheetData/x:row',ns)
            header=[''.join(c.itertext()) for c in rows[0]]
            values=[''.join(c.itertext()) for c in rows[1]]
            self.assertIn('사용자 우주 소품',header)
            self.assertEqual(values[header.index('사용자 우주 소품')],'별 지도')


if __name__=='__main__':unittest.main()
