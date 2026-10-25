"""Pinned-account GET-only adapter observation. No mutation transport exists."""
import argparse,json,os
from pathlib import Path
from datetime import datetime,timezone
from dotenv import dotenv_values
from mapping import match,Blocked
from market_lab.hilega_production_account_adapter_v1 import read_pin,capture,verify,sign,AdapterBlocked
from market_lab.hilega_production_broker_observation_v1 import Client

def save(path,data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--draft',type=Path);p.add_argument('--known-order-id');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if bool(a.draft)!=bool(a.known_order_id):p.error('--draft and --known-order-id must be supplied together')
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    values=dotenv_values(a.env_file)
    def setting(k):
        f=values.get(k);e=os.environ.get(k)
        if f and e and f!=e:raise Blocked('SHELL_FILE_TOKEN_CONFLICT')
        return e or f
    token=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN')
    if not token:raise Blocked('READ_TOKEN_MISSING')
    pin=read_pin(a.pin_file);snapshot=capture(Client(token),pin);a.output.mkdir(parents=True,mode=0o700)
    save(a.output/'account-capture.json',snapshot)
    try:
        verify(snapshot,pin,as_of=datetime.now(timezone.utc).isoformat())
        if a.draft:
            request=json.loads(a.draft.read_text());result=match(request,snapshot,a.known_order_id,expected_account_scope=pin['scope'],as_of=datetime.now(timezone.utc).isoformat())
        else:result=dict(status='ACCOUNT_CAPTURE_ONLY_NO_ORDER_MAPPING',ownership_verified=False,entry_permission=False)
        report=dict(model='HILEGA_DISABLED_UPSTOX_ADAPTER_OBSERVATION_V1',capture_verified=True,result=result,
            counts={k:len(snapshot[k]) for k in ('orders','trades','positions')},production_execution_enabled=False,
            orders_sent=False,mutation_transport='DISABLED_IN_CODE',strategy_ownership_verified=False)
    except (Blocked,AdapterBlocked) as exc:report=dict(status='BLOCKED',reason=str(exc),capture_verified=False,production_execution_enabled=False,orders_sent=False)
    report['signature']=sign(report,pin);save(a.output/'report.json',report)
    # No order IDs, cash, account scope or position details in terminal output.
    print(json.dumps({k:report.get(k) for k in ('capture_verified','status','reason','result','counts','production_execution_enabled','orders_sent','mutation_transport')},indent=2))
    return 0 if report.get('capture_verified') and (not a.draft or report['result']['status']=='REQUEST_FIELDS_MATCH_READ_ONLY_OWNERSHIP_UNVERIFIED') else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except (Blocked,AdapterBlocked) as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False)));raise SystemExit(2)
