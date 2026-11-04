"""Run with: python -m unittest discover -s tests -v"""
import json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from bbolprom_engine.hwpx import HWPXReader
from bbolprom_engine.analysis import analyze
from bbolprom_engine.tags import run_tag_pipeline,horizontal_normalize
from bbolprom_engine.master import export_results,build_index
from bbolprom_engine.registry import build_plan,register
from bbolprom_engine.knowledge import load_terms

def make_hwpx(path, duplicate=False):
    ns='urn:hancom:hwpml:2011:paragraph'
    texts=['승무원 제복과 하이힐을 착용한 인물이 항공기 기내에서 정면 구도로 서 있습니다.',
           '호텔 침실에 놓인 테이블 옆에서 드레스를 입은 인물이 앉아 있습니다.']
    if duplicate:texts=[texts[0],texts[0]]
    blocks=[]
    for i,t in enumerate(texts,1):
        blocks.append(f'<hp:p><hp:run><hp:t>{t}</hp:t><hp:pic binaryItemIDRef="image{i}"/></hp:run></hp:p>')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('Contents/section0.xml','<hp:sec xmlns:hp="'+ns+'">'+''.join(blocks)+'</hp:sec>')
        z.writestr('BinData/image1.JPG',b'fake-jpg-content-1')
        z.writestr('BinData/image2.JPG',b'fake-jpg-content-2')
    return path

class EngineWorkflow(unittest.TestCase):
    def test_all_pipeline_stages(self):
        text='승무원 제복과 하이힐, 항공기 기내. 9:16 세로 구도.'
        result=run_tag_pipeline(text)
        tags={(x['category_column'],x['tag']) for x in result['tags']}
        self.assertIn(('E','승무원 제복'),tags)
        self.assertIn(('E','하이힐'),tags)
        self.assertIn(('F','항공기 기내'),tags)
        self.assertIn(('H','9:16 세로 구도'),tags)
        self.assertNotIn(('E','제복'),tags) # nested synonym removed within same evidence
        for t in result['tags']:
            for s in t['spans']:
                self.assertEqual(text[s['start_cp']:s['end_cp']],s['evidence'])
        self.assertEqual(result['stats']['validated_highlight_spans'],
                         sum(len(t['spans']) for t in result['tags']))

    def test_ambiguous_multicolumn_to_review(self):
        cand=[{'category_column':cat,'tag':'같은말','spans':[{'start_cp':0,'end_cp':3,'evidence':'같은말'}]}
              for cat in ('G','I')]
        tags,audit=horizontal_normalize(cand)
        self.assertEqual(tags,[])
        self.assertEqual(audit[0]['operation'],'review_cross_category')
        self.assertEqual(len(audit[0]['candidate_tags']),2)

    def test_synthetic_images_hashes_and_index(self):
        with tempfile.TemporaryDirectory() as d:
            src=make_hwpx(Path(d)/'sample.hwpx')
            with HWPXReader(src) as reader:
                result=analyze(reader,segmentation='auto')
            self.assertEqual(result['result_stats']['card_count'],2)
            self.assertEqual(result['result_stats']['image_references_resolved'],2)
            self.assertEqual(result['result_stats']['image_references_unresolved'],0)
            self.assertTrue(all(len(c['images'])==1 for c in result['cards']))
            self.assertIn('md5',result['cards'][0]['images'][0]['digest'])
            output=Path(d)/'out';export_results(output,result)
            self.assertTrue((output/'integrated_tag_index.json').exists())
            self.assertTrue((output/'draft_master.csv').exists())
            self.assertGreater(build_index(result)['unique_tags'],0)

    def test_registration_review_then_commit_and_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            src=make_hwpx(Path(d)/'new.hwpx')
            with HWPXReader(src) as reader:result=analyze(reader,segmentation='auto')
            db=Path(d)/'local_db'
            before=register(result,src,db,commit=False)
            self.assertEqual(before['summary']['new_card'],2)
            self.assertFalse((db/'cards.sqlite3').exists())
            commit=register(result,src,db,commit=True)
            self.assertTrue((db/'cards.sqlite3').exists())
            conn=sqlite3.connect(db/'cards.sqlite3')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM images').fetchone()[0],2)
            conn.close()
            repeat=register(result,src,db,commit=False)
            self.assertEqual(repeat['summary']['skip_identical'],2)
            self.assertEqual(repeat['summary']['new_card'],0)

    def test_same_prompt_two_images_merge_in_single_batch(self):
        with tempfile.TemporaryDirectory() as d:
            src=make_hwpx(Path(d)/'duplicate.hwpx',duplicate=True)
            with HWPXReader(src) as reader:result=analyze(reader,segmentation='auto')
            db=Path(d)/'db'
            plan=build_plan(result,db)
            self.assertEqual(plan['summary']['new_card'],1)
            self.assertEqual(plan['summary']['merge_to_new_batch_card'],1)
            register(result,src,db,commit=True)
            conn=sqlite3.connect(db/'cards.sqlite3')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM card_images').fetchone()[0],2)
            conn.close()

    def test_approved_vocabulary_has_no_card_identifiers(self):
        terms=load_terms('approved_terms')
        self.assertGreaterEqual(len(terms),2000)
        self.assertTrue(all(set(t)=={'category_column','tag'} for t in terms))

if __name__=='__main__':unittest.main()
