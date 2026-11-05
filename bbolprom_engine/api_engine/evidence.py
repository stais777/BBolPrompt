"""New-card evidence checking; original309 highlighting helpers stay unchanged."""
from ..api import evidence_spans


GUIDANCE=('For repeated evidence provide a LONGER EXACT source quote which uniquely identifies the intended context. '
          'Do not choose an arbitrary repeated occurrence or return offsets. The program rejects ambiguous locations. '
          'User corrections are context examples, not new universal rules. Protected/current-card tags remain user-owned.')


def refine(text,result):
    tags=result.get('tags',[])+result.get('unclassified',[])
    for tag in tags:
        quotes=tag.get('evidence_text',[]);spans=[];ambiguous=False
        # The frozen validator clears ALL highlights when any quote is false.
        # A repeated valid quote must not accidentally restore a partial subset.
        if any(not quote or quote not in text for quote in quotes):continue
        for quote in quotes:
            found=evidence_spans(text,[quote])
            if len(found)==1:spans+=found
            elif len(found)>1:ambiguous=True
        if ambiguous:
            tag['spans']=sorted({(s['start_cp'],s['end_cp']):s for s in spans}.values(),key=lambda s:s['start_cp'])
            tag['evidence_ambiguous']=True
            if not spans:tag.update(category_id=None,category_column=None,category_status='unclassified',reason='반복 근거의 문맥을 특정하지 못해 위치 검토가 필요합니다.')
    result['tags']=[t for t in tags if t.get('category_id') is not None]
    result['unclassified']=[t for t in tags if t.get('category_id') is None]
    if result.get('status') in ('ok','partial'):result['status']='partial' if result['unclassified'] else 'ok'
    return result
