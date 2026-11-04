"""Read-only evidence audit. No source cards are used by production inference.
Run: python evaluation/audit_handoff.py --handoff /path/to/extracted/handoff
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re,zipfile
from pathlib import Path
from collections import Counter
from xml.etree import ElementTree as ET

MASTER_SHA='b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'
PT_SHA='c5d52ce0cda5901d9da178f88c8d5c2eeb5614eefa5a0546916e4951df881ddf'
NS={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def sheet_rows(z,name):
    strings=[''.join(s.itertext()) for s in ET.fromstring(z.read('xl/sharedStrings.xml'))]
    rows=[]
    for row in ET.fromstring(z.read(name)).findall('x:sheetData/x:row',NS):
        cells={}
        for c in row:
            v=c.find('x:v',NS);text='' if v is None else v.text or ''
            if c.attrib.get('t')=='s':text=strings[int(text)]
            elif c.attrib.get('t')=='inlineStr':
                inline=c.find('x:is',NS);text='' if inline is None else ''.join(inline.itertext())
            cells[re.match('[A-Z]+',c.attrib['r'])[0]]=text
        rows.append(cells)
    return rows

def audit(handoff):
    handoff=Path(handoff)
    with (handoff/'FILE_SHA256_MANIFEST.tsv').open(encoding='utf8',newline='') as f:
        manifest=list(csv.DictReader(f,delimiter='\t'))
    failures=[]
    for row in manifest:
        p=handoff/row['archive_path']
        if not p.is_file() or p.stat().st_size!=int(row['bytes']) or sha256(p)!=row['sha256']:
            failures.append(row['archive_path'])
    master=next((handoff/'01_확정자료').glob('Bbolprom_Master*.xlsx'))
    baseline_path=handoff/'03_현행코드/Alpha_v0.2/reference/approved_baseline_309.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf8'))
    cards=baseline['cards']
    with zipfile.ZipFile(master) as z:
        sheets=[s.attrib['name'] for s in ET.fromstring(z.read('xl/workbook.xml')).find('x:sheets',NS)]
        rows=sheet_rows(z,'xl/worksheets/sheet1.xml')
        card_rows=[r for r in rows if r.get('A','').isdigit() and 1<=int(r['A'])<=309]
        master_tags=[(int(r['A']),col,t) for r in card_rows for col in 'CDEFGHI' for t in r.get(col,'').splitlines() if t]
    gold_tags={(c['card_id'],t['category_column'],t['tag']) for c in cards for t in c['tags']}
    html_path=next((handoff/'01_확정자료').glob('*.html'))
    html=json.JSONDecoder().raw_decode(html_path.read_text(encoding='utf8').split('const DATA=',1)[1])[0]
    html_text={c['card_id']:c['source_text'] for c in html['cards']}
    html_tags={(r['card_id'],r['category_column'],r['tag']) for r in html['records']}
    invalid_spans=[]
    for c in cards:
        for t in c['tags']:
            for s in t['spans']:
                if c['source_text'][s['start_cp']:s['end_cp']]!=s['evidence']:
                    invalid_spans.append([c['card_id'],t['tag'],s['start_cp'],s['end_cp']])
    reports={}
    for path in sorted((handoff/'04_실제_PT_시험결과').rglob('*.json')):
        report=json.loads(path.read_text(encoding='utf8'))
        per_card=report['per_card']
        reports[path.parent.name]={
            'input_sha256':report['input_hwpx_sha256'],
            'master_sha256':report['baseline_master_sha256'],
            'source_count':report['source_count'],'image_references':report['image_references'],
            'tags':report['tags'],'highlight_spans':report['highlight_spans'],
            'card_aggregates':{
                'false_negative_tags':sum(c['missing_tags'] for c in per_card),
                'false_positive_tags_in_aligned_cards':sum(c['extra_tags'] for c in per_card),
                'missing_image_refs':sum(c['missing_images'] for c in per_card),
                'extra_image_refs_in_aligned_cards':sum(c['extra_images'] for c in per_card),
                'text_relations':dict(Counter(c['text_relation'] for c in per_card))},
            'source':'supplied historical actual PT report; not rerun during this task'}
    prompt_groups={}
    for card in cards:
        prompt_groups.setdefault(hashlib.sha256(card['source_text'].encode('utf8')).hexdigest(),[]).append(card['card_id'])
    result={
        'schema':'bbolprom-handoff-evidence-audit-v1',
        'manifest':{'listed_files':len(manifest),'verified_files':len(manifest)-len(failures),'mismatches':failures},
        'master':{'sha256':sha256(master),'expected_sha256':MASTER_SHA,'hash_matches':sha256(master)==MASTER_SHA,
                  'sheet_count':len(sheets),'sheets':sheets,'cards':len(card_rows),'tag_mappings':len(master_tags),
                  'baseline_tag_set_matches':set(master_tags)==gold_tags},
        'approved_baseline':{'cards':len(cards),'tag_mappings':sum(len(c['tags']) for c in cards),
             'unique_tag_names':len({t['tag'] for c in cards for t in c['tags']}),
             'unique_prompt_sha256':len(prompt_groups),
             'duplicate_prompt_card_groups':[ids for ids in prompt_groups.values() if len(ids)>1],
             'highlight_spans':sum(len(t['spans']) for c in cards for t in c['tags']),
             'empty_evidence_tags':sum(not t['spans'] for c in cards for t in c['tags']),
             'invalid_span_slices':invalid_spans,
             'final_html_prompts_match':all(html_text[c['card_id']]==c['source_text'] for c in cards),
             'final_html_tags_match':html_tags==gold_tags},
        'historical_actual_pt_reports':reports,
        'current_actual_pt_retest':{'status':'not_run','required_sha256':PT_SHA,
             'reason':'605MB original PT.hwpx is absent; supplied simulated HWPX cannot measure actual PT improvement'},
        'live_api_quality':{'status':'not_run','reason':'Mock/schema tests do not measure semantic API accuracy'},
        'independence':'This evaluation module reads gold. Runtime segmentation must never import it.'}
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--handoff',required=True,type=Path)
    p.add_argument('--out',type=Path,default=Path(__file__).with_name('handoff-audit.json'))
    a=p.parse_args();d=audit(a.handoff);a.out.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in d.items() if k not in ('historical_actual_pt_reports','master')},ensure_ascii=False,indent=2))
    raise SystemExit(bool(d['manifest']['mismatches'] or not d['master']['hash_matches'] or not d['master']['baseline_tag_set_matches']))
