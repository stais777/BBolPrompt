"""One isolation regression, not evidence of actual PT boundary correctness.

The known 309 benchmark/read-only gallery must never determine a new document's
card count. An attempt to read per-card gold/context makes this test fail.
"""
import builtins
import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from bbolprom_engine.analysis import analyze
from bbolprom_engine.hwpx import HWPXReader


class GenericImportIndependence(unittest.TestCase):
    def test_two_new_cards_analyze_with_catalog_baseline_and_context_reads_forbidden(self):
        texts=['독립 신규 카드 하나. 임의 숫자 417과 이모지 😀를 그대로 보존합니다.',
               '  별개의 신규 카드 둘. 승인 원문과 무관한 장면입니다.  ']
        media=[b'unique-independent-first-image',b'unique-independent-second-image']
        forbidden={'approved_catalog.json','approved_baseline_309.json','approved_context.json'}
        attempts=[]
        builtin_open=builtins.open
        path_open=Path.open

        def check(path):
            if isinstance(path,(str,bytes,os.PathLike)):
                name=Path(os.fsdecode(os.fspath(path))).name.casefold()
                if name in forbidden:
                    attempts.append(name)
                    raise AssertionError('Generic inference attempted protected reference read: '+name)

        def guarded_builtin_open(path,*args,**kwargs):
            check(path)
            return builtin_open(path,*args,**kwargs)

        def guarded_path_open(path,*args,**kwargs):
            check(path)
            return path_open(path,*args,**kwargs)

        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'unrelated-two-cards.hwpx'
            paragraphs=[]
            for i,text in enumerate(texts,1):
                paragraphs.append('<hp:p><hp:run><hp:t>'+escape(text)+'</hp:t><hc:img binaryItemIDRef="fresh'+str(i)+'"/></hp:run></hp:p>')
            with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('Contents/section0.xml','<hp:sec xmlns:hp="urn:hwp:paragraph" xmlns:hc="urn:hwp:core">'+''.join(paragraphs)+'</hp:sec>')
                for i,raw in enumerate(media,1):z.writestr('BinData/fresh'+str(i)+'.PNG',raw)
            original=source.read_bytes()
            with patch('builtins.open',new=guarded_builtin_open),patch.object(Path,'open',new=guarded_path_open):
                # Prove both common file-opening paths would catch a protected read.
                with self.assertRaises(AssertionError):builtins.open(Path(temp)/'approved_baseline_309.json')
                with self.assertRaises(AssertionError):(Path(temp)/'approved_catalog.json').open()
                attempts.clear()
                with HWPXReader(source) as reader:
                    result=analyze(reader,segmentation='auto',knowledge_mode='generic')
                self.assertEqual(attempts,[])
            self.assertEqual(result['result_stats']['card_count'],2)
            self.assertEqual([c['source_text'] for c in result['cards']],texts)
            self.assertEqual(result['file']['sha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(result['result_stats']['image_references_resolved'],2)
            for card,raw in zip(result['cards'],media):
                self.assertEqual(len(card['images']),1)
                digest=card['images'][0]['digest']
                self.assertEqual(digest['bytes'],len(raw))
                self.assertEqual(digest['md5'],hashlib.md5(raw).hexdigest())
                self.assertEqual(digest['sha1'],hashlib.sha1(raw).hexdigest())
                self.assertEqual(digest['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(source.read_bytes(),original)


if __name__=='__main__':unittest.main()
