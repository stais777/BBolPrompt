"""Local bilingual evidence index and bounded, retractable correction examples."""
import copy,json,math,re,hashlib
from ..approved_context import _features
from .common import digest,name


def index(snapshot):
    rows={}
    for card in snapshot['cards']:
        for tag in card['tags']:
            label=name(tag);category=tag.get('category_column')
            if category is None:continue
            ident='std-'+hashlib.sha256((category+'\0'+label).encode()).hexdigest()[:16]
            item=rows.setdefault(ident,{'id':ident,'name':label,'category_id':category,'features':set(),'sources':set()})
            item['features'].update(_features(label));item['sources'].add((card['card_id'],card.get('user_tag_revision',0)))
            for span in tag.get('spans',[]):
                quote=span['evidence'].casefold()
                item['features'].update(re.findall(r'[a-z][a-z0-9_-]{2,}',quote))
                if re.search('[가-힣]',quote):item['features'].update(_features(quote[:512]))
    # A child label's English evidence can retrieve its approved parent label
    # (e.g. subway-station wall -> subway station). This only ranks references;
    # it never assigns that tag to a new card.
    labels={(x['category_id'],x['name']):x for x in rows.values()}
    for item in list(rows.values()):
        for at,char in enumerate(item['name']):
            if char!=' ':continue
            parent=labels.get((item['category_id'],item['name'][:at]))
            if parent:parent['features'].update(item['features']);parent['sources'].update(item['sources'])
    return rows


def standards(text,rows,limit=100):
    query=set(re.findall(r'[a-z][a-z0-9_-]{2,}',text.casefold()))
    if re.search('[가-힣]',text):query.update(_features(text))
    query-=set('the and with for from that this are was were into'.split())
    frequencies={f:sum(f in item['features'] for item in rows.values()) for f in query};scored=[]
    for item in rows.values():
        overlap=query & item['features']
        if overlap:scored.append((sum(math.log(1+len(rows)/(1+frequencies[f])) for f in overlap)/math.sqrt(max(1,len(item['features']))),item['id'],item))
    return [{k:r[k] for k in ('id','name','category_id')} for _,_,r in sorted(scored,key=lambda x:(-x[0],x[1]))[:limit]]


def corrections(text,repo,cid,*,enabled=False):
    if not enabled:return []
    query=_features(text);ranked=[]
    for correction in repo.corrections():
        if not correction['active'] or correction['card_id']==cid:continue
        with repo.connect(readonly=True) as c:source=c.execute('SELECT text FROM cards WHERE id=?',(correction['card_id'],)).fetchone()['text']
        features=_features(source);score=len(query & features)/math.sqrt(max(1,len(features)))
        if score:ranked.append((score,correction,source))
    result=[];remaining=8000
    for _,item,source in sorted(ranked,key=lambda x:-x[0]):
        if len(result)>=3:break
        anchors=[s['start_cp'] for t in item['tags'] for s in t.get('spans',[])];start=max(0,(anchors[0] if anchors else 0)-200)
        excerpt=source[start:start+2000];tags=[]
        for t in item['tags'][:12]:
            spans=[dict(s,start_cp=s['start_cp']-start,end_cp=s['end_cp']-start) for s in t.get('spans',[]) if start<=s['start_cp']<s['end_cp']<=start+len(excerpt)]
            if t.get('spans') and not spans:continue
            tags.append({'name':name(t),'category_id':t.get('category_id',t.get('category_column')),'spans':spans})
        row={'correction_id':item['id'],'source_card_id':item['card_id'],'source_sha256':item['source_sha'],
            'revision':item['revision'],'source_excerpt':excerpt,'excerpt_start_cp':start,'tags':tags,
            'excluded_tags':[name(t) for t in item['removed'][:30]],'scope':'contextual user correction, not a universal rule'}
        size=len(json.dumps(row,ensure_ascii=False))
        if size>remaining:continue
        result.append(row);remaining-=size
    return result
