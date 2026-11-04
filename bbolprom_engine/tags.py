"""Source-driven tag candidate creation, vertical/horizontal normalization and evidence mapping.

This code implements auditable rule-based stages, not a replacement for semantic AI.
No reference card is read. Only GENERIC category/alias policies live here.
"""
from __future__ import annotations
import re
import unicodedata
from collections import defaultdict

CATEGORIES={
 'C':'성적·페티시','D':'성적 행위 상태','E':'의상·착용',
 'F':'장소·배경','G':'상황·관계','H':'자세·구도','I':'소품·기타'}

# (category, standardized tag, accepted textual evidence pattern)
# Search features from all seven classification areas. Unlike final baseline,
# these rules contain NO card number, source text or per-card tag assignments.
PATTERNS=[
 ('C','BDSM',r'\bBDSM\b'),('C','페티시',r'페티시|\bfetish\b'),
 ('C','펨돔',r'펨돔|\bfemdom\b'),('C','페깅',r'페깅|\bpegging\b'),
 ('C','발 페티시',r'발\s*페티시|foot\s*fetish'),
 ('D','성교 준비',r'성교\s*준비|섹스\s*준비|성교를\s*위한\s*자세'),
 ('D','구강성교 준비',r'구강성교\s*준비|입\s*쪽으로\s*유도'),
 ('D','성적 역할극',r'성적\s*역할극'),('D','노출 상태',r'노출\s*상태|노출된'),
 ('E','승무원 제복',r'승무원\s*제복'),('E','제복',r'(?:경찰|군인|간호사)?\s*제복'),
 ('E','하이힐',r'하이힐|high\s*heels?'),('E','mules',r'\bmules?\b|뮬\s*(?:신발)?'),
 ('E','맨발',r'맨발|\bbarefoot\b'),('E','운동화',r'운동화|\bsneakers?\b'),
 ('E','롱부츠',r'롱\s*부츠|knee.high\s*boots?'),('E','부츠',r'부츠|\bboots?\b'),
 ('E','미니스커트',r'미니\s*스커트|미니\s*치마'),('E','스커트',r'스커트|치마'),
 ('E','드레스',r'드레스|\bdress\b'),('E','원피스',r'원피스'),
 ('E','바디수트',r'바디\s*수트|\bbodysuit\b'),('E','비키니',r'비키니|\bbikini\b'),
 ('E','수영복',r'수영복|\bswimsuit\b'),('E','속옷',r'속옷|언더웨어'),
 ('E','브래지어',r'브래지어|\bbra\b'),('E','스타킹',r'스타킹|stockings?'),
 ('E','장갑',r'장갑|gloves?'),('E','스카프',r'스카프|scarf'),
 ('E','모자',r'모자|hat\b'),('E','헬멧',r'헬멧|helmet'),
 ('E','블레이저',r'블레이저|blazer'),('E','넥타이',r'넥타이|necktie'),
 ('E','코르셋',r'코르셋|corset'),('E','레깅스',r'레깅스|leggings?'),
 ('F','항공기 기내',r'항공기\s*기내|비행기\s*기내|기내'),
 ('F','공항',r'공항|airport'),('F','강의실',r'강의실|lecture\s*room|classroom'),
 ('F','교실',r'교실|classroom'),('F','사무실',r'사무실|\boffice\b'),
 ('F','보드룸',r'보드룸|boardroom'),('F','회의실',r'회의실|meeting\s*room'),
 ('F','호텔',r'호텔|hotel'),('F','침실',r'침실|bedroom'),
 ('F','욕실',r'욕실|bathroom'),('F','화장실',r'화장실|restroom|toilet'),
 ('F','주방',r'주방|부엌|kitchen'),('F','거실',r'거실|living\s*room'),
 ('F','복도',r'복도|hallway'),('F','계단',r'계단|staircase'),
 ('F','옥상',r'옥상|rooftop'),('F','거리',r'거리|골목길|\bstreet\b'),
 ('F','지하철',r'지하철|subway'),('F','기차',r'기차|train'),
 ('F','병원',r'병원|hospital'),('F','영화관',r'영화관|cinema'),
 ('F','헬스장',r'헬스장|gym'),('F','체육관',r'체육관'),
 ('F','카페',r'카페|\bcafe\b'),('F','레스토랑',r'레스토랑|restaurant'),
 ('F','스튜디오',r'스튜디오|studio'),('F','해변',r'해변|beach'),
 ('F','수영장',r'수영장|pool'),('F','공원',r'공원|park'),
 ('G','유혹',r'유혹|매혹|seductiv\w*|seduction'),('G','역할극',r'역할극|role\s*play'),
 ('G','관찰자',r'관찰자|observer'),('G','손님',r'손님|고객|guest'),
 ('G','직원',r'직원|employee'),('G','강사',r'강사|instructor'),
 ('G','승무원',r'승무원|flight\s*attendant'),('G','비서',r'비서|secretary'),
 ('G','휴머노이드',r'휴머노이드|humanoid'),('G','안드로이드',r'안드로이드|android'),
 ('G','경호원',r'경호원|bodyguard'),('G','의사',r'의사|doctor'),
 ('G','간호사',r'간호사|nurse'),('G','남성',r'남성|남자|\bman\b'),
 ('G','여성',r'여성|여자|\bwoman\b'),
 ('H','정면 구도',r'정면\s*(?:구도|샷|을\s*향)|front\s*view'),
 ('H','전신 구도',r'전신\s*(?:구도|샷)|full.body\s*shot'),
 ('H','9:16 세로 구도',r'9\s*:\s*16'),('H','16:9 가로 프레임',r'16\s*:\s*9'),
 ('H','클로즈업',r'클로즈\s*업|close[ -]?up'),
 ('H','웨이스트샷',r'웨이스트\s*샷|waist\s*shot'),
 ('H','로우 앵글',r'로우\s*앵글|low\s*angle'),
 ('H','하이 앵글',r'하이\s*앵글|high\s*angle'),
 ('H','측면 구도',r'측면\s*(?:구도|샷)|side\s*view'),
 ('H','카메라 응시',r'카메라를\s*(?:바라|응시)|looking\s*(?:at|into)\s*(?:the\s*)?camera'),
 ('H','앉은 자세',r'앉(?:아|은|아서|아있|아\s*있)|sitting'),
 ('H','서 있는 자세',r'서\s*있(?:는|음)|서있는|standing'),
 ('H','누운 자세',r'누운|누워|lying\s*down'),
 ('H','엎드린 자세',r'엎드린|엎드려'),('H','쪼그려 앉음',r'쪼그려\s*앉|squat\w*'),
 ('H','다리 교차',r'다리\s*(?:꼬|교차)|crossed\s*legs?'),
 ('H','양손 들기',r'양손\s*(?:들|올리)|raise\s*both\s*hands'),
 ('H','뒤돌아봄',r'뒤돌아(?:봄|보|봄)|look\s*back'),
 ('H','2인 구성',r'\b2인\s*구성\b|두\s*명의\s*(?:인물|사람)'),
 ('H','3인 구성',r'\b3인\s*구성\b|세\s*명의\s*(?:인물|사람)'),
 ('I','의자',r'의자|chair'),('I','테이블',r'테이블|table'),
 ('I','데스크',r'데스크|desk'),('I','소파',r'소파|sofa'),
 ('I','거울',r'거울|mirror'),('I','유리문',r'유리문|glass\s*door'),
 ('I','침대',r'침대|bed\b'),('I','스마트폰',r'스마트폰|휴대폰|smartphone'),
 ('I','노트북',r'노트북|laptop'),('I','모니터',r'모니터|monitor'),
 ('I','CCTV',r'\bCCTV\b'),('I','카메라',r'카메라|camera'),
 ('I','가면',r'가면|mask'),('I','안경',r'안경|glasses'),
 ('I','선글라스',r'선글라스|sunglasses'),('I','귀걸이',r'귀걸이|earrings?'),
 ('I','목걸이',r'목걸이|necklace'),('I','반지',r'반지|ring'),
 ('I','가방',r'가방|bag\b'),('I','조명',r'조명|lighting'),
 ('I','네온등',r'네온등|neon\s*light'),('I','스포트라이트',r'스포트라이트|spotlight'),
 ('I','마이크',r'마이크|microphone'),('I','책',r'책|book'),
 ('I','컵',r'컵|cup'),('I','펜',r'펜|\bpen\b'),
]

# The approved distinct concepts listed here are global normalization policies,
# not per-card answers. Bare names are not assumed to be textual evidence.
ALIASES={
 '뮬 신발':'mules','뮬 신발 착용':'mules','뮬':'mules',
 '자연스러운 C컬 단발':'C컬 단발',
 '유리문 그림자/반사':'유리문',
}
PREFERRED_COLUMN={
 '펨돔':'C','페깅':'C','strap-on':'C','스포트라이트':'F',
 '유리문':'I','mules':'E','승무원 제복':'E',
}
NEGATIVE_PREFIX=re.compile(r'(?:없음|금지|제외|없이|\bno\s+|\bwithout\s+)$', re.I)
COMPILED=[(cat,name,re.compile(rx,re.I)) for cat,name,rx in PATTERNS]

def canonical(tag: str)->str:
    name=unicodedata.normalize('NFKC',tag or '').strip()
    name=re.sub(r'\s+',' ',name)
    return ALIASES.get(name,name)

def _candidate(cat,name, match, text, source):
    a,b=match.span()
    return dict(category_column=cat,tag=canonical(name),status='candidate',
                method=source, confidence='rule',
                spans=[{'start_cp':a,'end_cp':b,'evidence':text[a:b]}],notes=[])

def extract_candidates(text: str, standard_terms=None)->list[dict]:
    """Stage 1: literal evidence detection; no inferred/highlight fabrication."""
    out=[]
    for cat,name,rx in COMPILED:
        for m in rx.finditer(text):
            prefix=text[max(0,m.start()-16):m.start()]
            if NEGATIVE_PREFIX.search(prefix):
                continue
            out.append(_candidate(cat,name,m,text,'rule'))
    if standard_terms:
        from .knowledge import TermScanner
        for it,a,b in TermScanner(standard_terms).find(text):
            context=text[max(0,a-16):a]
            if NEGATIVE_PREFIX.search(context):continue
            out.append({'category_column':it['category_column'],'tag':canonical(it['tag']),
                'status':'candidate','method':'standard_vocabulary_literal',
                'confidence':'lexical','notes':[],
                'spans':[{'start_cp':a,'end_cp':b,'evidence':text[a:b]}]})
    return out

def vertical_normalize(candidates:list[dict])->tuple[list[dict],list[dict]]:
    """Stage 2: within-column representative terminology and duplicate collapse."""
    by={};audit=[]
    for candidate in candidates:
        c=dict(candidate)
        c['tag']=canonical(c['tag'])
        key=(c['category_column'],c['tag'].casefold())
        if key in by:
            old=by[key]
            seen={(s['start_cp'],s['end_cp']) for s in old['spans']}
            old['spans'] += [s for s in c['spans'] if (s['start_cp'],s['end_cp']) not in seen]
            audit.append({'stage':'vertical','operation':'merge_same_category','column':key[0],'tag':old['tag']})
        else:
            by[key]=c
    return list(by.values()),audit

def _remove_nested_evidence_same_category(tags:list[dict])->tuple[list[dict],list[dict]]:
    """Specific compound tag wins when generic term is ONLY a slice of it.

    If the generic feature also occurs elsewhere independently it is retained.
    """
    gone=set();audit=[]
    for i,a in enumerate(tags):
        for j,b in enumerate(tags):
            if i==j or i in gone or j in gone:continue
            if a['category_column']!=b['category_column']:continue
            if not (len(a['tag'])<len(b['tag']) and a['tag'].casefold() in b['tag'].casefold()):continue
            if not a['spans'] or not b['spans']:continue
            all_contained=all(any(v['start_cp']<=x['start_cp'] and x['end_cp']<=v['end_cp']
                              for v in b['spans']) for x in a['spans'])
            if all_contained:
                gone.add(i)
                audit.append({'stage':'vertical','operation':'remove_nested_evidence',
                              'dropped':a['tag'],'kept':b['tag'],'column':a['category_column']})
    return [t for i,t in enumerate(tags) if i not in gone],audit

def horizontal_normalize(tags:list[dict])->tuple[list[dict],list[dict]]:
    """Stage 3: only approved unambiguous cross-column preferences are automatic.

    Other ambiguous multi-column occurrences are PARKED in a review record,
    rather than placed in two categories at once or deleted without trace.
    """
    by=defaultdict(list)
    for tag in tags: by[tag['tag'].casefold()].append(tag)
    out=[];audit=[]
    for name, group in by.items():
        if len(group)==1:
            out.extend(group);continue
        cols={x['category_column'] for x in group}
        if len(cols)==1:
            out.extend(group);continue
        preference=PREFERRED_COLUMN.get(group[0]['tag'])
        keep=next((x for x in group if x['category_column']==preference), None)
        if keep is None:
            audit.append({'stage':'horizontal','operation':'review_cross_category',
                          'tag':group[0]['tag'],'columns':sorted(cols),
                          'candidate_tags':group,'reason':'같은 대표어의 복수 대분류: 자동 확정 보류'})
            continue
        for tag in group:
            if tag is keep:continue
            had={(s['start_cp'],s['end_cp']) for s in keep['spans']}
            keep['spans'] += [s for s in tag['spans'] if (s['start_cp'],s['end_cp']) not in had]
            audit.append({'stage':'horizontal','operation':'move_and_merge','tag':keep['tag'],
                          'from':tag['category_column'],'to':keep['category_column']})
        out.append(keep)
    return out,audit

def validate_spans(text:str,tags:list[dict])->tuple[list[dict],list[dict]]:
    """Stage 4: exact codepoint slice validation and deterministic ordering."""
    failures=[]
    for tag in tags:
        spans=[]; seen=set()
        for span in tag.get('spans',[]):
            a,b=span['start_cp'],span['end_cp']
            if not isinstance(a,int) or not isinstance(b,int) or not (0<=a<b<=len(text)) or text[a:b]!=span['evidence']:
                failures.append({'tag':tag['tag'],'category':tag['category_column'],'span':span})
                continue
            if (a,b) not in seen:
                spans.append(span);seen.add((a,b))
        tag['spans']=sorted(spans,key=lambda s:(s['start_cp'],s['end_cp']))
    return tags,failures

def overlaps_for_review(tags:list[dict])->list[dict]:
    """Stage 5: candidate pairs that might need user/AI semantic refinement."""
    out=[]
    bycol=defaultdict(list)
    for tag in tags:bycol[tag['category_column']].append(tag)
    for col,arr in bycol.items():
        for i,a in enumerate(arr):
            for b in arr[i+1:]:
                x,y=a['tag'],b['tag']
                if x in y or y in x:
                    if len(x)>2 and len(y)>2:
                        out.append({'stage':'similarity','operation':'review_nested_terms',
                                    'column':col,'tags':[x,y]})
    return out[:120]

def run_tag_pipeline(text:str,standard_terms=None)->dict:
    initial=extract_candidates(text,standard_terms)
    vertical,vlog=vertical_normalize(initial)
    vertical,nestedlog=_remove_nested_evidence_same_category(vertical)
    vlog+=nestedlog
    horizontal,hlog=horizontal_normalize(vertical)
    tags,broken=validate_spans(text,horizontal)
    tags.sort(key=lambda t:(t['category_column'],t['spans'][0]['start_cp'] if t['spans'] else 10**12,t['tag']))
    audit=[{'stage':'candidate_generation','operation':'detected','count':len(initial)}]+vlog+hlog+overlaps_for_review(tags)
    review=[x for x in audit if x['operation'].startswith('review_')]
    novel=discover_new_phrases(text,tags)
    for item in hlog:
        if item.get('operation')=='review_cross_category':
            novel.append({'tag':item['tag'],'suggested_columns':item['columns'],
                'status':'unclassified_review','reason':item['reason'],
                'spans':[s for t in item['candidate_tags'] for s in t['spans']]})
    if broken: review.append({'stage':'highlight','operation':'invalid_evidence','items':broken})
    return {'tags':tags,'audit':audit,'review':review,
            'unclassified_tag_candidates':novel,'stats':{
        'raw_candidates':len(initial),'vertically_normalized':len(vertical),
        'horizontally_normalized':len(tags),
        'validated_highlight_spans':sum(len(t['spans']) for t in tags),
        'review_items':len(review)+len(novel), 'unclassified_candidates':len(novel)}}

# New terms are never silently assigned to an arbitrary category. This
# discoverer proposes explicit short noun-phrases for later review.
NOVEL_HEADS={
 'E':['제복','유니폼','드레스','부츠','상의','하의','모자','헬멧','가운','슈트','재킷'],
 'F':['실내','실외','보드룸','회의실','부스','텐트','공항','대합실','스튜디오','건물','숍'],
 'H':['구도','앵글','샷','시점','프레임','자세','착석','응시'],
 'I':['가방','테이블','의자','거울','문','조명','모니터','카메라','책상','헤드셋'],
}

def discover_new_phrases(text:str,known_tags:list[dict])->list[dict]:
    suggestions=[];seen=set(t['tag'] for t in known_tags)
    for m in re.finditer(r'[^,，;；\n]{2,80}',text):
        clause=m.group().strip()
        if not (3<=len(clause)<=55):continue
        if re.search(r'(?:한다|한다\.|됩니다|되어|도록|한다면|않|금지|없음|제외|하지\s*말)',clause):continue
        clean=re.sub(r'^(?:\d+[.)]\s*|\([^)]+\)\s*)','',clause).strip(' .:!"\'')
        clean=re.sub(r'^(?:a|an|the)\s+','',clean,flags=re.I)
        if not 3<=len(clean)<=32 or clean in seen:continue
        types=[c for c,heads in NOVEL_HEADS.items() if any(head in clean for head in heads)]
        if not types:continue
        a=text.find(clean,m.start(),m.end())
        if a<0:continue
        suggestions.append({'tag':clean,'suggested_columns':types,
            'status':'unclassified_review','reason':'새로운 복합 표현: 의미·중복 판단 미실시',
            'spans':[{'start_cp':a,'end_cp':a+len(clean),'evidence':text[a:a+len(clean)]}]})
        seen.add(clean)
        if len(suggestions)>=36:break
    return suggestions
