"""Bounded recovery for the approved CLOSED rollout. Original plan/tool remain unchanged."""
from contextlib import closing
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import hashlib

APPROVED='55ba58b26771b81ade1511e0b9f3324767fbc6768c2e2fa4d6ee3e6acbad4965'
TRANSIENT={'NEW_BRIDGE_HEARTBEAT_NOT_CURRENT','NEW_BRIDGE_LEASE_REQUIRED','BRIDGE_HEALTH_REQUIRED','SOURCE_WORKER_HEALTH_ERROR'}


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def regular(p):
    p=Path(p)
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_ABSOLUTE_FILE_REQUIRED')
    return p.read_bytes()


def wait_for_heartbeats(check,read,services,*,timeout=60,clock=time.monotonic,pause=time.sleep):
    deadline=clock()+timeout;first=None
    while clock()<deadline:
        need(services(),'MANAGED_SERVICE_EXITED_DURING_STARTUP')
        try:
            check()
            row=read();stamp=row['heartbeat_at']
            lease=row.get('lease_hash')
            if first is None or first[0]!=lease:first=(lease,stamp)
            elif stamp>first[1]:return dict(new_lease_verified=True,heartbeat_advanced=True)
        except ValueError as exc:
            if str(exc) not in TRANSIENT:raise
            row=read()
            if row and row.get('new_lease') and row.get('phase') in {'ERROR','STOPPED'}:
                raise ValueError('NEW_SOURCE_WORKER_REPORTED_ERROR_OR_STOPPED') from None
            first=None
        pause(1)
    raise ValueError('BOUNDED_SOURCE_STARTUP_TIMEOUT')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--retry',action='store_true')
    args=p.parse_args();repo=args.repo.resolve();package=Path(__file__).resolve().parent
    own=json.loads(regular(package/'MANIFEST.json'))
    for n,d in own.items():need(sha(regular(package/n))==d,'RETRY_PACKAGE_CHANGED')
    old=repo/'hilega-closed-rollout-v1';old_manifest=regular(old/'MANIFEST.json')
    for n,d in json.loads(old_manifest).items():need(sha(regular(old/n))==d,'ORIGINAL_ROLLOUT_TOOL_CHANGED')
    plan_path=args.plan.resolve();raw=regular(plan_path);need(sha(raw)==APPROVED,'EXACT_APPROVED_PLAN_REQUIRED')
    plan=json.loads(raw);folder=plan_path.parent
    need(plan['repo']==str(repo) and plan['tool_manifest_sha256']==sha(old_manifest),'ORIGINAL_PLAN_BINDING_CHANGED')
    spec=importlib.util.spec_from_file_location('approved_rollout',old/'rollout.py');roll=importlib.util.module_from_spec(spec);spec.loader.exec_module(roll)
    pins=json.loads(regular(old/'BASELINE_PINS.json'))
    for n,d in pins.items():
        if n not in roll.TARGETS:need(sha(regular(repo/n))==d,'BASELINE_PACKAGE_CHANGED')
    sys.path[:0]=[str(repo/'hilega-effective-environment-v1'),str(repo/'hilega-readonly-readiness-v1')]
    from effective_environment import environment_review,APP,ADAPTER
    env,paths=environment_review(repo,Path.home())
    need(env['environment_hash_revalidated'] and env['effective_database_paths_confirmed'],'PINNED_ENVIRONMENT_REQUIRED')
    config=Path.home()/'hilega-persistent-supervision-stage-v1/config-private.json'
    need(plan['environment_pins']==dict(configuration_sha256=sha(regular(config)),environment_sha256=sha(regular(repo/'.env'))),
         'APPROVED_ENVIRONMENT_CHANGED')
    need(plan['application_db']==str(paths[APP]) and plan['adapter_db']==str(paths[ADAPTER]),'APPROVED_DATABASE_PATH_CHANGED')
    tx=json.loads(regular(folder/'TRANSACTION.json'))
    need(tx['phase'] in {'STARTUP_FAILED_SERVICES_STOPPED','INSTALLED_SERVICES_STOPPED'},'EXACT_STOPPED_RETRY_PHASE_REQUIRED')
    need(tx['files']==plan['files'] and tx['repo']==plan['repo'],'TRANSACTION_BINDING_CHANGED')
    for e in plan['files']:need(sha(regular(roll.target(repo,e['name'])))==e['new_sha256'],'INSTALLED_CODE_CHANGED')
    manager=roll.Systemd()
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in roll.UNITS),'ALL_MANAGED_SERVICES_MUST_BE_STOPPED')
    roll.no_unmanaged_python(repo);roll.require_empty_closed_baseline(paths[APP],paths[ADAPTER])
    with tempfile.TemporaryDirectory(prefix='hilega-startup-retry-tests-') as temp:
        junit=Path(temp)/'junit.xml';environment=dict(os.environ,PYTHONPATH=str(package))
        code=subprocess.run([sys.executable,'-m','pytest',str(package/'test_startup_retry.py'),'-q','--junitxml='+str(junit)],cwd=repo,env=environment).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(code==0 and len(cases)==6 and not any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases),'STARTUP_RETRY_TESTS_MUST_PASS')
    if not args.retry:
        print(json.dumps(dict(status='RETRY_CHECK_PASS',collected_cases=6,services_changed=False,production_execution_enabled=False),indent=2));return 0
    app=paths[APP]
    def read():
        with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            row=db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
            if not row:return None
            data=json.loads(row[0]);return dict(phase=data.get('phase'),heartbeat_at=data.get('heartbeat_at'),
                lease_hash=sha(str(data.get('run_id')).encode()),
                new_lease=bool(data.get('run_id')) and sha(str(data['run_id']).encode())!=plan['previous_bridge_run_hash'])
    def bounded_health(app,previous):
        active=[u for u,s in tx['before'].items() if s['active']=='active']
        return wait_for_heartbeats(lambda:roll.closed_health(app,previous),read,
            lambda:all(manager.state(u)['active']=='active' and manager.state(u)['pid']>0 for u in active))
    roll.save(folder/'STARTUP-RETRY.json',dict(model='HILEGA_BOUNDED_APPROVED_STARTUP_RETRY_V1',plan_sha256=APPROVED,
        previous_phase=tx['phase'],timeout_seconds=60,requires_advancing_heartbeat=True,production_execution_enabled=False))
    # Preconditions prove the installed/stopped condition; record the retry transition explicitly.
    tx['phase']='INSTALLED_SERVICES_STOPPED';roll.save(folder/'TRANSACTION.json',tx)
    result=roll.start(folder,manager,healthcheck=bounded_health)
    report=dict(phase=result['phase'],new_lease_verified=True,heartbeat_advanced=True,
        controller_remains_paused=True,production_execution_enabled=False,production_ready=False)
    roll.save(folder/'STARTUP-RETRY-RESULT.json',report);print(json.dumps(report,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
