"""Gold-standard comparator. Separate from the HWPX analysis engine.

No approved labels are passed back to the analyzer. This file may read the
approved 309-card baseline ONLY after analysis.json has been saved.
"""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ZERO_WIDTH = '\u200b\u200c\u200d\u2060\ufeff\u00ad'
REMOVE_SPACE = re.compile(r'[\s' + ZERO_WIDTH + r']+')
EXPECTED_BASE_SHA = 'b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe'


def compact(s):
    return REMOVE_SPACE.sub('', s or '')


def safe_ratio(a, b):
    return round(100*a/b, 2) if b else (100.0 if not a else 0.0)


def key_tags(tags):
    return {(tag['category_column'], tag['tag']) for tag in tags}


def image_refs(card):
    return [im['ref'].lower() for im in card.get('images', [])]


def gold_images(card):
    return re.findall(r'image\d+', str(card.get('image_ref', '')), re.I)


def match_cards(engine_cards, gold_cards):
    """Exact normalized source alignment before conservative containment fallback."""
    available = set(range(len(gold_cards)))
    exact_by_text = defaultdict(list)
    for i, gold in enumerate(gold_cards):
        exact_by_text[compact(gold['source_text'])].append(i)
    mapped = {}
    # Exact normalized match, images break ties for duplicate prompt bodies.
    for pred_i, card in enumerate(engine_cards):
        key = compact(card.get('source_text', ''))
        choices = [gi for gi in exact_by_text.get(key, []) if gi in available]
        if not choices:
            continue
        expected = [x.lower() for x in image_refs(card)]
        chosen = next((gi for gi in choices if [x.lower() for x in gold_images(gold_cards[gi])] == expected), choices[0])
        available.remove(chosen)
        mapped[pred_i] = (chosen, 'exact' if card['source_text'] == gold_cards[chosen]['source_text'] else 'whitespace_equivalent')
    # Partial containment is for diagnostics only: cannot count as correctly reconstructed card.
    for pred_i, card in enumerate(engine_cards):
        if pred_i in mapped:
            continue
        body = compact(card.get('source_text', ''))
        if len(body) < 30:
            continue
        matches = []
        for gi in available:
            ref = compact(gold_cards[gi]['source_text'])
            if len(ref) < 30:
                continue
            small, large = sorted((body, ref), key=len)
            coverage = len(small)/len(large)
            if coverage >= .82 and small in large:
                matches.append((coverage, gi))
        if matches:
            matches.sort(reverse=True)
            if len(matches) == 1 or matches[0][0] > matches[1][0] + .08:
                _, chosen = matches[0]
                mapped[pred_i] = (chosen, 'partial_source')
                available.remove(chosen)
    return mapped


def compare(engine: dict, baseline: dict) -> dict:
    if engine.get('schema') != 'bbolprom-independent-engine-alpha-0.2':
        raise ValueError('독립 엔진 결과 JSON이 아닙니다.')
    if baseline.get('source_master_sha256') != EXPECTED_BASE_SHA:
        raise ValueError('베이스화 마스터 SHA256 식별자가 일치하지 않습니다. 올바른 확정 베이스를 선택하세요.')
    gold_cards = baseline['cards']
    engine_cards = engine['cards']
    matches = match_cards(engine_cards, gold_cards)
    mapped_by_gold = {gi: (pi, relation) for pi, (gi, relation) in matches.items()}
    report_rows = []
    totals = Counter()
    total_gold_refs = 0
    span_comparable = 0
    tag_rows = 0
    span_rows = 0
    for gi, gold in enumerate(gold_cards):
        gold_ref = gold_images(gold)
        gold_tag_set = key_tags(gold['tags'])
        gold_spans = {(t['category_column'], t['tag'], s['start_cp'], s['end_cp'])
                      for t in gold['tags'] for s in t.get('spans', [])}
        total_gold_refs += len(gold_ref)
        tag_rows += len(gold_tag_set)
        span_rows += len(gold_spans)
        if gi not in mapped_by_gold:
            report_rows.append({'card_id': gold['card_id'], 'engine_card': None, 'text_relation': 'unmatched',
                                'expected_images': len(gold_ref), 'correct_images': 0,
                                'missing_images': len(gold_ref), 'extra_images': 0,
                                'expected_tags': len(gold_tag_set), 'correct_tags': 0,
                                'missing_tags': len(gold_tag_set), 'extra_tags': 0,
                                'expected_spans': len(gold_spans), 'correct_spans': None,
                                'missing_examples': sorted(f'{a}:{b}' for a, b in gold_tag_set)[:12],
                                'extra_examples': []})
            totals['unmatched_gold'] += 1
            continue
        pred_i, relation = mapped_by_gold[gi]
        pred = engine_cards[pred_i]
        pred_tags = key_tags(pred['tags'])
        pred_ref = image_refs(pred)
        # Counts, not just sets: the same original image can legitimately be reused.
        common_images = sum((Counter(x.lower() for x in gold_ref) & Counter(pred_ref)).values())
        shared_tags = len(gold_tag_set & pred_tags)
        extras = pred_tags - gold_tag_set
        missing = gold_tag_set - pred_tags
        totals['image_true_positive'] += common_images
        totals['image_false_positive'] += len(pred_ref)-common_images
        totals['tag_true_positive'] += shared_tags
        totals['tag_false_positive'] += len(extras)
        totals['aligned_gold'] += 1
        if relation == 'exact':
            totals['exact_source'] += 1
        elif relation == 'whitespace_equivalent':
            totals['whitespace_equivalent_source'] += 1
        else:
            totals['partial_source'] += 1
        correct_spans = None
        if relation == 'exact':
            spans = {(t['category_column'], t['tag'], s['start_cp'], s['end_cp'])
                     for t in pred['tags'] for s in t.get('spans', [])}
            correct_spans = len(gold_spans & spans)
            span_comparable += len(gold_spans)
            totals['span_true_positive'] += correct_spans
            totals['span_false_positive'] += len(spans-gold_spans)
        report_rows.append({'card_id': gold['card_id'], 'engine_card': pred['engine_card'],
                            'text_relation': relation,
                            'expected_images': len(gold_ref), 'correct_images': common_images,
                            'missing_images': len(gold_ref)-common_images,
                            'extra_images': len(pred_ref)-common_images,
                            'expected_tags': len(gold_tag_set), 'correct_tags': shared_tags,
                            'missing_tags': len(missing), 'extra_tags': len(extras),
                            'expected_spans': len(gold_spans), 'correct_spans': correct_spans,
                            'missing_examples': sorted(f'{a}:{b}' for a, b in missing)[:12],
                            'extra_examples': sorted(f'{a}:{b}' for a, b in extras)[:12]})
    total_pred_refs = sum(len(image_refs(c)) for c in engine_cards)
    total_pred_tags = sum(len(key_tags(c['tags'])) for c in engine_cards)
    total_pred_spans = sum(sum(len(t.get('spans', [])) for t in c['tags']) for c in engine_cards)
    gold_mapped_count = totals['aligned_gold']
    results = {
        'schema': 'bbolprom-engine-comparison-alpha-0.2',
        'baseline_master_sha256': EXPECTED_BASE_SHA,
        'input_hwpx_sha256': engine['file']['sha256'],
        'source_count': {'baseline_cards': len(gold_cards), 'engine_cards': len(engine_cards),
                         'exact_text': totals['exact_source'],
                         'whitespace_equivalent_text': totals['whitespace_equivalent_source'],
                         'partial_text_only': totals['partial_source'],
                         'unmatched_baseline': len(gold_cards)-gold_mapped_count,
                         'unmatched_engine': len(engine_cards)-gold_mapped_count},
        'image_references': {'baseline': total_gold_refs, 'engine': total_pred_refs,
                             'correct_in_aligned_cards': totals['image_true_positive'],
                             'recall_pct': safe_ratio(totals['image_true_positive'], total_gold_refs),
                             'precision_pct': safe_ratio(totals['image_true_positive'], total_pred_refs)},
        'tags': {'baseline': tag_rows, 'engine': total_pred_tags,
                 'correct_in_aligned_cards': totals['tag_true_positive'],
                 'recall_pct': safe_ratio(totals['tag_true_positive'], tag_rows),
                 'precision_pct': safe_ratio(totals['tag_true_positive'], total_pred_tags)},
        'highlight_spans': {'baseline': span_rows, 'engine': total_pred_spans,
                            'comparable_baseline_spans': span_comparable,
                            'correct_spans_when_raw_text_identical': totals['span_true_positive'],
                            'recall_pct_over_all_baseline': safe_ratio(totals['span_true_positive'], span_rows),
                            'note': '원문이 완전히 동일할 때만 좌표 비교. 공백/문단 차이가 있으면 위치 비교를 수행하지 않음.'},
        'per_card': report_rows,
        'limitations': [
            '엔진에는 확정 309개 태그·문구·하이라이팅 정답이 주입되지 않았습니다.',
            '태그는 제한적인 규칙 후보이며 AI 의미 분석 결과가 아닙니다.',
            '원문이 부분 일치인 경우 카드 구분 성공으로 간주하지 않습니다.',
            '실제 PT.hwpx가 아닌 인공 시험 HWPX로 얻은 지표는 본 시험 성능이 아닙니다.',
        ]
    }
    return results


def save_comparison(outdir: Path, report: dict):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir/'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = report['per_card']
    with (outdir/'comparison_cards.csv').open('w', encoding='utf-8-sig', newline='') as fp:
        cols = ['card_id','engine_card','text_relation','expected_images','correct_images',
                'missing_images','extra_images','expected_tags','correct_tags','missing_tags',
                'extra_tags','expected_spans','correct_spans']
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction='ignore');w.writeheader();w.writerows(rows)
    (outdir/'comparison.html').write_text(render_html(report), encoding='utf-8')


def render_html(r: dict) -> str:
    esc = html.escape
    s = r['source_count'];i=r['image_references'];t=r['tags'];h=r['highlight_spans']
    metrics = [
        ('베이스 카드',s['baseline_cards'],'장'),('엔진 카드',s['engine_cards'],'장'),
        ('원문 완전일치',s['exact_text'],'장'),('공백 제외 일치',s['whitespace_equivalent_text'],'장'),
        ('이미지 참조 재현율',f"{i['recall_pct']}%",f"{i['correct_in_aligned_cards']}/{i['baseline']}"),
        ('태그 정확 재현율',f"{t['recall_pct']}%",f"{t['correct_in_aligned_cards']}/{t['baseline']}"),
        ('형광펜 정확 좌표',h['correct_spans_when_raw_text_identical'],f"비교 가능 {h['comparable_baseline_spans']} / 기준 {h['baseline']}"),
    ]
    cards = ''.join(f'<article class="metric"><label>{esc(str(label))}</label><strong>{esc(str(v))}</strong><small>{esc(str(unit))}</small></article>' for label,v,unit in metrics)
    trs=[]
    for a in r['per_card']:
        tag_examples = ', '.join(a['missing_examples'][:5])
        relation=a['text_relation']
        flag = 'ok' if relation=='exact' else ('soft' if relation=='whitespace_equivalent' else 'bad')
        trs.append('<tr>'+
                   f'<td>{a["card_id"]:03d}</td><td>{esc(str(a["engine_card"] or "—"))}</td>'+
                   f'<td class="{flag}">{esc(relation)}</td>'+
                   f'<td>{a["correct_images"]}/{a["expected_images"]}</td>'+
                   f'<td>{a["correct_tags"]}/{a["expected_tags"]}</td>'+
                   f'<td>{esc(str(a["correct_spans"] if a["correct_spans"] is not None else "비교불가"))}</td>'+
                   f'<td title="{esc(tag_examples)}">{esc(tag_examples[:90])}</td>'+
                   '</tr>')
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>뽈프롬 독립 엔진 검증 보고서</title><style>
    :root{font-family:system-ui,'Malgun Gothic',sans-serif;color:#1b2738;background:#f0f3f9}
    body{max-width:1330px;margin:24px auto;padding:0 24px}h1{font-size:26px}h2{font-size:18px}
    .metricgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
    .metric{background:white;border:1px solid #d9e0ea;border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:6px}
    label,small{color:#627187}strong{font-size:27px;color:#15579f}table{width:100%;border-collapse:collapse;background:white}
    th{background:#dce7f4;position:sticky;top:0}td,th{border-bottom:1px solid #e5ebf1;padding:10px;text-align:left;font-size:13px}
    .ok{color:#18784b}.soft{color:#886b17}.bad{color:#c0392b}.note{background:#fff4d8;border:1px solid #e6ca76;padding:14px;border-radius:10px}
    .scroll{max-height:650px;overflow:auto;border-radius:10px;border:1px solid #cbd6e5}
    </style></head><body><h1>뽈프롬 · 독립 엔진 검증 결과</h1><p>기존 309개 베이스화 vs. HWPX를 독립 분석한 엔진 결과</p>
    <div class="metricgrid">'''+cards+'''</div><h2>해석상 주의</h2><div class="note">
    이 결과는 <b>정답이 주입되지 않은 규칙 기반 엔진</b>의 현재 수준입니다. 태그를 의미상 비슷하게 생성했더라도
    카테고리와 이름이 정확히 같아야 재현된 것으로 집계됩니다. 형광펜은 원문이 문자 단위로 완전히 일치하는 카드에서만 좌표를 비교합니다.
    <b>원문 완전일치</b>와 공백 제외 일치/부분 일치를 구분해서 해석하세요.</div>
    <h2>카드별 비교</h2><div class="scroll"><table><thead><tr><th>베이스 카드</th><th>엔진 카드</th>
    <th>원문</th><th>이미지</th><th>태그</th><th>정확 형광펜</th><th>누락 태그 일부</th></tr></thead><tbody>'''+''.join(trs)+'''</tbody></table></div></body></html>'''
