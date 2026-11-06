"""Dependency-free OOXML export of a NEW library; never overwrites an approved file."""
import hashlib,json,zipfile
from xml.sax.saxutils import escape
from pathlib import Path

def export_xlsx(cards, path, category_names=None):
    path = Path(path)
    if path.exists(): raise FileExistsError('내보내기는 새 파일에만 허용됩니다')
    names = category_names or {}
    extra=sorted({str(t.get('category_id',t.get('category_column'))) for c in cards for t in c['tags'] if t.get('category_id',t.get('category_column')) not in (None,'','C','D','E','F','G','H','I')})
    columns=list('CDEFGHI')+extra
    rows = [['카드 ID','원본 프롬프트',*[names.get(col,col) for col in columns],'미분류','이미지 SHA256','상태']]
    evidence = [['카드 ID','태그','대분류 ID','시작 CP','끝 CP','원문 근거']]
    review = [['카드 ID','태그','최종 분류','최종 판단 사유','API 원래 제안','API 제안 분류','API 원래 판단 사유',
               '기존 표준 ID','기존 표준 이름','기존 표준 분류','보정·검토 사항','품질 규칙 버전']]
    standards={}
    for c in cards:
        if not c.get('approved'):continue
        for t in c['tags']:
            label=t.get('tag',t.get('name',''));cat=t.get('category_id',t.get('category_column'))
            if not cat:continue
            ident='std-'+hashlib.sha256((cat+'\0'+label).encode()).hexdigest()[:16]
            standards.setdefault(label,{})[ident]={'id':ident,'name':label,'category_id':cat}
    index = {}
    for c in cards:
        tags = c['tags']
        rows.append([str(c['id']),c['source_text'],*['\n'.join(t.get('tag',t.get('name','')) for t in tags
                      if t.get('category_id',t.get('category_column'))==col) for col in columns],
                     '\n'.join(t.get('tag',t.get('name','')) for t in tags if not t.get('category_id',t.get('category_column'))),
                     '\n'.join(i.get('sha') or i.get('ref','') for i in c['images']),c.get('analysis_status','approved_readonly')])
        for t in tags:
            name=t.get('tag',t.get('name','')); cat=t.get('category_id',t.get('category_column'))
            index.setdefault((name,str(cat or '')),[]).append(str(c['id']))
            proposals=t.get('api_proposals',[])
            refs=list(standards.get(name,{}).values())
            if t.get('standard_reference') and t['standard_reference'] not in refs:refs.append(t['standard_reference'])
            review.append([str(c['id']),name,str(cat or ''),t.get('reason',''),
                           json.dumps(proposals,ensure_ascii=False) if proposals else '',
                           '\n'.join(str(p.get('category_id') or '') for p in proposals),
                           '\n'.join(p.get('reason','') for p in proposals),
                           '\n'.join(r['id'] for r in refs),'\n'.join(r['name'] for r in refs),
                           '\n'.join(str(r['category_id'] or '') for r in refs),
                           '\n'.join(t.get('normalization_notes',[])),t.get('quality_version','')])
            for s in t.get('spans',[]):
                evidence.append([str(c['id']),name,str(cat or ''),str(s['start_cp']),str(s['end_cp']),s['evidence']])
    sheets=[('카드',rows),('통합태그색인',[['태그','대분류 ID','카드 IDs']]+[[n,c,', '.join(ids)] for (n,c),ids in sorted(index.items())]),('원문근거',evidence),('태그검수',review)]
    def sheet_xml(data):
        output=['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for i,row in enumerate(data,1):
            output.append(f'<row r="{i}">')
            for value in row:
                output.append('<c t="inlineStr"><is><t xml:space="preserve">'+escape(str(value))+'</t></is></c>')
            output.append('</row>')
        return ''.join(output)+'</sheetData></worksheet>'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        for i,(_,data) in enumerate(sheets,1): z.writestr(f'xl/worksheets/sheet{i}.xml',sheet_xml(data))
    return path
