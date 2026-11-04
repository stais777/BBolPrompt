"""Regenerate ONLY derived read-only decision context from the pinned master.

Development tool, requires openpyxl. The master is opened read-only and never
saved. Production semantic inference does not open the workbook or baselines.
"""
import argparse
import hashlib
import json
from pathlib import Path
import openpyxl

APPROVED_SHA='b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'
SHEETS=['B_001-309_최종승인사전','C_001-150_승인사전29종','가로_다음차수적용기준','가로2차_다음차수적용기준']

def build(workbook,lexicon,destination):
    workbook=Path(workbook);sha=hashlib.sha256(workbook.read_bytes()).hexdigest()
    if sha!=APPROVED_SHA:raise ValueError('Approved master checksum mismatch; refusing extraction')
    wb=openpyxl.load_workbook(workbook,read_only=True,data_only=True)
    records=[]
    try:
        for name in SHEETS:
            sheet=wb[name];i=wb.sheetnames.index(name)+1
            rows=iter(sheet.values);headers=next(rows)
            for no,row in enumerate(rows,2):
                fields={str(k):v for k,v in zip(headers,row) if k and v is not None}
                if not any('승인' in str(v) for k,v in fields.items() if '상태' in k):continue
                records.append({'id':f'approved-{i}-{no}','fields':fields,
                    'provenance':{'file':workbook.name,'sha256':sha,'sheet':sheet.title,'row':no},
                    'scope':'approved normalization decision; contextual exceptions apply; not a universal substitution'})
    finally:wb.close()
    terms=json.loads(Path(lexicon).read_text(encoding='utf8'))['terms']
    standards=[{'id':'std-'+hashlib.sha256((x['category_column']+'\0'+x['tag']).encode()).hexdigest()[:16],
                'name':x['tag'],'category_id':x['category_column']} for x in terms]
    output={'schema':'bbolprom-approved-context-1','source_sha256':sha,'standards':standards,'decisions':records}
    Path(destination).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workbook');p.add_argument('destination')
    p.add_argument('--lexicon',default=str(Path(__file__).resolve().parents[1]/'bbolprom_engine/lexicon/approved_terms_only.json'))
    args=p.parse_args();result=build(args.workbook,args.lexicon,args.destination)
    print(len(result['standards']),'standard category/name rows;',len(result['decisions']),'approval decisions')
