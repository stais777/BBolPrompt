"""Persist view preferences separately from approved data and operational cards."""
import copy

DEFAULTS={'theme':'workstation','tone':'preset','view':'basic','inspector_width':385,
          'hidden_cards':[],'order':[],'pinned_tags':{},'selected_tags':[],
          'applied_tags':[],'filter_active':False,'show_hidden':False,'sort':'source'}

def preferences(library):
    return dict(copy.deepcopy(DEFAULTS),**library.get_setting('ui',{}))

def save_preferences(library,patch):
    if not isinstance(patch,dict) or set(patch)-set(DEFAULTS):raise ValueError('지원하지 않는 UI 설정')
    choices={'theme':{'workstation','vision','cloud','carbon','illustrated'},
             'tone':{'preset','blue','mint','violet'},'view':{'grid','basic','large','detail'},
             'sort':{'source','user','title'}}
    for key,values in choices.items():
        if key in patch and (not isinstance(patch[key],str) or patch[key] not in values):raise ValueError('지원하지 않는 화면 설정: '+key)
    for key in ('filter_active','show_hidden'):
        if key in patch and type(patch[key]) is not bool:raise ValueError('잘못된 UI 상태')
    if 'inspector_width' in patch and (type(patch['inspector_width']) is not int or not 290<=patch['inspector_width']<=720):
        raise ValueError('인스펙터 너비 범위:290~720')
    def strings(value):
        return isinstance(value,list) and len(value)<=10000 and all(isinstance(x,str) and 0<len(x)<=512 for x in value) and len(set(value))==len(value)
    for key in ('hidden_cards','order','selected_tags','applied_tags'):
        if key in patch and not strings(patch[key]):raise ValueError('잘못된 UI 목록: '+key)
    if 'pinned_tags' in patch:
        pins=patch['pinned_tags']
        if not isinstance(pins,dict) or len(pins)>10000 or any(not isinstance(k,str) or len(k)>128 or not strings(v) for k,v in pins.items()):
            raise ValueError('잘못된 대표 태그 설정')
    value=dict(preferences(library),**patch)
    library.set_setting('ui',value)
    return value
