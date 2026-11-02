"""Run actual closed candidate worker twice, confined to new disposable local state."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def need(ok,reason):
    if not ok:raise ValueError(reason)


def run(release,output):
    release=Path(release).resolve();output=Path(output).resolve()
    need(not output.exists(),'NEW_REHEARSAL_DIRECTORY_REQUIRED');output.mkdir(mode=0o700)
    journal=output/'empty-strategy.jsonl';journal.write_text('');env_file=output/'empty.env';env_file.write_text('')
    app=output/'application.sqlite';adapter=output/'adapter.sqlite'
    environment={'PATH':os.defpath,'LANG':'C.UTF-8','HOME':str(output),'PYTHONDONTWRITEBYTECODE':'1',
        'HILEGA_PRODUCTION_WORKSPACE_MODE':'SIMULATION_ONLY','HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED':'1',
        'HILEGA_PRODUCTION_EXECUTION_ROUTE':'PREPARATION_ONLY','HILEGA_PRODUCTION_SIM_DB':str(app),
        'HILEGA_PREPARATION_ADAPTER_DB':str(adapter),'HILEGA_PREPARATION_CAPTURE_ON_SIGNAL':'0',
        'PYTHONPATH':os.pathsep.join(map(str,[release/'backend',release/'runtime']))}
    runs=[];leases=[]
    for attempt in range(2):
        r=subprocess.run([sys.executable,'-B',str(release/'closed_worker_launcher.py'),'--once',
            '--env-file',str(env_file),'--source',str(journal)],cwd=output,env=environment,capture_output=True,text=True,timeout=20)
        (output/f'worker-{attempt+1}-stdout.txt').write_text(r.stdout)
        (output/f'worker-{attempt+1}-stderr.txt').write_text(r.stderr)
        need(r.returncode==0,'ACTUAL_DISPOSABLE_WORKER_FAILED: '+r.stderr[-3000:])
        with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
            health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
            need(control['mode']=='PAUSED','DISPOSABLE_CONTROLLER_LEFT_PAUSED_MODE')
            for table in ('intents','sim_orders','sim_fills','preparation_plans','preparation_outbox','preparation_shadow_holds'):
                need(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0,'DISPOSABLE_ORDER_OR_PREPARATION_CREATED')
            need(health['phase']=='STOPPED','CLOSED_ONCE_WORKER_DID_NOT_FINISH_LEASE')
            leases.append(health['run_id'])
        need(not adapter.exists(),'DISPOSABLE_ADAPTER_WAS_UNEXPECTEDLY_OPENED')
        runs.append(dict(attempt=attempt+1,exit_code=r.returncode,controller_paused=True,orders_and_preparations_empty=True))
    need(leases[0]!=leases[1],'RESTART_DID_NOT_CREATE_NEW_DISPOSABLE_LEASE')
    report=dict(status='ACTUAL_DISPOSABLE_CLOSED_WORKER_RESTART_PASS',runs=runs,
        actual_candidate_worker_executed=True,disposable_databases_only=True,
        empty_journal_only=True,fresh_signal_preparation_verified=False,live_database_opened=False,
        credentials_provided=False,application_services_changed=False,production_execution_enabled=False)
    (output/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.release,a.output),indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
