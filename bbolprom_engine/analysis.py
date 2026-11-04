"""Independent segmentation and conservative rule-based tag candidates.

No approved PT card texts, identifiers or mappings are used in this module.
The tagger is deliberately a lower-bound prototype, NOT an AI substitute.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from .hwpx import Paragraph, HWPXReader
from .tags import run_tag_pipeline, CATEGORIES
from .knowledge import load_terms


@dataclass
class WorkingCard:
    section_start: int
    paragraphs: list[Paragraph] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        # Image anchors are not empty prompt lines. Do not strip characters
        # inside hp:t: trailing newlines/Unicode whitespace belong to the source.
        texts = [p.text for p in self.paragraphs if p.text or not p.image_refs]
        while texts and texts[0] == '': texts.pop(0)
        while texts and texts[-1] == '': texts.pop()
        return '\n'.join(texts)

    def append(self, p: Paragraph):
        self.paragraphs.append(p)
        self.refs.extend(p.image_refs)


def split_cards(paragraphs: list[Paragraph], mode: str = 'paragraph') -> list[WorkingCard]:
    """Two independent heuristics; no known-card matching is performed.

    paragraph: nonempty text paragraphs form boundaries; images in separate
               paragraphs attach to the preceding card.
    blank:      blank text-only paragraphs separate consecutive text blocks;
               adjacent text paragraphs are kept together.
    """
    if mode == 'structure':
        return split_structural(paragraphs)
    if mode not in {'paragraph', 'blank'}:
        raise ValueError('segmentation mode must be paragraph or blank')
    cards: list[WorkingCard] = []
    current: WorkingCard | None = None
    leading: list[Paragraph] = []
    separated = False
    for para in paragraphs:
        has_text = bool(para.text.strip())
        has_image = bool(para.image_refs)
        if not has_text and not has_image:
            if mode == 'blank' and current:
                separated = True
            # A blank paragraph is kept within the current text block for fidelity,
            # unless it is between cards (in that case it is simply a separator).
            if current and mode == 'blank' and current.paragraphs and current.paragraphs[-1].text.strip():
                current.append(para)
            continue
        if has_text:
            is_new = current is None or mode == 'paragraph' or separated
            if is_new:
                current = WorkingCard(para.section)
                if leading:
                    # Leading unattached images: attach to the first subsequent text block.
                    for item in leading:
                        current.append(item)
                    current.warnings.append('앞쪽 이미지가 다음 텍스트 카드에 임시 연결됨')
                    leading.clear()
                cards.append(current)
            current.append(para)
            separated = False
        elif has_image:
            if current is None:
                leading.append(para)
            else:
                current.append(para)
    if leading:
        orphan = WorkingCard(leading[0].section)
        for item in leading:
            orphan.append(item)
        orphan.warnings.append('텍스트가 없는 이미지 묶음: 카드 경계 수동 확인 필요')
        cards.append(orphan)
    for card in cards:
        if not card.text.strip():
            card.warnings.append('프롬프트 텍스트 없음')
        if not card.refs:
            card.warnings.append('연결 이미지 없음: 정상인 텍스트 전용 카드일 수 있음')
    return cards


def split_structural(paragraphs: list[Paragraph]) -> list[WorkingCard]:
    """Use XML grouping and image/text transitions, with explicit uncertainty.

    HWPX has no general card element. Table rows, explicit page/section breaks,
    blank separators and recurring image runs supply evidence. This cannot
    establish correctness for arbitrary layouts; no known prompt is consulted.
    """
    nonblank = [p for p in paragraphs if p.text.strip() or p.image_refs]
    if not nonblank:
        return []
    has_images = any(p.image_refs for p in nonblank)
    leading_images = bool(nonblank[0].image_refs and not nonblank[0].text.strip())
    # Text-only documents without delimiters are intrinsically ambiguous.
    text_fallback = (not has_images and not any(p.container or p.break_before for p in nonblank)
                     and not any(not p.text.strip() and not p.image_refs for p in paragraphs))
    cards, current = [], None
    separated = False
    previous = None
    for para in paragraphs:
        text, image = bool(para.text.strip()), bool(para.image_refs)
        if not text and not image:
            separated = True
            continue
        same_row = bool(current and para.container and previous and para.container == previous.container)
        row_change = bool(previous and para.container != previous.container and
                          (para.container or previous.container))
        explicit_break = bool(previous and (para.section != previous.section or para.break_before))
        boundary = current is None or explicit_break or row_change
        if current and not boundary and not same_row:
            if separated:
                # Blank image->text spacing belongs to that image's card.
                boundary = bool(current.text.strip()) and (text or (leading_images and image))
            elif text_fallback:
                boundary = True
            elif leading_images:
                boundary = image and bool(current.text.strip())
            else:
                # In text-first layouts, images close a prompt's block. Adjacent
                # textual paragraphs before the images are kept together.
                boundary = text and bool(current.refs)
        if boundary:
            current = WorkingCard(para.section)
            cards.append(current)
        current.append(para)
        previous, separated = para, False
    for card in cards:
        if text_fallback:
            card.warnings.append('텍스트 전용·경계 표식 없음: 문단별 분리는 잠정값입니다. 반입 검토에서 확인하세요.')
        elif any(p.container for p in card.paragraphs):
            card.warnings.append('표 행 구조로 묶음: 한 행에 여러 카드가 있는 배치는 경계 검토가 필요합니다.')
        else:
            card.warnings.append('문서 구조/이미지 전환으로 추정한 카드 경계: 반입 전 확인하세요.')
        if not card.text.strip():
            card.warnings.append('프롬프트 텍스트 없음')
        if not card.refs:
            card.warnings.append('연결 이미지 없음: 정상인 텍스트 전용 카드일 수 있음')
    return cards


def _boundary_score(cards: list[WorkingCard]) -> float:
    """Unsupervised plausibility score; intentionally independent of 309 baseline."""
    if not cards:
        return -float('inf')
    score = 0.0
    for card in cards:
        length = len(card.text.strip())
        if 80 <= length <= 8000:
            score += 2
        elif 35 <= length <= 20000:
            score += 1
        elif length > 20000:
            score -= 4
        else:
            score -= 2
        if card.refs and length:
            score += 0.5
        if not length:
            score -= 3
    return score / max(1, len(cards))


def pick_mode(paragraphs: list[Paragraph]) -> tuple[str, dict]:
    p = split_cards(paragraphs, 'paragraph')
    b = split_cards(paragraphs, 'blank')
    scores = {'paragraph': round(_boundary_score(p), 4), 'blank': round(_boundary_score(b), 4)}
    structural = split_cards(paragraphs, 'structure')
    return 'structure', {'candidate_counts': {'paragraph': len(p), 'blank': len(b), 'structure': len(structural)},
                      'plausibility_scores': scores,
                      'note': '구조 기반 추정입니다. 기준 309개 정답/카드 수/문자열은 사용하지 않았습니다. 반입 검토 필요.'}




def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fp:
        for chunk in iter(lambda: fp.read(4*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def analyze(reader: HWPXReader, segmentation: str='auto', hash_images: bool=True, knowledge_mode:str='generic')->dict:
    """Run the entire source→tag→normalization→evidence→index-ready pipeline.

    No approved baseline file, source prompts, per-card tags or label IDs used.
    """
    standard_terms=load_terms(knowledge_mode)
    paragraphs, meta=reader.read_paragraphs()
    if segmentation=='auto':
        mode,heuristic=pick_mode(paragraphs)
    else:
        mode=segmentation
        heuristic={'note':'사용자가 카드 경계 모드를 지정했습니다.',
                   'candidate_counts':{},'plausibility_scores':{}}
    cards=split_cards(paragraphs,mode)
    hashed={}; unresolved=[]; results=[]; total_refs=0; total_tags=0; total_spans=0; total_review=0
    for idx,card in enumerate(cards,1):
        images=[]
        for ref in card.refs:
            path=reader.resolve_image(ref)
            obj={'ref':ref,'path':path,'resolved':bool(path)}
            if path:
                total_refs+=1
                if hash_images:
                    if path not in hashed:hashed[path]=reader.media_digest(path)
                    obj['digest']=hashed[path]
            else:unresolved.append({'engine_card':idx,'ref':ref})
            images.append(obj)
        text=card.text
        processed=run_tag_pipeline(text,standard_terms)
        results.append({'engine_card':idx,'source_text':text,
                        'source_text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
                        'section_start':card.section_start,
                        'paragraph_ids':[p.index for p in card.paragraphs],
                        'images':images,'tags':processed['tags'],
                        'normalization_audit':processed['audit'],
                        'review_candidates':processed['review'],
                        'unclassified_tag_candidates':processed['unclassified_tag_candidates'],
                        'processing_stats':processed['stats'],
                        'warnings':card.warnings})
        total_tags+=len(processed['tags'])
        total_spans+=processed['stats']['validated_highlight_spans']
        total_review+=processed['stats']['review_items']
    return {
        'schema':'bbolprom-independent-engine-alpha-0.3',
        'engine_source':'HWPX XML + generic rules + optional term-only vocabulary; PER-CARD BASELINE NOT READ',
        'file':{'name':reader.source.name,'bytes':reader.source.stat().st_size,
                'sha256':file_sha256(reader.source)},
        'segmentation_mode':mode,'segmentation_heuristics':heuristic,
        'category_definitions':CATEGORIES,
        'knowledge_mode':knowledge_mode,
        'source_stats':meta,
        'result_stats':{'card_count':len(results),
                        'image_references_resolved':total_refs,
                        'image_references_unresolved':len(unresolved),
                        'distinct_hashed_images':len(hashed),
                        'tag_candidates':total_tags,
                        'highlight_spans':total_spans,
                        'normalization_review_items':total_review,
                        'text_only_cards':sum(not c['images'] for c in results)},
        'unresolved_images':unresolved,'cards':results}
