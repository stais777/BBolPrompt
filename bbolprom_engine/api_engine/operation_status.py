"""Read-only operation metadata. Never return prompts, quotes, tags, settings or keys."""
import json,re,sqlite3
from ..api_budget import APIBudget
from ..sqlite_utils import ClosingConnection

STATUSES={'ok','partial','api_disabled','api_unavailable','invalid_response','stale_result','stale_reference','provider_error'}
PHASES={'preflight','sent','received','mock'}
REASONS={'stop','length','content_filter','tool_calls','function_call','other'}
CODES={'output_limit','refused','filtered','incomplete_response','http_error','timeout','connection_or_response_error'}

def safe_summary(value):
    if not isinstance(value,dict):return {}
    result={}
    for k,allowed in (('phase',PHASES),('finish_reason',REASONS),('error_code',CODES)):
        v=value.get(k)
        if isinstance(v,str) and v in allowed:result[k]=v
    for k in ('input_tokens','output_tokens','reasoning_tokens','max_output_tokens','http_status'):
        v=value.get(k)
        if type(v) is int and 0<=v<=10**10:result[k]=v
    if type(value.get('refusal')) is bool:result['refusal']=value['refusal']
    return result

def recent(library):
    with library.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='api_runs'").fetchone():return []
        rows=c.execute('SELECT card_id,created,status,mode,audit_json FROM api_runs ORDER BY created DESC LIMIT 20').fetchall()
    result=[];seen=set()
    for row in rows:
        cid=row['card_id']
        if not isinstance(cid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',cid) or cid in seen:continue
        seen.add(cid)
        try:audit=json.loads(row['audit_json'])
        except (ValueError,TypeError):audit={}
        result.append({'card_id':cid,'created':row['created'],'status':row['status'] if row['status'] in STATUSES else 'other',
            'mode':row['mode'] if row['mode'] in ('mock','live','offline') else 'unknown',
            'provider':safe_summary(audit.get('provider_response')) if isinstance(audit,dict) else {}})
    return result

def daily_usage(library):
    p=library.root/'api-safety.sqlite3'
    if not p.is_file():return {'available':False}
    try:
        with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as c:
            r=c.execute('SELECT count(*),coalesce(sum(reserved),0),coalesce(sum(input_tokens),0),coalesce(sum(output_tokens),0) FROM api_reservations WHERE day=?',(APIBudget.day(),)).fetchone()
        return {'available':True,'day_utc':APIBudget.day(),'calls':r[0],'reserved_cost_usd':r[1]/1e9,'input_tokens':r[2],'output_tokens':r[3]}
    except (OSError,sqlite3.Error):return {'available':False}
