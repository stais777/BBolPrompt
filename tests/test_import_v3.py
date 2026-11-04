"""Structural regression fixtures; none contain approved card text or labels."""
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from bbolprom_engine.hwpx import HWPXReader, HWPXError
from bbolprom_engine.analysis import analyze, split_cards, pick_mode

NS = 'urn:hancom:hwpml:2011:paragraph'
def p(text='', refs=(), attr=''):
    return '<hp:p '+attr+'><hp:run><hp:t>'+text+'</hp:t>'+''.join(
        '<hp:pic><hp:img binaryItemIDRef="'+r+'"/></hp:pic>' for r in refs)+'</hp:run></hp:p>'

def document(path, body, second=None, meta=''):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('Contents/section0.xml', '<hp:sec xmlns:hp="'+NS+'">'+body+'</hp:sec>')
        if second is not None:z.writestr('Contents/section1.xml', '<hp:sec xmlns:hp="'+NS+'">'+second+'</hp:sec>')
        if meta:z.writestr('Contents/content.hpf',meta)
        for i in range(1,11):z.writestr('BinData/image'+str(i)+'.png',b'original-image-'+bytes([i]))
    return path

class StructuralImport(unittest.TestCase):
    def run_body(self, body, second=None, meta=''):
        with tempfile.TemporaryDirectory() as tmp:
            path=document(Path(tmp)/'fixture.hwpx',body,second,meta)
            source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
            with HWPXReader(path) as r:
                paras, stats=r.read_paragraphs()
                result=analyze(r)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source_hash)
            return paras,stats,result

    def test_multiline_trailing_images_do_not_split_each_paragraph(self):
        _,stats,r=self.run_body(p('첫 카드 첫 문단')+p('첫 카드 둘째 문단')+p('',('image1','image2'))+
                              p('둘째 카드 첫 문단')+p('둘째 카드 둘째 문단')+p('',('image3',)))
        self.assertEqual(r['result_stats']['card_count'],2)
        self.assertEqual([c['source_text'] for c in r['cards']],['첫 카드 첫 문단\n첫 카드 둘째 문단','둘째 카드 첫 문단\n둘째 카드 둘째 문단'])
        self.assertEqual([[i['ref'] for i in c['images']] for c in r['cards']],[['image1','image2'],['image3']])
        self.assertEqual(stats['image_ref_count'],3)
        self.assertEqual(r['segmentation_heuristics']['candidate_counts']['paragraph'],4)

    def test_leading_images_multiple_paragraphs_and_blank_spacing(self):
        _,_,r=self.run_body(p('',('image1',))+p()+p('원문 A')+p('계속 A')+
                              p('',('image2','image3'))+p('원문 B')+p('계속 B'))
        self.assertEqual([c['source_text'] for c in r['cards']],['원문 A\n계속 A','원문 B\n계속 B'])
        self.assertEqual([len(c['images']) for c in r['cards']],[1,2])

    def test_nested_table_paragraphs_not_duplicated_and_row_images_pair(self):
        table='<hp:p><hp:run><hp:tbl>'
        for i in (1,2):
            table+='<hp:tr><hp:tc><hp:subList>'+p('',('image'+str(i),))+'</hp:subList></hp:tc>'
            table+='<hp:tc><hp:subList>'+p('카드 '+str(i))+p('다음 문단')+'</hp:subList></hp:tc></hp:tr>'
        table+='</hp:tbl></hp:run></hp:p>'
        paras,stats,r=self.run_body(table)
        self.assertEqual(stats['image_ref_count'],2)
        self.assertEqual(stats['paragraph_count'],6)
        self.assertEqual([c['source_text'] for c in r['cards']],['카드 1\n다음 문단','카드 2\n다음 문단'])
        self.assertEqual([[i['ref'] for i in c['images']] for c in r['cards']],[['image1'],['image2']])
        self.assertEqual(len({p.index for p in paras}),len(paras))

    def test_outer_text_before_and_after_nested_content_in_document_order(self):
        nested='<hp:p><hp:run><hp:t>앞</hp:t><hp:tbl><hp:tr><hp:tc>'+p('안')+'</hp:tc></hp:tr></hp:tbl><hp:t>뒤</hp:t></hp:run></hp:p>'
        paras,_,_=self.run_body(nested)
        self.assertEqual([p.text for p in paras],['앞','안','뒤'])

    def test_inline_images_and_unicode_controls_preserved(self):
        _,_,r=self.run_body(p('🙂 한글<hp:tab/>A<hp:lineBreak/>B\n',('image1','image2'))+p('둘째',('image3',)))
        self.assertEqual(r['cards'][0]['source_text'],'🙂 한글\tA\nB\n')
        self.assertEqual(r['result_stats']['card_count'],2)
        self.assertEqual(r['result_stats']['image_references_resolved'],3)
        self.assertEqual(r['cards'][0]['images'][0]['digest']['md5'],hashlib.md5(b'original-image-\x01').hexdigest())

    def test_page_section_and_blank_delimiters(self):
        _,_,r=self.run_body(p('첫 문단')+p('계속')+p()+p('둘째')+p('셋째',attr='pageBreak="1"'),p('넷째'))
        self.assertEqual([c['source_text'] for c in r['cards']],['첫 문단\n계속','둘째','셋째','넷째'])

    def test_manifest_image_id_resolution_and_unresolved_reference(self):
        _,_,r=self.run_body(p('카드',('custom','missing')),meta='<package><item id="custom" href="../BinData/image1.png"/></package>')
        # HWPX common relative href ../BinData is resolved by basename fallback.
        self.assertEqual(r['result_stats']['image_references_resolved'],1)
        self.assertEqual(r['unresolved_images'],[{'engine_card':1,'ref':'missing'}])

    def test_empty_and_orphan_documents(self):
        _,_,empty=self.run_body(p()+p('  '))
        self.assertEqual(empty['cards'],[])
        _,_,orphan=self.run_body(p('',('image1',)))
        self.assertEqual(len(orphan['cards']),1)
        self.assertIn('프롬프트 텍스트 없음',orphan['cards'][0]['warnings'])

    def test_text_only_ambiguity_reported_and_explicit_modes_retained(self):
        paras,_,r=self.run_body(p('첫째')+p('둘째'))
        self.assertEqual(len(r['cards']),2)
        self.assertTrue(all('잠정값' in c['warnings'][0] for c in r['cards']))
        self.assertEqual(len(split_cards(paras,'paragraph')),2)
        self.assertEqual(len(split_cards(paras,'blank')),1)
        self.assertEqual(pick_mode(paras)[0],'structure')

    def test_xml_entities_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.hwpx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('Contents/section0.xml','<!DOCTYPE a [<!ENTITY x "boom">]><a/>')
            with HWPXReader(path) as reader:
                with self.assertRaises(HWPXError):reader.read_paragraphs()

    def test_one_through_ten_multiline_cards(self):
        for count in range(1,11):
            with self.subTest(count=count):
                body=''.join(p('카드 '+str(i))+p('계속 '+str(i))+p('',('image'+str(i),)) for i in range(1,count+1))
                _,_,r=self.run_body(body)
                self.assertEqual(len(r['cards']),count)
                self.assertEqual([c['source_text'] for c in r['cards']],['카드 '+str(i)+'\n계속 '+str(i) for i in range(1,count+1)])
                self.assertEqual(r['result_stats']['image_references_resolved'],count)

    def test_spaced_multiple_trailing_images_and_repeated_refs_preserved(self):
        _,_,r=self.run_body(p('첫째')+p('',('image1',))+p()+p('',('image2','image2'))+p('둘째',('image3',)))
        self.assertEqual(len(r['cards']),2)
        self.assertEqual([i['ref'] for i in r['cards'][0]['images']],['image1','image2','image2'])
        self.assertEqual(r['source_stats']['image_ref_count'],4)

if __name__=='__main__':unittest.main()
