"""GET-only source provider check using the running worker's explicit read context."""
import argparse,json,os,re,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path

def need(ok,reason):
    if not ok:raise ValueError(reason)

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--application',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True);p.add_argument('--pid',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    proc=Path('/proc')/str(a.pid);need(proc.stat().st_uid==os.getuid() and (proc/'cwd').resolve()==a.repo.resolve(),'EXACT_SOURCE_WORKER_PROCESS_REQUIRED')
    environment=dict(x.split(b'=',1) for x in (proc/'environ').read_bytes().split(b'\0') if b'=' in x)
    names=('HOME','HILEGA_PRODUCTION_EXECUTION_ROUTE','HILEGA_PRODUCTION_WORKSPACE_MODE','HILEGA_PREPARATION_PIN_FILE','HILEGA_PREPARATION_ENV_FILE','HILEGA_PREPARATION_EVIDENCE_FILE','HILEGA_PREPARATION_CAPTURE_ON_SIGNAL','HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED','HILEGA_PREPARATION_ADAPTER_DB','UPSTOX_ACCESS_TOKEN','HILEGA_PRODUCTION_BROKER_READ_TOKEN')
    for name in names:
        os.environ.pop(name,None)
        if name.encode() in environment:os.environ[name]=environment[name.encode()].decode()
    del environment
    need(os.environ.get('HILEGA_PRODUCTION_EXECUTION_ROUTE')=='PREPARATION_ONLY' and os.environ.get('HILEGA_PREPARATION_CAPTURE_ON_SIGNAL')=='1' and os.environ.get('HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED')=='1' and not os.environ.get('HILEGA_PREPARATION_EVIDENCE_FILE'),'RUNNING_FRESH_ATOMIC_GET_PROVIDER_REQUIRED')
    selected=Path(os.environ.get('HILEGA_PREPARATION_ADAPTER_DB','data/research/hilega-broker-adapter-closed/adapter.sqlite'))
    need((selected if selected.is_absolute() else a.repo/selected).resolve()==a.adapter.resolve(),'RUNNING_ADAPTER_PATH_CHANGED')
    os.chdir(a.repo);sys.dont_write_bytecode=True;sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    from market_lab.hilega_preparation_runtime_v1.source import configured_evidence
    from market_lab.hilega_preparation_runtime_v1 import evidence
    from market_lab.hilega_execution_port_v1 import adapter as port
    try:port.require_live_clearance()
    except port.GateClosed:pass
    else:raise ValueError('HARD_ORDER_GATE_NOT_CLOSED')
    bundle,pin=configured_evidence();end=datetime.now(timezone.utc);evidence.validate(bundle,pin,as_of=end.isoformat())
    db=sqlite3.connect(a.adapter.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON');meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0]);need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'SOURCE_PIN_AND_ADAPTER_SCOPE_CHANGED')
    finally:db.close()
    file=a.output/'private-source-evidence.json';fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(bundle,f);f.write('\n')
    result=dict(status='RUNNING_SOURCE_GET_EVIDENCE_PREFLIGHT_PASS',source_pid=a.pid,
        source_signature_and_freshness_verified=True,source_pin_matches_adapter=True,
        provider_uses_running_worker_context=True,source_evidence_file_saved_privately=True,
        actual_private_authority_loaded=False,owner_enrolled=False,production_execution_enabled=False)
    print(json.dumps(result));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        reason=str(exc);safe=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',reason) else 'SOURCE_READ_CONTEXT_OR_MARKET_EVIDENCE_REQUIRES_REVIEW'
        print(json.dumps(dict(status='SOURCE_PROVIDER_PREFLIGHT_BLOCKED',reason=safe,error_type=type(exc).__name__,production_execution_enabled=False)));raise SystemExit(2)
