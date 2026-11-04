"""Read-only Upstox evidence. No execution imports, order mutations or ledger writes."""
from __future__ import annotations
import json, math, os, re, tempfile
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

MODEL='HILEGA_PRODUCTION_BROKER_OBSERVATION_V1'
PATHS={'profile':'/v2/user/profile','orders':'/v2/order/retrieve-all',
       'trades':'/v2/order/trades/get-trades-for-day','positions':'/v2/portfolio/short-term-positions',
       'funds':'/v3/user/get-funds-and-margin'}
FIELDS={
 'orders':('order_id','instrument_token','product','transaction_type','status','quantity','filled_quantity','pending_quantity','average_price'),
 'trades':('trade_id','order_id','instrument_token','product','transaction_type','quantity','average_price'),
 'positions':('instrument_token','product','quantity','average_price','last_price','realised','unrealised')}
CASH_PATH='data.available_to_trade.cash_available_to_trade.total'

def now():return datetime.now(timezone.utc)
def enabled():return os.getenv('HILEGA_PRODUCTION_BROKER_OBSERVE','0')=='1'
def cache_path():return Path(os.getenv('HILEGA_PRODUCTION_BROKER_SNAPSHOT','data/research/hilega-production-broker-observation/latest.json'))
def number(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('INVALID_NUMBER')
    return v

def integer(v):
    number(v)
    if int(v)!=v:raise ValueError('INVALID_QUANTITY')
    return int(v)

def failure(code,halt=False,provider_code=None):
    return dict(status='FAIL',error=code,halt=halt,provider_code=provider_code)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):return None

class Client:
    def __init__(self,token):
        if not token or '\r' in token or '\n' in token:raise ValueError('BROKER_TOKEN_MISSING_OR_INVALID')
        self.token=token;self.opener=build_opener(NoRedirect())
    def get(self,name):
        if name not in PATHS:raise ValueError('ENDPOINT_NOT_ALLOWED')
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/json',
                 'User-Agent':'RB-ITOS-AI/1.0 (read-only readiness validation)'}
        if name=='funds':headers['Api-Version']='3.0'
        request=Request('https://api.upstox.com'+PATHS[name],headers=headers,method='GET')
        try:
            with self.opener.open(request,timeout=8) as r:raw=r.read(8_000_001)
            if len(raw)>8_000_000:return failure('RESPONSE_TOO_LARGE')
            return json.loads(raw)
        except HTTPError as exc:
            provider=None
            try:
                body=json.loads(exc.read(65536))
                code=body.get('error_code')
                if code==1010:provider='CLOUDFLARE_1010'
                errors=body.get('errors',[])
                if isinstance(errors,list):
                    for e in errors:
                        if not isinstance(e,dict):continue
                        code=e.get('errorCode') or e.get('error_code')
                        if isinstance(code,str) and re.fullmatch(r'UDAPI[0-9]{1,12}',code):provider=code;break
            except (ValueError,TypeError,AttributeError):pass
            # Do not rotate identities, retry permissions failures or persist provider text.
            return failure('HTTP_'+str(exc.code),exc.code in (400,401,403,404,405) or 300<=exc.code<400,provider)
        except (OSError,TimeoutError):return failure('NETWORK_OR_TIMEOUT')
        except (ValueError,UnicodeError):return failure('INVALID_JSON')

def sanitize(raw,name):
    if not isinstance(raw,dict):return failure('INVALID_RESPONSE')
    if raw.get('status')!='success':
        error=raw.get('error','PROVIDER_ERROR')
        allowed={'RESPONSE_TOO_LARGE','NETWORK_OR_TIMEOUT','INVALID_JSON','COLLECTION_FAILED','NOT_REQUESTED_AFTER_ACCESS_BLOCK',
                 'INVALID_RESPONSE','INVALID_PROFILE','FUNDS_SCHEMA_OR_NUMBER_INVALID','INVALID_ROWS','INVALID_REQUIRED_FIELDS'}
        if not (isinstance(error,str) and (error in allowed or re.fullmatch(r'HTTP_[0-9]{3}',error))):error='PROVIDER_ERROR'
        provider=raw.get('provider_code')
        if not isinstance(provider,str) or not re.fullmatch(r'(UDAPI[0-9]{1,12}|CLOUDFLARE_1010)',provider):provider=None
        return failure(error,bool(raw.get('halt')),provider)
    data=raw.get('data')
    if name=='profile':return dict(status='PASS') if isinstance(data,dict) and data else failure('INVALID_PROFILE')
    if name=='funds':
        try:
            a=data['available_to_trade'];cash=number(a['cash_available_to_trade']['total'])
            # The live V3 response may omit the optional net pledge total.
            # Missing pledge is unknown; never zero, derived collateral or cash.
            pledge_bucket=a.get('pledge_available_to_trade')
            if pledge_bucket is not None and not isinstance(pledge_bucket,dict):raise ValueError()
            pledge=(pledge_bucket or {}).get('total')
            if pledge is not None:pledge=number(pledge)
            used=number(a['cash_available_to_trade']['margin_used']['total'])
            preview=(max(Decimal('0'),Decimal(str(cash)))*Decimal('0.50')).quantize(Decimal('0.01'),rounding=ROUND_DOWN)
            return dict(status='PASS',cash_available_to_trade=cash,pledge_available_to_trade=pledge,
                        cash_margin_used=used,half_cash_preview=str(preview),field=CASH_PATH,
                        pledge_status='UNAVAILABLE' if pledge is None else 'AVAILABLE',
                        mapping_status='PENDING_ACCOUNT_COMPARISON',allocation_approved=False)
        except (KeyError,TypeError,ValueError,ArithmeticError):return failure('FUNDS_SCHEMA_OR_NUMBER_INVALID')
    if not isinstance(data,list):return failure('INVALID_ROWS')
    rows=[]
    try:
        for row in data:
            if not isinstance(row,dict):raise ValueError()
            clean={k:row[k] for k in FIELDS[name] if k in row}
            for k,v in clean.items():
                if isinstance(v,(dict,list,bool)) or v is not None and not isinstance(v,(str,int,float)):raise ValueError()
                if isinstance(v,(int,float)):number(v)
                if isinstance(v,str) and len(v)>256:raise ValueError()
            if not isinstance(clean.get('instrument_token'),str) or not clean['instrument_token'] or not isinstance(clean.get('product'),str) or not clean['product']:raise ValueError()
            if name=='positions':integer(clean.get('quantity'))
            else:
                if not isinstance(clean.get('order_id'),str) or not clean['order_id'] or clean.get('transaction_type') not in ('BUY','SELL'):raise ValueError()
                if integer(clean.get('quantity'))<=0:raise ValueError()
                if name=='orders':
                    filled=integer(clean.get('filled_quantity'));pending=integer(clean.get('pending_quantity'))
                    if min(filled,pending)<0 or filled+pending>clean['quantity'] or not isinstance(clean.get('status'),str):raise ValueError()
                elif not isinstance(clean.get('trade_id'),str) or not clean['trade_id']:raise ValueError()
            rows.append(clean)
    except (ValueError,TypeError):return failure('INVALID_REQUIRED_FIELDS')
    return dict(status='PASS',rows=rows)

def fill_diagnostics(checks):
    """Account evidence only; no strategy ownership, no inferred external exit or P&L."""
    if any(checks[n].get('status')!='PASS' for n in ('orders','trades','positions')):
        return dict(status='UNKNOWN',issues=['ORDER_TRADE_OR_POSITION_EVIDENCE_UNAVAILABLE'],ownership='NOT_MAPPED')
    orders={};seen={};totals={};issues=[]
    for o in checks['orders']['rows']:
        if o['order_id'] in orders:issues.append('DUPLICATE_ORDER_ID')
        orders[o['order_id']]=o
    for t in checks['trades']['rows']:
        key=(t['order_id'],t['trade_id'])
        if key in seen:
            issues.append('DUPLICATE_TRADE_ID');continue
        seen[key]=t;order=orders.get(t['order_id'])
        if not order:issues.append('TRADE_WITHOUT_ORDER');continue
        if any(t.get(k)!=order.get(k) for k in ('instrument_token','product','transaction_type')):issues.append('TRADE_ORDER_IDENTITY_MISMATCH');continue
        totals[t['order_id']]=totals.get(t['order_id'],0)+t['quantity']
    for oid,o in orders.items():
        if totals.get(oid,0)!=o['filled_quantity']:issues.append('ORDER_FILL_TOTAL_MISMATCH')
    keys=[(p['instrument_token'],p['product']) for p in checks['positions']['rows']]
    if len(keys)!=len(set(keys)):issues.append('DUPLICATE_POSITION_KEY')
    return dict(status='REVIEW_REQUIRED' if issues else 'CONSISTENT_ACCOUNT_SNAPSHOT',issues=sorted(set(issues)),
                ownership='NOT_MAPPED',position_fill_linkage='NOT_VALIDATED',application_state_updated=False)

def collect(get,at=None):
    start=at or now();checks={};halt=False
    for name in PATHS:
        if halt:checks[name]=failure('NOT_REQUESTED_AFTER_ACCESS_BLOCK',True);continue
        try:checks[name]=sanitize(get(name),name)
        except Exception:checks[name]=failure('COLLECTION_FAILED')
        halt=halt or checks[name].get('halt',False)
    return dict(model=MODEL,generated_at=start.isoformat(),completed_at=(at or now()).isoformat(),
        session_date=start.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat(),evidence_mode='LIVE_READ_ONLY',
        checks=checks,connection_status='PASS' if all(c['status']=='PASS' for c in checks.values()) else 'FAIL',
        halt=halt,diagnostics=fill_diagnostics(checks),snapshot_atomic=False,
        production_execution_enabled=False,orders_sent=False,readiness='NOT_CLEARED_FOR_PRODUCTION')

def write_snapshot(value,path=None):
    path=path or cache_path();path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def display(path=None,at=None):
    base=dict(status='NOT_ENABLED' if not enabled() else 'UNAVAILABLE',broker_connected=False,
              positions=None,orders=None,trades=None,funds=None,checks=[],age_seconds=None,
              production_execution_enabled=False,ownership='NOT_MAPPED',live_pnl=None)
    if not enabled():return base
    try:
        p=path or cache_path()
        if p.stat().st_size>8_000_000:raise ValueError()
        value=json.loads(p.read_text());at=at or now()
        stamp=datetime.fromisoformat(value['generated_at'])
        if stamp.tzinfo is None or value['model']!=MODEL or value['evidence_mode']!='LIVE_READ_ONLY':raise ValueError()
        age=(at-stamp).total_seconds()
        base.update(age_seconds=round(age,1),generated_at=stamp.isoformat())
        if age<0 or age>90 or value['session_date']!=at.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat():
            base['status']='STALE';return base
        checks=value['checks']
        # Revalidate all cached fields; no raw provider bodies are passed to UI.
        safe={}
        for n in PATHS:
            c=checks[n]
            if c['status']=='PASS':
                if n=='profile':safe[n]=dict(status='PASS')
                elif n=='funds':
                    # Store only approved schema fields; monetary preview remains unapproved.
                    cash=number(c['cash_available_to_trade']);pledge=c.get('pledge_available_to_trade');used=number(c['cash_margin_used'])
                    if pledge is not None:pledge=number(pledge)
                    safe[n]=sanitize(dict(status='success',data={'available_to_trade':{
                        'cash_available_to_trade':{'total':cash,'margin_used':{'total':used}},
                        'pledge_available_to_trade':{'total':pledge}}}),n)
                else:safe[n]=sanitize(dict(status='success',data=c['rows']),n)
            else:safe[n]=sanitize(c,n)
        ok=all(c['status']=='PASS' for c in safe.values())
        base.update(status='LIVE_READ_ONLY' if ok else 'ACCESS_BLOCKED' if value.get('halt') else 'ERROR',broker_connected=ok,
            checks=[dict(check=n,status=c['status'],error=c.get('error'),provider_code=c.get('provider_code')) for n,c in safe.items()],
            diagnostics=fill_diagnostics(safe))
        for n in ('positions','orders','trades'):base[n]=safe[n].get('rows') if safe[n]['status']=='PASS' else None
        base['funds']=safe['funds'] if safe['funds']['status']=='PASS' else None
        return base
    except (OSError,ValueError,KeyError,TypeError,OverflowError):
        base['status']='UNAVAILABLE';return base

async def monitor():
    """Opt-in server task, independent of browser. GET-only, halt on access errors."""
    import asyncio
    delay=30
    while True:
        try:
            # Dedicated broker token may be configured without replacing market-data token.
            token=os.getenv('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or os.getenv('UPSTOX_ACCESS_TOKEN','')
            client=Client(token)
            result=await asyncio.to_thread(collect,client.get)
            await asyncio.to_thread(write_snapshot,result)
            if result['halt']:return  # explicit operator restart after credentials/IP correction
            delay=30 if result['connection_status']=='PASS' else min(delay*2,300)
        except Exception:
            value=dict(model=MODEL,generated_at=now().isoformat(),evidence_mode='LIVE_READ_ONLY',
                       session_date=now().astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat(),checks={},halt=True)
            try:await asyncio.to_thread(write_snapshot,value)
            except Exception:pass  # existing cache becomes stale; never treated as current
            return
        await asyncio.sleep(delay)
