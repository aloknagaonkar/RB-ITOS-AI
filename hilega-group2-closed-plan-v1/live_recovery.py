"""Pinned closed-runtime pause recovery. Never arms, enrolls, captures credentials or sends orders."""
import argparse,hashlib,json,os,runpy,sys,uuid
from pathlib import Path

def need(ok,reason):
    if not ok:raise ValueError(reason)
def regular(path):
    path=Path(path);need(path.is_absolute() and path.is_file() and not any(x.is_symlink() for x in [path,*path.parents]),'REGULAR_ABSOLUTE_RECOVERY_INPUT_REQUIRED');return path.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def recover(config):
    need(config['model']=='HILEGA_CLOSED_PAUSE_RECOVERY_CONFIG_V1' and config['production_execution_enabled'] is False,'CLOSED_RECOVERY_CONFIG_REQUIRED')
    bundle=Path(config['bundle']);raw=regular(bundle/'RELEASE-MANIFEST.json');need(sha(raw)==config['release_manifest_sha256'],'APPROVED_CLOSED_RELEASE_CHANGED')
    manifest=json.loads(raw)
    for name,digest in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_RELEASE_INPUT_REQUIRED')
        need(sha(regular(bundle/rel))==digest,'CLOSED_RELEASE_SOURCE_CHANGED')
    registration=json.loads(regular(bundle/'CLOSED-REGISTRATION.json'))
    need(registration['mode']=='CLOSED_PREPARATION_ONLY' and registration['execution_factory_configured'] is False and registration['production_execution_enabled'] is False,'CLOSED_FACTORY_DISABLED_REGISTRATION_REQUIRED')
    need(sha(regular(Path(config['worker'])))==config['worker_sha256'],'INSTALLED_WRAPPER_CHANGED')
    app=Path(config['application_db']);regular(app)
    sys.dont_write_bytecode=True
    identity=runpy.run_path(str(bundle/'rehearse.py'),run_name='closed_recovery_runtime_identity');identity['verify_runtime_payload'](bundle)
    sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
    os.environ['HILEGA_PRODUCTION_EXECUTION_ROUTE']='PREPARATION_ONLY'
    os.environ['HILEGA_PRODUCTION_WORKSPACE_MODE']='SIMULATION_ONLY'
    # Avoid constructing a Store against an absent or unrelated database.
    import sqlite3
    db=sqlite3.connect(app.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        route=json.loads(db.execute('SELECT data FROM preparation_route WHERE id=1').fetchone()[0])
        need(route==dict(route='PREPARATION_ONLY',model='APPLICATION_PREPARATION_ROUTE_V1'),'PERSISTED_PREPARATION_ROUTE_REQUIRED')
        control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        need(control['production_execution_enabled'] is False and control['simulation_only'] is True,'CLOSED_CONTROLLER_REQUIRED')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need({'control','requests','events','sim_stop_state','sim_stop_requests','sim_orders','sim_fills','intents','preparation_plans'}<=tables,'EXISTING_CONTROLLER_SCHEMA_REQUIRED')
        for name in ('intents','sim_orders','sim_fills'):need(db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]==0,'SIMULATOR_HISTORY_ON_PREPARATION_ROUTE')
    finally:db.close()
    from market_lab.hilega_execution_port_v1 import adapter as port
    try:port.require_live_clearance()
    except port.GateClosed:pass
    else:raise ValueError('HARD_PRODUCTION_GATE_NOT_CLOSED')
    from market_lab.hilega_production_foundation.core import Store,SimBroker,Service
    store=Store(app);service=Service(store,SimBroker(store),worker_start=False)
    c=store.control();service.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='APPROVED_CLOSED_BOOT_PAUSE_RECOVERY',session_date=c['session_date'])
    after=store.control();need(after['mode']=='PAUSED' and not store.stop_state()['pending'],'RECOVERY_PAUSE_NOT_VERIFIED')
    return dict(status='CLOSED_PAUSE_RECOVERY_PASS',controller_paused=True,production_execution_enabled=False,controller_resumed=False,orders_sent=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--sha256',required=True);a=p.parse_args()
    raw=regular(a.config);need(sha(raw)==a.sha256,'EXACT_RECOVERY_CONFIG_REQUIRED');print(json.dumps(recover(json.loads(raw))));return 0
if __name__=='__main__':raise SystemExit(main())
