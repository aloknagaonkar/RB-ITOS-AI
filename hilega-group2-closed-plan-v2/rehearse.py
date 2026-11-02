"""Native pause recovery against new synthetic databases, never copies live database data."""
import argparse,json,os,subprocess,sys,uuid
from pathlib import Path
from live_recovery import need,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(mode=0o700);base=json.loads(a.config.read_text());bundle=Path(base['bundle'])
    sys.dont_write_bytecode=True;sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
    os.environ['HILEGA_PRODUCTION_EXECUTION_ROUTE']='PREPARATION_ONLY';os.environ['HILEGA_PRODUCTION_WORKSPACE_MODE']='SIMULATION_ONLY';os.environ['HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED']='0'
    from market_lab.hilega_production_foundation.core import Store,SimBroker,Service
    from market_lab.hilega_preparation_runtime_v1.source import Source
    outcomes=[]
    for scenario in ('paused-empty','armed-empty'):
        folder=a.output/scenario;folder.mkdir(mode=0o700);app=folder/'application.sqlite';store=Store(app);service=Service(store,SimBroker(store),worker_start=False)
        Source(service,run_id='SYNTHETIC_RECOVERY_REHEARSAL',provider=lambda:(_ for _ in ()).throw(AssertionError('Evidence must not be requested')))
        c=store.control();service.command('reconcile',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='RECOVERY_FIXTURE',session_date=c['session_date'])
        if scenario=='armed-empty':
            c=store.control();service.command('resume',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='RECOVERY_FIXTURE',session_date=c['session_date']);need(store.control()['mode']=='ARMED','NATIVE_FIXTURE_ARM_FAILED')
        cfg=dict(base,application_db=str(app));raw=(json.dumps(cfg,sort_keys=True,indent=2)+'\n').encode();path=folder/'CONFIG.json';path.write_bytes(raw);path.chmod(0o600)
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).with_name('live_recovery.py')),'--config',str(path),'--sha256',sha(raw)],capture_output=True,text=True,timeout=90)
        (folder/'recovery.log').write_text(result.stdout+result.stderr)
        need(result.returncode==0,'NATIVE_RECOVERY_REHEARSAL_FAILED: '+scenario)
        need(json.loads(result.stdout)['status']=='CLOSED_PAUSE_RECOVERY_PASS' and store.control()['mode']=='PAUSED' and not store.stop_state()['pending'],'SYNTHETIC_PAUSE_NOT_VERIFIED')
        with store.db() as db:
            for table in ('intents','sim_orders','sim_fills','preparation_plans'):need(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0,'SYNTHETIC_ACTIVITY_CREATED')
        outcomes.append(dict(scenario=scenario,native_pause_verified=True,disposable_database_only=True))
    print(json.dumps(dict(status='LIVE_ADAPTER_SYNTHETIC_REHEARSAL_PASS',scenarios=outcomes,live_database_mutated=False)));return 0
if __name__=='__main__':raise SystemExit(main())
