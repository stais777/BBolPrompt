"""Compare independent old/new segmentation on controlled HWPX, never PT gold.
Synthetic results are explicitly not estimates of actual PT accuracy.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys,tempfile,zipfile
from pathlib import Path
from xml.sax.saxutils import escape

PROBE='''import json,sys
from bbolprom_engine.hwpx import HWPXReader
from bbolprom_engine.analysis import analyze
with HWPXReader(sys.argv[1]) as reader:r=analyze(reader,knowledge_mode="generic")
print(json.dumps({"cards":[{"text":c["source_text"],"refs":[i["ref"] for i in c["images"]]} for c in r["cards"]],"stats":r["result_stats"],"mode":r["segmentation_mode"]},ensure_ascii=False))'''

def paragraph(text='',refs=(),extra=''):
    imgs=''.join(f'<hp:pic><hc:img binaryItemIDRef="{escape(ref)}"/></hp:pic>' for ref in refs)
    return f'<hp:p><hp:run><hp:t>{escape(text)}</hp:t>{imgs}{extra}</hp:run></hp:p>'

def write_hwpx(path,body,refs):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('Contents/section0.xml','<hs:sec xmlns:hs="urn:hancom:section" xmlns:hp="urn:hancom:paragraph" xmlns:hc="urn:hancom:core">'+body+'</hs:sec>')
        for ref in refs:z.writestr('BinData/'+ref+'.PNG',b'original-test-image-bytes:'+ref.encode())

def run(root,fixture):
    p=subprocess.run([sys.executable,'-c',PROBE,str(fixture)],cwd=root,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(f'Probe failed in {root}: {p.stderr}')
    return json.loads(p.stdout)

def evaluate(old,new,handoff):
    rows=[]
    with tempfile.TemporaryDirectory() as d:
        d=Path(d)
        cases=[]
        a=['첫 카드 원문의 첫 문장입니다. 원문 공백을 유지합니다.','😀 첫 카드의 두 번째 문단에는 비율 9:16 설명이 있습니다.']
        b=['둘째 카드에는 정사각형 이미지가 연결됩니다.','둘째 문단의 끝 공백도 보존합니다.  ']
        body=''.join(paragraph(t) for t in a)+paragraph(refs=['image1','image2'])+''.join(paragraph(t) for t in b)+paragraph(refs=['image3'])
        cases.append(('multi_paragraph_trailing_images',body,['image1','image2','image3'],[{'text':'\n'.join(a),'refs':['image1','image2']},{'text':'\n'.join(b),'refs':['image3']}]))
        body=paragraph(extra='<hp:tbl><hp:tr><hp:tc><hp:subList>'+paragraph('테이블 첫 행 원문입니다.',['image1'])+'</hp:subList></hp:tc></hp:tr><hp:tr><hp:tc><hp:subList>'+paragraph('테이블 둘째 행 원문입니다.',['image2'])+'</hp:subList></hp:tc></hp:tr></hp:tbl>')
        cases.append(('nested_table_single_visit',body,['image1','image2'],[{'text':'테이블 첫 행 원문입니다.','refs':['image1']},{'text':'테이블 둘째 행 원문입니다.','refs':['image2']}]))
        for name,body,refs,expected in cases:
            p=d/(name+'.hwpx');write_hwpx(p,body,refs)
            outputs={version:run(root,p) for version,root in [('alpha_0_2',old),('new',new)]}
            measurements={}
            for version,r in outputs.items():
                exact=sum(c==expected[i] for i,c in enumerate(r['cards']) if i<len(expected))
                measurements[version]={'card_count':len(r['cards']),'expected_card_count':len(expected),'exact_text_and_image_cards_by_position':exact,'exact_all':r['cards']==expected,'image_reference_count':sum(len(c['refs']) for c in r['cards']),'mode':r['mode']}
            rows.append({'fixture':name,'kind':'new controlled synthetic, no approved PT text','input_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'measurements':measurements})
    supplied=handoff/'06_개발참고/_v07_small_simulated.hwpx'
    supplied_outputs={version:run(root,supplied) for version,root in [('alpha_0_2',old),('new',new)]}
    supplied_summary={version:{'card_count':len(r['cards']),'image_reference_count':sum(len(c['refs']) for c in r['cards']),'mode':r['mode']} for version,r in supplied_outputs.items()}
    return {'schema':'bbolprom-controlled-structural-regression-v1','fixtures':rows,'supplied_simulated_hwpx':{'input_sha256':hashlib.sha256(supplied.read_bytes()).hexdigest(),'measurements':supplied_summary,'limitations':'Supplied generated file contains 309 single-paragraph cards and one unused BMP asset and zero XML image references, not actual PT geometry or 531 references. No tag-quality claim.'},'actual_pt_improvement':{'status':'not_measured','reason':'Original PT.hwpx absent; historical A/B input SHA differs from all synthetic inputs.'}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--handoff',required=True,type=Path);p.add_argument('--new',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,default=Path(__file__).with_name('structural-regression.json'));a=p.parse_args()
    d=evaluate(a.handoff/'03_현행코드/Alpha_v0.2',a.new,a.handoff);a.out.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(d,ensure_ascii=False,indent=2))
    raise SystemExit(any(not x['measurements']['new']['exact_all'] for x in d['fixtures']))
