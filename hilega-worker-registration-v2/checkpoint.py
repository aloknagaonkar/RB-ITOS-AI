"""Read-only checkpoint for the approved running CLOSED preparation hook."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import time

APPROVED='55ba58b26771b81ade1511e0b9f3324767fbc6768c2e2fa4d6ee3e6acbad4965'
UNITS=('hilega-production-source-worker.service','hilega-worker.service','hilega-api.service',
 'hilega-lifecycle-reference.service','hilega-observation-analytics.service','hilega-observation-readiness.service')


def need(ok,reason):
    if not ok:raise ValueError(reason)


def regular(path):
    path=Path(path);need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_FILE_REQUIRED')
    return path.read_bytes()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def snapshot(plan):
    result={}
    for kind,key in [('application','application_db'),('adapter','adapter_db')]:
        path=Path(plan[key]);need(path.is_file() and not path.is_symlink(),'REGULAR_DATABASE_REQUIRED')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            wanted=('preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations') if kind=='application' else ('requests','attempts','receipts')
            result[kind+'_counts']={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in wanted if t in tables}
            if kind=='application':
                c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
                h=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
                stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
                at=datetime.fromisoformat(h['heartbeat_at']);need(at.tzinfo is not None,'AWARE_HEARTBEAT_REQUIRED')
                result.update(controller_paused=c['mode']=='PAUSED',stop_pending=not stop or stop[0]!=stop[1],
                    heartbeat_at=h['heartbeat_at'],heartbeat_age_seconds=round((datetime.now(timezone.utc)-at).total_seconds(),3),
                    bridge_running_without_error=h.get('phase')=='RUNNING' and not h.get('problem'),
                    lease_fingerprint=sha(str(h.get('run_id')).encode()),
                    candidate_owner_present='preparation_candidate_exclusive_source_owner_v1' in tables,
                    candidate_coordinator_present='preparation_candidate_coordinator_state_v1' in tables)
            else:
                meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0]);result['adapter_live_closed']=meta.get('mode')=='LIVE_CLOSED'
            db.rollback()
    return result


def services():
    rows=[]
    for unit in UNITS:
        r=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,SubState,MainPID,NRestarts'],capture_output=True,text=True,timeout=10)
        need(r.returncode==0,'SERVICE_QUERY_FAILED')
        fields=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
        rows.append(dict(unit=unit,active=fields.get('ActiveState')=='active',sub_state=fields.get('SubState'),
            pid=int(fields.get('MainPID','0')),restart_count=int(fields.get('NRestarts','0'))))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--compatibility-review',type=Path,required=True)
    args=p.parse_args();repo=args.repo.resolve();plan_path=args.plan.resolve()
    package_root=Path(__file__).resolve().parent
    for name,digest in json.loads(regular(package_root/'MANIFEST.json')).items():
        need(sha(regular(package_root/name))==digest,'POSTDEPLOY_CHECK_PACKAGE_CHANGED')
    raw=regular(plan_path)
    need(sha(raw)==APPROVED,'EXACT_APPROVED_PLAN_REQUIRED');plan=json.loads(raw);need(plan['repo']==str(repo),'APPROVED_ROOT_CHANGED')
    tx=json.loads(regular(plan_path.parent/'TRANSACTION.json'));need(tx['phase']=='CLOSED_HOOK_RUNNING','VERIFIED_RUNNING_TRANSACTION_REQUIRED')
    for e in plan['files']:need(sha(regular(repo/e['name']))==e['new_sha256'],'INSTALLED_HOOK_HASH_CHANGED')
    compat=args.compatibility_review.resolve();receipt=json.loads(regular(compat/'REPORT.json'))
    need(receipt['status']=='COMPATIBILITY_APPLIED_SERVICES_STOPPED','APPLIED_COMPATIBILITY_RECEIPT_REQUIRED')
    service=repo/'hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py'
    need(regular(service)==regular(compat/'lifecycle_reference_service.py'),'COMPANION_CHANGED_AFTER_COMPATIBILITY_REVIEW')
    spec=importlib.util.spec_from_file_location('postdeploy_reference_check',service)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    package=repo/'hilega-operational-lifecycle-tools-6cexrur_';module.check_package(repo,package)
    before_services=services();before=snapshot(plan)
    deadline=time.monotonic()+30
    after=before
    while time.monotonic()<deadline:
        time.sleep(2);after=snapshot(plan)
        if after['lease_fingerprint']!=before['lease_fingerprint'] or after['heartbeat_at']>before['heartbeat_at']:break
    after_services=services()
    advancing=after['lease_fingerprint']==before['lease_fingerprint'] and after['heartbeat_at']>before['heartbeat_at']
    checks=dict(installed_hook_hashes_match=True,companion_integrity_check_passed=True,
        all_services_active=all(r['active'] and r['pid']>0 for r in before_services+after_services),
        service_pids_stable=all(a['pid']==b['pid'] and a['restart_count']==b['restart_count'] for a,b in zip(before_services,after_services)),
        controller_remains_paused=before['controller_paused'] and after['controller_paused'],
        no_pending_stop=not before['stop_pending'] and not after['stop_pending'],
        heartbeat_advances_on_same_lease=advancing,
        heartbeat_current_and_healthy=all(0<=r['heartbeat_age_seconds']<=30 and r['bridge_running_without_error'] for r in (before,after)),
        closed_adapter=before['adapter_live_closed'] and after['adapter_live_closed'],
        no_preparation_or_adapter_activity=all(v==0 for r in (before,after) for k in ('application_counts','adapter_counts') for v in r[k].values()),
        execution_candidate_not_enrolled=not any(r['candidate_owner_present'] or r['candidate_coordinator_present'] for r in (before,after)))
    report=dict(status='CLOSED_POSTDEPLOY_CHECK_PASS' if all(checks.values()) else 'CLOSED_POSTDEPLOY_CHECK_REQUIRES_REVIEW',
        assessed_at=datetime.now(timezone.utc).isoformat(),checks=checks,services=after_services,
        heartbeat_at=after['heartbeat_at'],heartbeat_age_seconds=after['heartbeat_age_seconds'],
        application_counts=after['application_counts'],adapter_counts=after['adapter_counts'],
        scope='RUNNING_CLOSED_PREPARATION_HOOK_ONLY',live_database_inspected=True,sql_mutations_issued=False,
        account_capture_requested=False,service_control_commands_issued=False,
        execution_session_factory_configured=False,broker_network_validated=False,
        full_release_regression_reexecuted=False,production_execution_enabled=False,production_ready=False)
    path=plan_path.parent/'POST-DEPLOYMENT-BOUNDED.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',path);return 0 if all(checks.values()) else 1

if __name__=='__main__':raise SystemExit(main())
