"""Pinned GET-only baseline for the closed adapter; never calls mutation transport."""
import argparse,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values
from adapter import Adapter,Store,HttpTransport,Blocked
from market_lab.hilega_production_account_adapter_v1 import read_pin,capture,sign
from market_lab.hilega_production_broker_observation_v1 import Client

def save(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'));p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--store',type=Path,default=Path('data/research/hilega-broker-adapter-closed/adapter.sqlite'));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    deps=json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for relative,expected in deps.items():
        path=Path(relative)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise Blocked('READ_ONLY_DEPENDENCY_DIFFERS_'+path.name)
    config=dotenv_values(a.env_file)
    def setting(k):
        file=config.get(k);shell=os.environ.get(k)
        if file and shell and file!=shell:raise Blocked('SHELL_ENV_CONFLICT_'+k)
        return shell or file
    token=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN')
    if not token:raise Blocked('READ_TOKEN_REQUIRED')
    pin=read_pin(a.pin_file);a.output.mkdir(parents=True,mode=0o700)
    record=capture(Client(token),pin);save(a.output/'account-capture.json',record)
    adapter=Adapter(Store(a.store,pin['scope'],'LIVE_CLOSED'),HttpTransport(lambda:token))
    result=adapter.reconcile_read_only(record,pin,as_of=datetime.now(timezone.utc).isoformat())
    result.update(capture_verified=True,transport_gate='CLOSED_IN_CODE',application_integrated=False)
    report=dict(result=result,adapter=adapter.status());report['signature']=sign(report,pin);save(a.output/'report.json',report)
    print(json.dumps(result,indent=2));return 0 if result['status']=='EMPTY_READ_ONLY_BASELINE' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except Blocked as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False)));raise SystemExit(2)
