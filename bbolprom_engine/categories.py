"""User-owned category policy, kept separate from approved master files."""
from __future__ import annotations
import copy
from datetime import datetime, timezone

class CategoryManager:
    def __init__(self, categories=(), tags=(), history=()):
        self.categories = copy.deepcopy(list(categories))
        self.tags = copy.deepcopy(list(tags))
        self.history = copy.deepcopy(list(history))
        ids=[c['id'] for c in self.categories]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate category IDs')

    def _get(self, ident):
        for category in self.categories:
            if category['id']==ident:return category
        raise ValueError('Unknown category ID')

    def _record(self, operation, ident, before):
        self.history.append({'operation':operation,'category_id':ident,
                             'before':copy.deepcopy(before),
                             'at':datetime.now(timezone.utc).isoformat()})

    def add(self, category, *, user_confirmed=False):
        if not user_confirmed:raise ValueError('User approval of category definition is required')
        if not all(isinstance(category.get(k),str) and category[k].strip() for k in ('id','name','definition')):
            raise ValueError('Category id/name/user-approved definition required')
        if any(x['id']==category['id'] for x in self.categories):raise ValueError('Category ID exists')
        self.categories.append(copy.deepcopy({**category,'enabled':True,'definition_revision':1}))
        self._record('user_add',category['id'],None)

    def rename(self, ident, name):
        if not isinstance(name,str) or not name.strip():raise ValueError('Name required')
        c=self._get(ident);self._record('rename',ident,c);c['name']=name

    def define(self, ident, definition, *, include='', exclude='', user_confirmed=False):
        if not user_confirmed:raise ValueError('User approval required')
        if not isinstance(definition,str) or not definition.strip():raise ValueError('Definition required')
        c=self._get(ident);self._record('definition_for_future_imports',ident,c)
        c.update(definition=definition,include=include,exclude=exclude,
                 definition_revision=c.get('definition_revision',1)+1)
        # Existing card tags and evidence deliberately untouched.

    def deactivate(self, ident):
        c=self._get(ident)
        if not c.get('enabled',True):return
        self._record('deactivate',ident,c);c['enabled']=False
        for tag in self.tags:
            if tag.get('category_id',tag.get('category_column'))==ident:
                tag.setdefault('category_history',[]).append({'category_id':ident,'reason':'category_deactivated'})
                tag['category_id']=None;tag['category_column']=None;tag['category_status']='unclassified'

    def reactivate(self, ident, *, restore_tags=None):
        # Restoration is an unapproved product policy. Require an explicit user
        # choice for each operation instead of silently deciding a default.
        if type(restore_tags) is not bool:raise ValueError('User must choose whether prior tags should be restored')
        c=self._get(ident);self._record('reactivate_user_choice',ident,c)
        self.history[-1]['restore_tags']=restore_tags
        c['enabled']=True
        if restore_tags:
            for tag in self.tags:
                h=tag.get('category_history',[])
                if tag.get('category_id') is None and h and h[-1].get('category_id')==ident:
                    tag['category_id']=ident;tag['category_column']=ident;tag['category_status']='classified'
                    tag['category_history'].append({'category_id':ident,'reason':'explicit_user_restore'})

    def active(self):
        return copy.deepcopy([c for c in self.categories if c.get('enabled',True) and str(c.get('definition','')).strip()])

    def snapshot(self):
        return copy.deepcopy({'categories':self.categories,'tags':self.tags,'history':self.history})
