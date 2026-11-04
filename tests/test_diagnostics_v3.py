"""Local, image-free HWPX source-evidence exports; no PT quality claim."""
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from bbolprom_engine.analysis import analyze
from bbolprom_engine.diagnostics import collect_structure,SCHEMA
from bbolprom_engine.hwpx import HWPXReader,HWPXError


def diagnostic_source(path,extra=None):
    section=('''<hp:sec xmlns:hp="urn:hwp:paragraph" xmlns:hc="urn:hwp:core">
<hp:p><hp:run><hp:t>😀 첫 문단의 원문.  </hp:t><hc:img binaryItemIDRef="image1"/></hp:run></hp:p>
<hp:p pageBreak="1"><hp:run><hp:t>두 번째 카드의 문단.</hp:t></hp:run></hp:p>
<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>표 셀의 후속 문단</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>
</hp:sec>''').encode('utf8')
    originals={'Contents/section0.xml':section,
       'Contents/header.xml':b'<head><charProperties/></head>',
       'Contents/content.hpf':b'<package><item id="image1" href="BinData/image1.PNG"/></package>',
       'META-INF/manifest.xml':b'<manifest><file path="Contents/section0.xml"/></manifest>',
       'META-INF/container.xml':b'<container><rootfile path="Contents/content.hpf"/></container>',
       'version.xml':b'<version major="1"/>','settings.xml':b'<settings keep="true"/>'}
    excluded={'BinData/image1.PNG':b'UNIQUE_BIN_IMAGE_BYTES_DO_NOT_EXPORT',
       'BinData/disguised.xml':b'UNIQUE_BIN_XML_NAMED_PAYLOAD_DO_NOT_EXPORT',
       'Contents/BinData/disguised.xml':b'UNIQUE_NESTED_BIN_XML_PAYLOAD_DO_NOT_EXPORT',
       'Preview/PrvImage.png':b'UNIQUE_PREVIEW_IMAGE_DO_NOT_EXPORT',
       'Preview/PrvText.txt':b'UNIQUE_PREVIEW_TEXT_DO_NOT_EXPORT',
       'Contents/thumbnail.png':b'UNIQUE_THUMBNAIL_IMAGE_DO_NOT_EXPORT',
       'arbitrary-private.txt':b'UNIQUE_OTHER_BYTES_DO_NOT_EXPORT'}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,raw in {**originals,**excluded,**(extra or {})}.items():z.writestr(name,raw)
    return originals,excluded


def analyzed(path):
    with HWPXReader(path) as reader:return analyze(reader)


class StructureDiagnosticExport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_original_xml_and_structural_report_export_without_any_image_or_preview_payload(self):
        source=self.root/'source.hwpx';originals,excluded=diagnostic_source(source)
        before=source.read_bytes();result=analyzed(source);unchanged=copy.deepcopy(result)
        destination=self.root/'evidence.diagnostic.zip'
        report=collect_structure(source,result,destination)
        self.assertEqual(result,unchanged);self.assertEqual(source.read_bytes(),before)
        with zipfile.ZipFile(destination) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(set(z.namelist()),{'report.json'}|{'source/'+name for name in originals})
            actual=json.loads(z.read('report.json'))
            self.assertEqual(actual,report);self.assertEqual(actual['schema'],SCHEMA)
            self.assertEqual(actual['source']['sha256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(actual['extraction']['card_count'],len(result['cards']))
            self.assertEqual(actual['extraction']['image_reference_count'],1)
            self.assertEqual([c['paragraph_ids'] for c in actual['extraction']['cards']],[c['paragraph_ids'] for c in result['cards']])
            self.assertEqual(len(actual['paragraphs']),3)
            self.assertEqual(actual['paragraphs'][0]['image_refs'],['image1'])
            self.assertEqual(actual['paragraphs'][0]['text_sha256'],hashlib.sha256('😀 첫 문단의 원문.  '.encode()).hexdigest())
            self.assertTrue(actual['paragraphs'][1]['break_before'])
            self.assertIsNotNone(actual['paragraphs'][2]['container'])
            self.assertFalse(actual['actual_PT_quality_tested']);self.assertFalse(actual['originals_modified'])
            members={x['name']:x for x in actual['source_members']}
            included={x['name']:x for x in actual['included_xml']}
            for name,raw in originals.items():
                self.assertEqual(z.read('source/'+name),raw)
                self.assertEqual(included[name]['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertTrue(members[name]['xml_included'])
            all_uncompressed=b''.join(z.read(name) for name in z.namelist())
            for name,raw in excluded.items():
                self.assertFalse(members[name]['xml_included'])
                self.assertNotIn(raw,all_uncompressed)

    def test_changed_source_rejected_and_existing_destination_never_overwritten(self):
        source=self.root/'source.hwpx';diagnostic_source(source);result=analyzed(source)
        destination=self.root/'evidence.zip';collect_structure(source,result,destination)
        first=destination.read_bytes()
        with self.assertRaises(FileExistsError):collect_structure(source,result,destination)
        self.assertEqual(destination.read_bytes(),first)
        source.write_bytes(source.read_bytes()+b'changed-after-analysis')
        with self.assertRaisesRegex(ValueError,'원본'):collect_structure(source,result,self.root/'should-not-exist.zip')
        self.assertFalse((self.root/'should-not-exist.zip').exists())

    def test_unsafe_source_member_path_rejected_without_diagnostic_output(self):
        source=self.root/'unsafe.hwpx';diagnostic_source(source,{'../outside.xml':b'<outside/>'})
        result=analyzed(source);before=source.read_bytes();destination=self.root/'must-not-exist.zip'
        with self.assertRaisesRegex(HWPXError,'경로'):collect_structure(source,result,destination)
        self.assertFalse(destination.exists());self.assertEqual(source.read_bytes(),before)


if __name__=='__main__':unittest.main()
