"""Actual native controller startup pause, confined to newly created disposable databases."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--release',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    a.output.mkdir(mode=0o700)
    sys.dont_write_bytecode=True;sys.path[:0]=[str(a.release/'backend'),str(a.release/'runtime')]
    os.environ['HILEGA_PRODUCTION_EXECUTION_ROUTE']='PREPARATION_ONLY';os.environ['HILEGA_PRODUCTION_WORKSPACE_MODE']='SIMULATION_ONLY';os.environ['HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED']='0'
    from market_lab.hilega_production_foundation.core import Store,SimBroker,Service
    from market_lab.hilega_preparation_runtime_v1.source import Source
    from worker_binding import ensure_paused
    results=[]
    for scenario in ['already-paused','persisted-armed']:
        folder=a.output/scenario;folder.mkdir(mode=0o700)
        store=Store(folder/'application.sqlite');service=Service(store,SimBroker(store),worker_start=False)
        Source(service,run_id='SYNTHETIC_TRUST_RECOVERY',provider=lambda:(_ for _ in ()).throw(AssertionError('No evidence capture')))
        c=store.control();service.command('reconcile',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='SYNTHETIC_STARTUP',session_date=c['session_date'])
        if scenario=='persisted-armed':
            c=store.control();service.command('resume',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='SYNTHETIC_STARTUP',session_date=c['session_date'])
            assert store.control()['mode']=='ARMED'
        ensure_paused(service);ensure_paused(service)
        assert store.control()['mode']=='PAUSED' and not store.stop_state()['pending']
        with store.db() as db:
            for table in ['intents','sim_orders','sim_fills','preparation_plans']:assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        results.append(dict(scenario=scenario,paused=True,disposable_database_only=True))
    print(json.dumps(dict(status='NATIVE_REGISTRATION_STARTUP_RECOVERY_PASS',scenarios=results)))


if __name__=='__main__':main()
