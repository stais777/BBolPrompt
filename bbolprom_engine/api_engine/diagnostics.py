"""Aggregate support evidence only: no prompts, tag names, quotes or keys."""
import hashlib,json
from .operation_status import recent,daily_usage


def collect(library):
    with library.connect() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='api_runs'").fetchone()
        if not exists:return {'initialized':False,'version':'api-engine-1','daily_usage':daily_usage(library)}
        tables=('api_runs','api_tag_editions','api_user_corrections','api_correction_events','api_category_definitions')
        counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}
        sha=hashlib.sha256()
        for table in tables:
            sha.update(table.encode())
            for row in c.execute('SELECT * FROM '+table+' ORDER BY 1,2'):
                sha.update(json.dumps(list(row),ensure_ascii=False,separators=(',',':')).encode('utf8'))
        allowed={'ok','partial','api_disabled','api_unavailable','invalid_response','stale_result','stale_reference','provider_error'}
        statuses={}
        for status,count in c.execute('SELECT status,count(*) FROM api_runs GROUP BY status'):
            safe=status if status in allowed else 'other';statuses[safe]=statuses.get(safe,0)+count
    return {'initialized':True,'version':'api-engine-1','counts':counts,'status_counts':statuses,'ledger_sha256':sha.hexdigest(),
        'recent':recent(library),'daily_usage':daily_usage(library)}
