"""Approved-workflow stage: draft master, normalized integrated tag index and audit files.
These are outputs from the independent engine, NOT approved reference data.
"""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict,Counter
import json,csv,html
from .tags import CATEGORIES

def write_json(path, obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def build_index(result):
    index=defaultdict(lambda:{'card_ids':set(),'categories':set(),'mapping_count':0,'span_count':0})
    for card in result['cards']:
        for tag in card['tags']:
            k=(tag['category_column'],tag['tag'])
            v=index[k];v['card_ids'].add(card['engine_card']);v['categories'].add(tag['category_column'])
            v['mapping_count']+=1;v['span_count']+=len(tag['spans'])
    entries=[]
    for (cat,tag),v in sorted(index.items()):
        entries.append({'category_column':cat,'category_name':CATEGORIES[cat],
                        'tag':tag,'card_ids':sorted(v['card_ids']),
                        'card_count':len(v['card_ids']),
                        'mapping_count':v['mapping_count'],
                        'highlight_span_count':v['span_count']})
    return {'schema':'bbolprom-independent-index-alpha-0.2',
            'source_hwpx_sha256':result['file']['sha256'],
            'card_count':len(result['cards']), 'unique_tags':len(entries),'entries':entries}

def export_results(folder,result):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/'engine_result.json',result)
    index=build_index(result)
    write_json(folder/'integrated_tag_index.json',index)
    with (folder/'integrated_tag_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f);wr.writerow(['대분류','열','태그','해당 카드 수','카드 번호','하이라이팅 구간 수'])
        for e in index['entries']:
            wr.writerow([e['category_name'],e['category_column'],e['tag'],e['card_count'],
                         ', '.join(map(str,e['card_ids'])),e['highlight_span_count']])
    with (folder/'draft_master.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f)
        wr.writerow(['엔진카드ID','원문SHA256','이미지참조','원본프롬프트',*CATEGORIES.keys(),
                     '태그후보수','하이라이팅구간수','검토필요수','상태'])
        for card in result['cards']:
            tags=card['tags']
            wr.writerow([card['engine_card'],card['source_text_sha256'],
                         ', '.join(i['ref'] for i in card['images']),card['source_text'],
                         *['\n'.join(t['tag'] for t in tags if t['category_column']==col) for col in CATEGORIES],
                         len(tags),sum(len(t['spans']) for t in tags),
                         len(card['review_candidates']),'엔진 초안 (사용자 미승인)'])
    with (folder/'tag_evidence.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f);wr.writerow(['카드','대분류','태그','시작CP','끝CP','원문근거','검증'])
        for card in result['cards']:
            for t in card['tags']:
                for s in t['spans']:
                    wr.writerow([card['engine_card'],t['category_column'],t['tag'],s['start_cp'],
                                 s['end_cp'],s['evidence'],'원문과 정확 일치'])
    with (folder/'review_candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f);wr.writerow(['엔진카드ID','단계','검토유형','내용'])
        for card in result['cards']:
            for item in card['review_candidates']:
                wr.writerow([card['engine_card'],item.get('stage'),item.get('operation'),
                             json.dumps(item,ensure_ascii=False)])
            for candidate in card['unclassified_tag_candidates']:
                wr.writerow([card['engine_card'],'unclassified','new_tag_or_ambiguous',json.dumps(candidate,ensure_ascii=False)])
            for warning in card['warnings']:wr.writerow([card['engine_card'],'card','warning',warning])
    (folder/'engine_summary.html').write_text(render_summary(result,index),encoding='utf-8')
    return folder

def render_summary(data,index):
    esc=html.escape
    stats=data['result_stats']
    cols=[('카드 추정 수','card_count'),('연결 이미지 참조','image_references_resolved'),
          ('태그 후보','tag_candidates'),('하이라이팅 구간','highlight_spans'),
          ('검토 후보','normalization_review_items')]
    metrics=''.join(f'<section><small>{esc(n)}</small><strong>{stats[k]:,}</strong></section>' for n,k in cols)
    items=[]
    for card in data['cards']:
        preview=esc(card['source_text'][:130]);tags=', '.join(esc(t['tag']) for t in card['tags'][:8])
        items.append(f'<tr><td>{card["engine_card"]:03d}</td><td>{len(card["images"])}</td>'
                     f'<td>{len(card["tags"])}</td><td>{len(card["review_candidates"])+len(card["unclassified_tag_candidates"])}</td>'
                     f'<td>{preview}</td><td>{tags}</td></tr>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>뽈프롬 엔진 초안 검증</title>
<style>body{font-family:system-ui,'Malgun Gothic',sans-serif;background:#eff3f8;color:#1e293b;margin:30px auto;max-width:1500px;padding:0 24px}
header{background:#fff;padding:22px;border:1px solid #dde3ed;border-radius:12px}h1{margin-top:0}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:16px 0}.grid section{background:#fff;border:1px solid #d9e1ec;padding:16px;border-radius:12px;display:flex;flex-direction:column;gap:6px}
small{color:#64748b}strong{font-size:24px;color:#185daa}.warn{border-left:5px solid #dc8a22;padding:12px;background:#fff9eb}
table{border-collapse:collapse;width:100%;background:white;font-size:13px}td,th{padding:10px;border:1px solid #e1e7ef;vertical-align:top}th{background:#e5edf6;position:sticky;top:0}
</style><header><h1>뽈프롬 독립 엔진 · 처리 결과</h1><p>분석 파일: '''+esc(data['file']['name'])+'''</p><p class="warn">본 결과는 엔진이 생성한 <b>초안</b>입니다. 309개 승인 정답을 복사한 결과가 아니며, 원본 품질과 태그 의미 판단 정확도를 보장하지 않습니다.</p></header><div class="grid">'''+metrics+'''</div><h2>카드별 초안</h2><table><thead><tr><th>번호</th><th>이미지</th><th>태그</th><th>검토</th><th>원문 일부</th><th>태그 예시</th></tr></thead><tbody>'''+''.join(items)+'''</tbody></table></html>'''
