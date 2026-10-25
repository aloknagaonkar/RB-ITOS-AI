"""Read-only actual cash evidence and isolated shadow capacity; no real orders."""
import argparse,hashlib,importlib.util,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values
from gate import ShadowBook,Blocked
from market_lab.hilega_production_account_adapter_v1 import read_pin,sign
from market_lab.hilega_production_broker_observation_v1 import Client

def dependencies(root):
    expected=json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for relative,sha in expected.items():
        p=root/relative
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise Blocked('READ_ONLY_DEPENDENCY_DIFFERS_'+Path(relative).name)

def load_capture(root):
    folder=root/'hilega-production-cash-observation'
    # This imports the previously validated GET-only capture function; its CLI
    # main guard does not run. No credentials are sent to another destination.
    sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location('validated_cash_observation_capture',folder/'run.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.capture

def save(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--book',type=Path,default=Path('data/research/hilega-real-cash-shadow/shadow.sqlite'))
    p.add_argument('--proposed-cost',help='Explicit illustrative basket cost incl. buffer; not a contract-approved plan')
    p.add_argument('--shadow-plan-id',help='Optional: create only an isolated shadow hold; requires proposed cost')
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    if a.shadow_plan_id and a.proposed_cost is None:p.error('--shadow-plan-id requires --proposed-cost')
    root=Path.cwd();dependencies(root);config=dotenv_values(a.env_file)
    def setting(name):
        shell=os.environ.get(name);file=config.get(name)
        if shell and file and shell!=file:raise Blocked('SHELL_ENV_FILE_CONFLICT_'+name)
        return shell or file
    token=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN')
    if not token:raise Blocked('READ_TOKEN_MISSING')
    pin=read_pin(a.pin_file);capture=load_capture(root);a.output.mkdir(parents=True,mode=0o700)
    record=capture(Client(token),pin);save(a.output/'cash-capture.json',record)
    book=ShadowBook(a.book,pin['scope']);now=datetime.now(timezone.utc).isoformat()
    try:
        if a.shadow_plan_id:book.reserve_shadow(a.shadow_plan_id,a.proposed_cost,record,pin,as_of=now)
        result=book.preview(record,pin,as_of=now,proposed_cost=None if a.shadow_plan_id else a.proposed_cost)
    except Blocked as exc:result=dict(status='BLOCKED',reason=str(exc),entry_permission=False,production_execution_enabled=False,orders_sent=False,application_ledger_updated=False)
    result.update(generated_at=now,evidence_mode='READ_ONLY_REAL_CASH_WITH_ISOLATED_SHADOW_BOOK',debit_attribution='NOT_VALIDATED')
    result['signature']=sign(result,pin);save(a.output/'report.json',result)
    safe={k:result.get(k) for k in ('status','reason','reasons','capture_verified','debit_attribution','entry_permission','production_execution_enabled','orders_sent','application_ledger_updated')}
    print(json.dumps(safe,indent=2))
    text='# Real-cash shadow gate\n\nRead-only capture. No trading permission or application-ledger changes.\n\n| Check | Result |\n|---|---|\n'
    for k,v in safe.items():text+='| '+k+' | '+str(v)+' |\n'
    text+='\nCash values and shadow holds are in private report.json. No assumed reflected overlap or cash addback.\n'
    fd=os.open(a.output/'summary.md',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(text)
    return 0 if result['status']=='READ_ONLY_SHADOW_CAPACITY_AVAILABLE' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except Blocked as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False,production_execution_enabled=False)));raise SystemExit(2)
