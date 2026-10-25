"""Persist signed real read-only captures; no order binding or submission."""
import argparse,json,os
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values
from registry import Registry,Blocked
from market_lab.hilega_production_account_adapter_v1 import read_pin,capture,sign,AdapterBlocked
from market_lab.hilega_production_broker_observation_v1 import Client

def save(path,data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--registry-db',type=Path,default=Path('data/research/hilega-disabled-live-intents/registry.sqlite'))
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    values=dotenv_values(a.env_file)
    def setting(k):
        f=values.get(k);e=os.environ.get(k)
        if f and e and f!=e:raise Blocked('SHELL_FILE_TOKEN_CONFLICT')
        return e or f
    token=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN')
    if not token:raise Blocked('READ_TOKEN_MISSING')
    pin=read_pin(a.pin_file);registry=Registry(a.registry_db,pin['scope'],'LIVE_READ_ONLY')
    snapshot=capture(Client(token),pin);a.output.mkdir(parents=True,mode=0o700);save(a.output/'account-capture.json',snapshot)
    result=registry.record_live_capture(snapshot,pin,as_of=datetime.now(timezone.utc).isoformat())
    result.update(model='HILEGA_DISABLED_INTENT_BINDING_READ_V1',live_capture_count=registry.status(as_of=datetime.now(timezone.utc).isoformat())['live_capture_count'])
    result['signature']=sign(result,pin);save(a.output/'report.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='signature'},indent=2));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except (Blocked,AdapterBlocked) as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False)));raise SystemExit(2)
