"""Pinned Upstox GET-only cash/order evidence. No orders or simulator writes."""
import argparse,json,os,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values
from analysis import funds,compare,Blocked
from market_lab.hilega_production_account_adapter_v1 import read_pin,matches,normalise,sign,AdapterBlocked,day
from market_lab.hilega_production_broker_observation_v1 import Client

def capture(client,pin):
    start=datetime.now(timezone.utc)
    base=dict(model='HILEGA_READ_ONLY_CASH_OBSERVATION_V1',evidence_mode='LIVE_READ_ONLY_ACCOUNT_PINNED',
        snapshot_id=uuid.uuid4().hex,account_scope=pin['scope'],started_at=start.isoformat(),session_date=day(start),
        production_execution_enabled=False,orders_sent=False,entry_permission=False,capture_atomic=False,debit_attribution='NOT_VALIDATED')
    try:
        matches(client.get('profile'),pin)
        before=funds(client.get('funds'))
        responses={k:client.get(k) for k in ('orders','trades','positions')}
        after=funds(client.get('funds'));matches(client.get('profile'),pin)
        end=datetime.now(timezone.utc)
        if not 0<=(end-start).total_seconds()<=30 or day(end)!=day(start):raise Blocked('CAPTURE_WINDOW_EXCEEDED_OR_SESSION_CHANGED')
        evidence=normalise(responses['orders'],responses['trades'],responses['positions'],observed_at=end.isoformat())
        base.update(status='READ_ONLY_CAPTURED',account_identity_verified=True,completed_at=end.isoformat(),
            funds_before=before,funds_after=after,funds_changed_during_capture=before!=after,**evidence)
    except (Blocked,AdapterBlocked) as exc:base.update(status='BLOCKED',reason=str(exc),account_identity_verified=False,completed_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:base.update(status='BLOCKED',reason='CAPTURE_UNAVAILABLE',error_type=type(exc).__name__,account_identity_verified=False,completed_at=datetime.now(timezone.utc).isoformat())
    base['signature']=sign(base,pin);return base

def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--samples',type=int,default=3);p.add_argument('--interval',type=float,default=10)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if not 1<=a.samples<=360 or not 5<=a.interval<=60:p.error('samples1–360; interval5–60 seconds')
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_FRESH_DIRECTORY')
    config=dotenv_values(a.env_file)
    def setting(k):
        v=config.get(k);e=os.environ.get(k)
        if v and e and v!=e:raise Blocked('SHELL_ENV_FILE_CONFLICT_'+k)
        return e or v
    token=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN')
    if not token:raise Blocked('READ_TOKEN_MISSING')
    pin=read_pin(a.pin_file);client=Client(token)
    a.output.mkdir(parents=True,mode=0o700);captures=[];comparisons=[]
    for index in range(a.samples):
        r=capture(client,pin);change=compare(captures[-1] if captures else None,r)
        save(a.output/('sample-'+str(index+1).zfill(3)+'.json'),r)
        captures.append(r);comparisons.append(change)
        print(json.dumps(dict(sample=index+1,status=r['status'],reason=r.get('reason'),comparison=change['status'],
            debit_attribution='NOT_VALIDATED',orders_sent=False)),flush=True)
        if index<a.samples-1:time.sleep(a.interval)
    success=all(r['status']=='READ_ONLY_CAPTURED' for r in captures)
    evidence_issues=any(r.get('diagnostics',{}).get('issues') for r in captures)
    report=dict(status='READ_ONLY_CAPTURE_PASS' if success else 'EVIDENCE_INCOMPLETE',
        generated_at=datetime.now(timezone.utc).isoformat(),samples=len(captures),comparisons=comparisons,
        debit_attribution='NOT_VALIDATED',production_ready=False,production_execution_enabled=False,orders_sent=False,
        strategy_ownership_verified=False,broker_diagnostics_present=evidence_issues,
        reservation_integration='NOT_IMPLEMENTED_REAL_CASH',simulator_updated=False)
    report['signature']=sign(report,pin);save(a.output/'report.json',report)
    lines=['# Read-only real cash observations','',
        'Capture success is not debit attribution or production approval. No orders or simulator writes.','',
        '| Sample | Capture | Comparison | Cash delta INR | Margin-used delta INR | New fills |',
        '|---|---|---|---:|---:|---:|']
    for i,(r,c) in enumerate(zip(captures,comparisons),1):
        vals=[i,r['status'],c['status'],c.get('cash_deltas',{}).get('cash_available_to_trade','—'),c.get('cash_deltas',{}).get('cash_margin_used','—'),c.get('new_fill_count','—')]
        lines.append('| '+' | '.join(str(x) for x in vals)+' |')
    lines+=['','Capture status: '+report['status'],'Debit attribution: NOT_VALIDATED','Real cash reservation integration: PENDING']
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);(a.output/'summary.md').chmod(0o600);print(text)
    return 0 if success else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except (Blocked,AdapterBlocked) as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False)));raise SystemExit(2)
