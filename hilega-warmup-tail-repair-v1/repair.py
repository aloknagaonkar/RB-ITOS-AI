"""Back up and repair one incomplete historical warmup cache using broker GETs."""
import argparse
from datetime import date,datetime,timedelta
import hashlib,json,os
from pathlib import Path
import subprocess,sys,tempfile
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import quote
from urllib.error import HTTPError,URLError
from repair_core import *

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('BROKER_REDIRECT_BLOCKED')

def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_FILE_REQUIRED')
    return p.read_bytes()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--session',default='2026-10-30')
    ap.add_argument('--repair',action='store_true')
    ap.add_argument('--env-file',type=Path)
    args=ap.parse_args();folder=Path(__file__).absolute().parent
    manifest=json.loads(regular(folder/'MANIFEST.json'))
    for name,digest in manifest.items():need(sha(regular(folder/name))==digest,'REPAIR_PACKAGE_CHANGED')
    repo=args.repo.absolute();day=date.fromisoformat(args.session)
    need(day<datetime.now(IST).date(),'COMPLETED_PAST_SESSION_REQUIRED')
    path=repo/'data/historical-evidence/hilega-milega-underlying-cache-v1'/f'{day}.json'
    raw=regular(path);old=json.loads(raw)
    missing=missing_minutes(old['candles'],day)
    print(json.dumps(dict(session=str(day),cached_count=len(old['candles']),missing_1m=missing)),flush=True)
    if not args.repair:return 0
    r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(folder/'test_repair.py')])
    need(r.returncode==0,'REPAIR_TESTS_FAILED')
    pins=json.loads(regular(folder/'SOURCE-PINS.json'))
    for name,digest in pins.items():need(sha(regular(repo/name))==digest,'APPLICATION_VALIDATOR_CHANGED: '+name)
    sys.path.insert(0,str(repo/'backend'))
    from market_lab.gateways import normalize_upstox_historical_candles
    from market_lab.hilega_milega_historical_replay_v1 import aggregate_exact_5m
    def native(rows):
        body={'data':{'candles':[[x[k] for k in ('timestamp','open','high','low','close','volume','open_interest')] for x in rows]}}
        candles=normalize_upstox_historical_candles(UNDERLYING,day,body)
        bars=aggregate_exact_5m(candles,day,require_full_session=True)
        need(len(candles)==375 and len(bars)==75,'NATIVE_FULL_SESSION_VALIDATION_FAILED')
    if not missing:
        proposed_cache(old,old['candles'],day);native(old['candles'])
        print(json.dumps({'status':'ALREADY_COMPLETE','cache_modified':False}));return 0
    env=args.env_file or repo/'.env';regular(env)
    need(env.stat().st_uid==os.getuid() and env.stat().st_mode & 0o077==0,'PRIVATE_OWNED_ENV_REQUIRED')
    from dotenv import dotenv_values
    settings=dotenv_values(env);token=settings.get('UPSTOX_ACCESS_TOKEN') or settings.get('HILEGA_PRODUCTION_BROKER_READ_TOKEN')
    need(isinstance(token,str) and token.strip(),'BROKER_READ_TOKEN_MISSING');token=token.strip();del settings
    opener=build_opener(NoRedirect());attempts=[];candidate=[]
    for first in (day,day-timedelta(days=1)):
        url='https://api.upstox.com/v3/historical-candle/'+quote(UNDERLYING,safe='')+'/minutes/1/'+str(day)+'/'+str(first)
        request=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'},method='GET')
        try:
            with opener.open(request,timeout=15) as response:
                data=response.read(8*1024*1024+1);need(len(data)<=8*1024*1024,'BROKER_RESPONSE_TOO_LARGE')
        except HTTPError as exc:raise ValueError('BROKER_HTTP_'+str(exc.code)) from None
        except URLError:raise ValueError('BROKER_NETWORK_FAILED') from None
        candidate=normalize_v3(json.loads(data),day)
        gaps=missing_minutes(candidate,day);attempts.append(dict(from_date=str(first),count=len(candidate),missing_1m=gaps))
        if not gaps:break
    del token,request
    payload,changed=proposed_cache(old,candidate,day);native(payload['candles'])
    audit=Path(tempfile.mkdtemp(prefix='hilega-warmup-repair-',dir=repo));os.chmod(audit,0o700)
    (audit/'.gitignore').write_text('*\n')
    receipt=atomic_repair(path,raw,payload,audit/'original-cache.json')
    report=dict(status='WARMUP_CACHE_REPAIRED',session=str(day),candle_count=375,five_minute_count=75,
        fetch_attempts=attempts,overlapping_revisions=changed,**receipt,application_code_modified=False,
        services_changed=False,orders_sent=False,live_alert_clearance_verified=False)
    (audit/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        # Do not expose provider bodies, credential values, or unexpected exception text.
        safe=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        print(json.dumps(dict(status='REPAIR_BLOCKED',reason=safe)),flush=True);raise SystemExit(2)
