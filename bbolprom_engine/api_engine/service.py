"""Separate new-card orchestration, reusing the frozen secure provider adapter."""
import copy,json
from .. import api as legacy
from .. import approved_context
from ..approved_examples import retrieve_approved_examples
from ..approval_history import load_approval_history
from ..method_guidance import load_method_guidance
from . import ENGINE_VERSION,definitions,reference_reader,retrieval,evidence,quality
from .common import digest
from .repository import Repository
from .operation_status import safe_summary


class Engine:
    def __init__(self,db,records=None):
        self.records=copy.deepcopy(records) if records is not None else None
        self.repo=Repository(db,self.records);self._index=None;self._index_token=None

    def definition_view(self,categories):return definitions.view(self.repo,categories)

    def analyze(self,cid,categories,*,config=None,use_examples=False,use_corrections=False,transport=None,review_focus=''):
        review_focus=quality.validate_focus(review_focus)
        s=self.repo.snapshot(cid);refs=reference_reader.read(self.repo.db,self.records)
        effective=definitions.effective(self.repo,categories)
        if self._index_token!=refs['fingerprint']:
            self._index=retrieval.index(refs);self._index_token=refs['fingerprint']
        related=retrieval.standards(s['text'],self._index)
        context=approved_context.load_approved_context()
        current_names={(x['name'],x['category_id']) for x in self._index.values()}
        context=dict(context,standards=[x for x in context['standards'] if (x['name'],x['category_id']) in current_names])
        # Only approved/current manually edited standards, never automatic tags
        # from other operational cards promoted to an approved common vocabulary.
        current={x['id']:x for x in related}
        for item in self._index.values():
            current.setdefault(item['id'],{k:item[k] for k in ('id','name','category_id')})
        examples=retrieve_approved_examples(s['text'],enabled=use_examples,catalog=reference_reader.catalog(refs) if use_examples else None)
        correction_examples=retrieval.corrections(s['text'],self.repo,cid,enabled=use_corrections)
        def focus_token():
            with self.repo.connect(readonly=True) as c:
                row=c.execute("SELECT value FROM settings WHERE key='api'").fetchone()
            return digest(json.loads(row['value']).get('review_focus','') if row else '')
        initial_focus_token=focus_token()
        definition_token=self.definition_view(categories)['token'];captured={};usage={};proposals={}
        def provider(request):
            nonlocal usage,proposals
            supplied={t['id']:t for t in quality.identity_hints(s['text'],self._index)}
            for item in related+request['existing_tags']:supplied.setdefault(item['id'],item)
            request['existing_tags']=list(supplied.values())[:100]
            request['new_card_engine']={'version':ENGINE_VERSION,'guidance':evidence.GUIDANCE,
                'protected_tags':[{'name':t.get('tag',t.get('name')),'category_id':t.get('category_id',t.get('category_column')),'spans':t.get('spans',[])} for t in s['protected']],
                'excluded_tags':s['excluded'],'related_user_corrections':correction_examples}
            request['new_card_engine']['review']=quality.request_guidance(s['text'],self._index,review_focus)
            captured.update(request)
            if transport:content=transport(copy.deepcopy(request))
            else:content,usage=legacy._live_transport(request,config or legacy.APIConfig())
            content,proposals=quality.prepare_response(content,request,self._index)
            return content
        # Legacy helpers used by baseline manual editing remain byte-identical.
        try:
            result=legacy.analyze_card(cid,s['text'],effective,list(current.values()),context,
                transport=provider if transport or (config and config.enabled) else None,config=config,examples=examples,
                approval_history=load_approval_history(),method_guidance=load_method_guidance(),edited_card_ids=refs['edited_card_ids'])
        except Exception:
            result={'card_ref':cid,'source_text':s['text'],'status':'provider_error','tags':[],'unclassified':[],
                'warnings':['API 처리 중 오류가 발생했습니다. 이전 태그를 유지하며 재시도는 수동입니다.']}
        result['mode']='mock' if transport else 'live' if config and config.enabled else 'offline'
        result['usage']=usage
        result['provider_response']=safe_summary({'phase':'mock'} if transport else getattr(config,'_response_meta',{}))
        if result['status'] in ('ok','partial'):
            result=evidence.refine(s['text'],result,quality.source_sections(s['text']))
            result=quality.finish(s['text'],result,proposals,self._index,s['protected'],s['excluded'])
        def references_current():
            # Called AFTER BEGIN IMMEDIATE: no other writer can change these
            # references between validation and saving the new-card tags.
            if reference_reader.read(self.repo.db,self.records)['fingerprint']!=refs['fingerprint']:return False
            if focus_token()!=initial_focus_token:return False
            if correction_examples:
                current_corrections={x['id'] for x in self.repo.corrections() if x['active']}
                if any(x['correction_id'] not in current_corrections for x in correction_examples):return False
            with self.repo.connect(readonly=True) as c:
                raw=c.execute("SELECT value FROM settings WHERE key='categories'").fetchone()
            return self.definition_view(json.loads(raw['value']) if raw else categories)['token']==definition_token
        audit={'engine_version':ENGINE_VERSION,'source_sha256':s['sha'],'card_revision':s['revision'],'reference_fingerprint':refs['fingerprint'],'definition_token':definition_token,
            'quality_version':quality.VERSION,'review_focus_sha256':digest(review_focus),
            'quality_review':result.get('quality_audit',{}),
            'standard_ids':[t['id'] for t in related],'correction_ids':[x['correction_id'] for x in correction_examples],
            'bilingual_sources':{t['id']:sorted(self._index[t['id']]['sources']) for t in related},
            'request_sha256':digest(captured) if captured else None,'provider_response':result['provider_response']}
        result=self.repo.finish(s,result,audit,guard=references_current)
        result['engine_version']=ENGINE_VERSION
        return result
