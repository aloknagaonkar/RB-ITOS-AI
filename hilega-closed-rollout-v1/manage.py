"""Default CHECK only. Mutating maintenance actions require an explicit reviewed plan SHA."""
import argparse
import fcntl
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from rollout import TARGETS,UNITS,Systemd,regular,sha,save,need,require_empty_closed_baseline,apply,start,rollback,hold,cancel_before_install


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--action',choices=['check','apply','start','hold','rollback','cancel-before-install'],default='check')
    p.add_argument('--plan',type=Path);p.add_argument('--approve-plan-sha256')
    args=p.parse_args();repo=args.repo.resolve();package=Path(__file__).resolve().parent
    own=json.loads(regular(package/'MANIFEST.json'))
    for name,digest in own.items():need(sha(regular(package/name))==digest,'ROLLOUT_PACKAGE_CHANGED')
    pins=json.loads(regular(package/'BASELINE_PINS.json'))
    for name,digest in pins.items():
        if args.action!='check' and name in TARGETS:continue
        need(sha(regular(repo/name))==digest,'REVIEWED_BASELINE_CHANGED')
    sys.path[:0]=[str(repo/'hilega-effective-environment-v1'),str(repo/'hilega-readonly-readiness-v1')]
    from effective_environment import environment_review,APP,ADAPTER
    environment,paths=environment_review(repo,Path.home())
    need(environment['environment_hash_revalidated'] and environment['effective_database_paths_confirmed'],'CURRENT_STARTUP_ENVIRONMENT_NOT_CONFIRMED')
    config=Path.home()/'hilega-persistent-supervision-stage-v1/config-private.json'
    environment_pins=dict(configuration_sha256=sha(regular(config)),environment_sha256=sha(regular(repo/'.env')))
    if args.action!='check':
        lock_fd=os.open(repo/'.hilega-closed-rollout.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(lock_fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_ROLLOUT_LOCK_REQUIRED')
        fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Descriptor stays open for this CLI process; the kernel releases it on exit.
        need(args.plan is not None and args.approve_plan_sha256,'EXPLICIT_PLAN_AND_APPROVAL_SHA_REQUIRED')
        plan_path=args.plan.resolve();need(plan_path.name=='PLAN.json','EXACT_PLAN_FILENAME_REQUIRED')
        raw=regular(plan_path);need(sha(raw)==args.approve_plan_sha256,'PLAN_APPROVAL_SHA_MISMATCH')
        plan=json.loads(raw);need(plan['repo']==str(repo) and plan['tool_manifest_sha256']==sha(regular(package/'MANIFEST.json')),'PLAN_TOOL_OR_ROOT_CHANGED')
        need(plan['environment_pins']==environment_pins and plan['application_db']==str(paths[APP]) and plan['adapter_db']==str(paths[ADAPTER]),'PLAN_ENVIRONMENT_CHANGED')
        folder=plan_path.parent
        checked=json.loads(regular(folder/'CHECK-VALIDATION.json'))
        need(checked.get('status')=='PASS_TARGETED_ONLY' and checked.get('plan_sha256')==args.approve_plan_sha256,'PASSED_PLAN_CHECK_REQUIRED')
        manager=Systemd()
        if args.action=='apply':
            save(folder/'EXPLICIT-CLOSED-RELEASE-APPROVAL.json',dict(plan_sha256=args.approve_plan_sha256,scope='CLOSED_HOOK_ONLY',production_execution_enabled=False))
            result=apply(plan,folder,manager)
        elif args.action=='start':result=start(folder,manager)
        elif args.action=='hold':result=hold(folder,manager)
        elif args.action=='rollback':result=rollback(folder,manager)
        else:result=cancel_before_install(folder,manager)
        print(json.dumps(dict(phase=result['phase'],production_execution_enabled=False,production_ready=False),indent=2));return 0
    previous=repo/'hilega-effective-environment-v1/VM-VALIDATION.json';evidence=json.loads(regular(previous))
    need(evidence.get('status')=='PASS_TARGETED_ONLY' and evidence.get('environment_hash_revalidated') is True
         and evidence.get('effective_database_paths_confirmed_from_startup_contract') is True
         and evidence.get('baseline_blockers')==[] and evidence.get('production_execution_enabled') is False,'PRIOR_ENVIRONMENT_BASELINE_REQUIRED')
    require_empty_closed_baseline(paths[APP],paths[ADAPTER])
    v2=json.loads(regular(repo/'hilega-closed-release-v2/VM-VALIDATION.json'))
    need(v2.get('status')=='PASS_TARGETED_ONLY' and v2.get('collected_cases')==212 and v2.get('broader_integration_reexecuted') is True,'PRIOR_212_CASE_INTEGRATION_REQUIRED')
    stage=Path(v2['stage']);stage_pins=json.loads(regular(Path(v2['review_folder'])/'STAGED-MANIFEST.json'))
    entries=[]
    for name in TARGETS:
        new=regular(stage/name);need(sha(new)==stage_pins[name],'VERIFIED_STAGE_CHANGED')
        old=repo/name;raw=regular(old) if old.exists() else None
        entries.append(dict(name=name,old_sha256=sha(raw) if raw is not None else None,new_sha256=sha(new),
            mode=stat.S_IMODE(old.stat().st_mode) if raw is not None else 0o644))
    with closing(sqlite3.connect(paths[APP].as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        row=db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
        need(row is not None,'CURRENT_BRIDGE_LEASE_REQUIRED');previous_run=json.loads(row[0]).get('run_id')
        need(isinstance(previous_run,str) and previous_run,'CURRENT_BRIDGE_LEASE_REQUIRED')
    states={u:Systemd().state(u) for u in UNITS}
    need(states[UNITS[0]]['active']=='active','SOURCE_SERVICE_MUST_BE_ACTIVE_FOR_STARTUP_REVIEW')
    folder=Path(tempfile.mkdtemp(prefix='hilega-closed-rollout-plan-',dir=repo));folder.chmod(0o700)
    plan=dict(model='HILEGA_APPROVABLE_CLOSED_ROLLOUT_V1',repo=str(repo),stage=str(stage),files=entries,
        application_db=str(paths[APP]),adapter_db=str(paths[ADAPTER]),environment_pins=environment_pins,
        previous_bridge_run_hash=sha(previous_run.encode()),tool_manifest_sha256=sha(regular(package/'MANIFEST.json')),
        scope='CLOSED_PREPARATION_HOOK_ONLY_NO_EXECUTION_FACTORY',services_observed=states,
        production_execution_enabled=False,production_ready=False)
    save(folder/'PLAN.json',plan);digest=sha(regular(folder/'PLAN.json'))
    env=dict(os.environ);env['PYTHONPATH']=str(package)
    with tempfile.TemporaryDirectory(prefix='hilega-rollout-test-results-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',str(package/'test_rollout.py'),'-q','--junitxml='+str(junit)],cwd=repo,env=env).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(repo/n))==d for n,d in pins.items()) and all(sha(regular(package/n))==d for n,d in own.items())
    passed=code==0 and len(cases)==12 and failed==skipped==0 and unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='APPROVABLE_CLOSED_HOOK_ROLLOUT_CHECK',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,plan=str(folder/'PLAN.json'),plan_sha256=digest,
        prior_integration_cases_passed=212,full_regression_reexecuted=False,pinned_sources_unchanged=unchanged,
        live_database_inspected=True,actual_services_stopped=False,real_backups_created=False,new_release_approved=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False,runtime_deployed=False,production_ready=False)
    save(folder/'CHECK-VALIDATION.json',report);save(package/'VM-VALIDATION.json',report)
    print(json.dumps(report,indent=2));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
