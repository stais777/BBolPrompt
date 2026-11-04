"""Image-free, local-only source evidence for reproducing import failures.

Raw XML contains prompt text and document structure. Nothing is uploaded here.
This module never reads the approved catalogue, chooses boundaries, or writes DBs.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
from .analysis import file_sha256
from .hwpx import HWPXReader, HWPXError

SCHEMA = 'bbolprom-structure-diagnostic-1'
MAX_DIAGNOSTIC_XML_BYTES = 300 * 1024 * 1024

def collect_structure(source, result, destination):
    """Write a NEW ZIP: report.json + unchanged source XML/HPF under source/.

    BinData, previews, thumbnails and all other non-XML entries are excluded.
    The result is a reproduction input, not proof of corrected PT extraction.
    """
    source, destination = Path(source), Path(destination)
    if destination.exists(): raise FileExistsError('진단 파일은 새 경로에만 저장할 수 있습니다')
    if destination.resolve() == source.resolve(): raise ValueError('원본과 진단 경로가 같습니다')
    if file_sha256(source) != result['file']['sha256']:
        raise ValueError('분석 이후 원본이 변경되어 진단 생성을 중단했습니다')
    with HWPXReader(source) as reader:
        paragraphs, stats = reader.read_paragraphs()
        selected=[]
        for info in reader.members:
            name=info.filename
            path=PurePosixPath(name.replace('\\','/'))
            if path.is_absolute() or '..' in path.parts or str(path)!=name:
                raise HWPXError('안전하지 않은 HWPX 구성 경로')
            lower=name.casefold()
            is_contents=lower.startswith('contents/') and lower.endswith(('.xml','.hpf'))
            is_meta=lower in ('meta-inf/manifest.xml','meta-inf/container.xml','version.xml','settings.xml')
            if (is_contents or is_meta) and 'bindata' not in (part.casefold() for part in path.parts):
                selected.append(info)
        if sum(i.file_size for i in selected)>MAX_DIAGNOSTIC_XML_BYTES:
            raise HWPXError('진단 XML 총량 제한을 초과했습니다')
        report={
            'schema':SCHEMA,
            'notice':'원문과 문서 XML 포함. 이미지/미디어 바이트 미포함. 로컬 저장만 수행하며 자동 전송하지 않습니다.',
            'source':result['file'],
            'source_stats':stats,
            'extraction':{'card_count':len(result['cards']),
                'image_reference_count':sum(len(c['images']) for c in result['cards']),
                'segmentation_mode':result.get('segmentation_mode'),
                'heuristics':result.get('segmentation_heuristics'),
                'cards':[{'engine_card':c['engine_card'],'paragraph_ids':c.get('paragraph_ids',[]),
                    'source_text_sha256':c['source_text_sha256'],'source_chars':len(c['source_text']),
                    'image_refs':[im['ref'] for im in c['images']],
                    'warnings':c.get('warnings',[])} for c in result['cards']]},
            'paragraphs':[{'index':p.index,'section':p.section,'container':p.container,
                'break_before':p.break_before,'text_chars':len(p.text),'has_text':bool(p.text.strip()),
                'text_sha256':hashlib.sha256(p.text.encode('utf8')).hexdigest(),
                'image_refs':p.image_refs} for p in paragraphs],
            'source_members':[{'name':i.filename,'bytes':i.file_size,'crc32':f'{i.CRC:08x}',
                               'xml_included':i in selected} for i in reader.members],
            'included_xml':[],
            'actual_PT_quality_tested':False,
            'originals_modified':False,
        }
        destination.parent.mkdir(parents=True,exist_ok=True)
        try:
            with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as out:
                for info in selected:
                    raw=reader.zip.read(info.filename)
                    out.writestr('source/'+info.filename,raw)
                    report['included_xml'].append({'name':info.filename,'bytes':len(raw),
                        'sha256':hashlib.sha256(raw).hexdigest()})
                out.writestr('report.json',json.dumps(report,ensure_ascii=False,indent=2))
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return report
