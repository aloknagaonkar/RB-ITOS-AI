"""Standalone read-only broker evidence collector. Never imports strategy/executor."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

PATHS = {'profile':'/v2/user/profile', 'orders':'/v2/order/retrieve-all',
         'trades':'/v2/order/trades/get-trades-for-day',
         'positions':'/v2/portfolio/short-term-positions'}
FIELDS = {
 'orders': ('order_id','instrument_token','product','transaction_type','status','quantity','filled_quantity','pending_quantity','average_price','order_timestamp','exchange_timestamp'),
 'trades': ('trade_id','order_id','instrument_token','product','transaction_type','quantity','average_price','exchange_timestamp'),
 'positions': ('instrument_token','product','quantity','average_price','last_price','realised','unrealised')}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class ReadOnlyClient:
    def __init__(self, token):
        if not token or '\n' in token or '\r' in token:
            raise ValueError('TOKEN_MISSING_OR_INVALID')
        self.token = token
        self.opener = build_opener(NoRedirect())

    def get(self, name):
        if name not in PATHS:
            raise ValueError('ENDPOINT_NOT_ALLOWED')
        req = Request('https://api.upstox.com'+PATHS[name],
                      headers={'Authorization':'Bearer '+self.token,'Accept':'application/json','User-Agent':'RB-ITOS-AI/1.0 (read-only readiness validation)'},method='GET')
        try:
            with self.opener.open(req, timeout=8) as response:
                raw = response.read(8_000_001)
            if len(raw)>8_000_000:
                return {'status':'error','error':'RESPONSE_TOO_LARGE'}
            return json.loads(raw)
        except HTTPError as exc:
            return {'status':'error','error':'HTTP_'+str(exc.code)}
        except (URLError, TimeoutError, OSError):
            return {'status':'error','error':'NETWORK_OR_TIMEOUT'}
        except (ValueError, UnicodeError):
            return {'status':'error','error':'INVALID_JSON'}


def sanitize(raw, name):
    if not isinstance(raw, dict) or raw.get('status')!='success':
        # Never echo provider bodies, tokens, profile details or exception text.
        error = raw.get('error') if isinstance(raw,dict) else None
        safe = error if error in {'NETWORK_OR_TIMEOUT','INVALID_JSON','RESPONSE_TOO_LARGE'} or (isinstance(error,str) and error.startswith('HTTP_') and error[5:].isdigit()) else 'PROVIDER_ERROR'
        return {'status':'FAIL','error':safe}
    data = raw.get('data')
    if name=='profile':
        return {'status':'PASS'} if isinstance(data,dict) and data else {'status':'FAIL','error':'INVALID_PROFILE'}
    if not isinstance(data,list) or any(not isinstance(x,dict) for x in data):
        return {'status':'FAIL','error':'INVALID_ROWS'}
    rows = [{k:r[k] for k in FIELDS[name] if k in r} for r in data]
    try:
        for row in rows:
            if not isinstance(row.get('instrument_token'),str) or not row.get('product'):
                raise ValueError()
            if name=='positions': integer(row.get('quantity'))
            elif name=='orders':
                if not row.get('order_id') or not row.get('status'): raise ValueError()
                for k in ('quantity','filled_quantity','pending_quantity'):
                    if integer(row.get(k))<0: raise ValueError()
            else:
                if not row.get('order_id') or integer(row.get('quantity'))<0: raise ValueError()
    except (ValueError,TypeError):
        return {'status':'FAIL','error':'INVALID_REQUIRED_FIELDS'}
    return {'status':'PASS','rows':rows}


def integer(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or int(value)!=value:
        raise ValueError('INVALID_QUANTITY')
    return int(value)


def positions_map(rows):
    result={}
    for r in rows:
        key=r['instrument_token']+'|'+r['product']
        if key in result: raise ValueError('DUPLICATE_POSITION')
        result[key]=integer(r['quantity'])
    return result


def changes(previous, current):
    """Account-level evidence only: never attribute an external exit automatically."""
    if not previous or previous.get('session_date')!=current['session_date']:
        return [{'status':'BASELINE_ONLY','reason':'FIRST_OBSERVATION_OR_NEW_SESSION'}]
    if any(x.get('status')!='PASS' for x in (previous['checks']['positions'],current['checks']['positions'])):
        return [{'status':'UNKNOWN','reason':'POSITION_EVIDENCE_UNAVAILABLE'}]
    try:
        before=positions_map(previous['checks']['positions']['rows'])
        after=positions_map(current['checks']['positions']['rows'])
    except ValueError:
        return [{'status':'UNKNOWN','reason':'INVALID_POSITION_EVIDENCE'}]
    # An absent row is unknown, not proof of zero quantity.
    events=[]
    for key in sorted(set(before)|set(after)):
        a,b=before.get(key),after.get(key)
        if a==b: continue
        kind='POSITION_CHANGE_REQUIRES_RECONCILIATION'
        if a is None or b is None: kind='POSITION_ROW_APPEARED_OR_MISSING'
        elif a!=0 and b==0: kind='BROKER_POSITION_NOW_FLAT'
        elif a*b>0 and abs(b)<abs(a): kind='BROKER_POSITION_REDUCED'
        events.append({'instrument_product':key,'before':a,'after':b,'status':kind,
                       'attribution':'UNKNOWN_API_OR_APP_OR_WEB_OR_OTHER_ACTIVITY',
                       'application_state_updated':False})
    return events


def atomic(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,indent=2,allow_nan=False); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def collect(get, previous=None):
    from zoneinfo import ZoneInfo
    now=datetime.now(timezone.utc)
    checks={name:sanitize(get(name),name) for name in PATHS}
    result={'model':'HILEGA_PRODUCTION_READONLY_V1','generated_at':now.isoformat(),
            'session_date':now.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat(),
            'observation_only':True,'orders_sent':False,'production_activation_allowed':False,
            'checks':checks,'snapshot_atomic':False,
            'readiness':'NOT_CLEARED_FOR_PRODUCTION',
            'remaining_gates':['STRATEGY_OWNERSHIP_MAPPING','STREAM_PLUS_REST_RECONCILIATION',
                'UI_MANUAL_EXIT_AND_EXTERNAL_EXIT_INTEGRATION','PARTIAL_FILL_AND_UNKNOWN_ORDER_RECOVERY',
                'REVERSAL_FILL_SERIALIZATION','RISK_LIMITS_AND_CONTRACT_SCOPE','CONTROLLED_PILOT_APPROVAL']}
    result['connection_status']='PASS' if all(c['status']=='PASS' for c in checks.values()) else 'FAIL'
    result['position_changes']=changes(previous,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fixture',type=Path,help='Offline JSON with profile/orders/trades/positions responses')
    p.add_argument('--env-file',type=Path,help='Optional existing local dotenv file; never printed or copied')
    p.add_argument('--token-env',default='UPSTOX_ACCESS_TOKEN')
    p.add_argument('--samples',type=int,default=1)
    p.add_argument('--interval',type=float,default=10)
    args=p.parse_args()
    if args.samples<1 or args.samples>360 or args.interval<5:
        p.error('samples must be 1..360 and interval >=5 seconds')
    os.umask(0o077)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file,override=False)
    fixture=json.loads(args.fixture.read_text()) if args.fixture else None
    client=None if fixture is not None else ReadOnlyClient(os.getenv(args.token_env,''))
    previous=None # New invocation never treats an older run as a fresh baseline.
    for i in range(args.samples):
        result=collect((lambda name:fixture.get(name,{})) if fixture is not None else client.get,previous)
        result['evidence_mode']='OFFLINE_FIXTURE' if fixture is not None else 'LIVE_READ_ONLY'
        atomic(args.output/'latest.json',result)
        atomic(args.output/('snapshot-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'),result)
        print(json.dumps({k:result[k] for k in ('generated_at','evidence_mode','connection_status','readiness','position_changes','orders_sent')}),flush=True)
        previous=result
        if i+1<args.samples: time.sleep(args.interval)
    return 0 if result['connection_status']=='PASS' else 2

if __name__=='__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error_type':type(exc).__name__,'orders_sent':False}))
        raise SystemExit(2)
