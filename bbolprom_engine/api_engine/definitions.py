"""Editable drafts; never treated as approved until the user confirms them."""
import json
from ..library import _now
from .common import digest,encoded

DRAFTS={
 'C':('원문에 명시된 성적 선호·페티시·주제의 검색 개념.','명시된 선호와 주제','실제 수행 상태는 D, 의상은 E, 관계는 G와 구분한다.'),
 'D':('성적 행위의 실제 수행·준비·암시·부정 등 원문에 명시된 상태를 구분한다.','주체·대상·시점·수행 여부가 확인되는 상태','준비나 자세만으로 실제 수행을 추정하지 않는다.'),
 'E':('등장인물이 입거나 착용한 의류·신발·장신구와 착용 상태.','명시된 착용물과 복장','복장만으로 직업·역할을 확정하지 않는다. 손에 든 물건은 문맥상 I와 구분한다.'),
 'F':('장면이 위치한 장소·공간과 원문에서 식별되는 배경.','실내외 공간·시설·장소','휴대 물건은 I, 인물의 역할·관계는 G와 구분한다.'),
 'G':('등장인물의 역할·상황·상호 관계와 장면의 맥락.','원문에 명시된 역할·관계·상황','복장만으로 역할을 단정하거나 부정·가정을 실제 사건으로 확정하지 않는다.'),
 'H':('인물의 자세·방향 및 카메라 시점·거리·프레이밍.','명시된 자세·구도·촬영 시점','자세만으로 행위 수행을 추정하지 않는다. 장소는 F와 구분한다.'),
 'I':('장면의 소품·도구와 다른 분류에 명확히 속하지 않는 유용한 독립 검색 개념.','명시된 물건·도구·기타 독립 개념','모든 수식어를 태그로 만들거나 애매한 개념을 무조건 이 분류로 확정하지 않는다.')}


def view(repo,categories):
    with repo.connect(readonly=True) as c:
        rows={r['category_id']:r for r in c.execute('''SELECT x.* FROM api_category_definitions x
            WHERE revision=(SELECT max(revision) FROM api_category_definitions y WHERE y.category_id=x.category_id)''')}
    output=[]
    for cat in categories:
        item=dict(cat);saved=rows.get(cat['id'])
        if saved and saved['base_sha']==digest(cat):
            item.update(json.loads(saved['definition_json']),definition_revision=saved['revision'],definition_approved=True)
        elif cat.get('definition','').strip():item['definition_approved']=True
        else:
            definition,include,exclude=DRAFTS.get(cat['id'],('','',''))
            item.update(definition=definition,include=include,exclude=exclude,definition_approved=False)
        output.append(item)
    return {'definitions':output,'token':digest([categories,[dict(rows[k]) for k in sorted(rows)]])}


def effective(repo,categories):
    return [c for c in view(repo,categories)['definitions'] if c['definition_approved']]


def approve(repo,categories,items,expected_token):
    if not isinstance(items,list) or not items or len(items)>100:raise ValueError('확정할 분류 정의를 확인하세요.')
    with repo.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if view(repo,categories)['token']!=expected_token:raise ValueError('분류가 변경됐습니다. 다시 열어 확인하세요.')
        known={x['id']:x for x in categories};seen=set()
        for item in items:
            if not isinstance(item,dict) or set(item)!={'id','definition','include','exclude'}:raise ValueError('분류 정의 필드를 확인하세요.')
            cid=item['id']
            if cid not in known or cid in seen:raise ValueError('기존 분류만 한 번씩 확정할 수 있습니다.')
            seen.add(cid)
            if any(not isinstance(item[k],str) or len(item[k])>10000 for k in ('definition','include','exclude')) or not item['definition'].strip():raise ValueError('분류 정의가 비어 있거나 너무 깁니다.')
            rev=c.execute('SELECT coalesce(max(revision),0)+1 FROM api_category_definitions WHERE category_id=?',(cid,)).fetchone()[0]
            c.execute('INSERT INTO api_category_definitions VALUES(?,?,?,?,?)',(cid,rev,_now(),digest(known[cid]),encoded({k:item[k] for k in ('definition','include','exclude')})))
