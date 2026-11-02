"""Prepare or execute an exact controlled closed-worker rollback/reinstall cycle."""
import argparse
from contextlib import closing
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from cycle import regular,sha,need,validate_receipt,copy_plan,steps,perform


def save(path,value):
    data=(json.dumps(value,indent=2)+'\n').encode();temp=path.with_name(path.name+'.new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)


def load_original_tool(repo,plan):
    folder=repo/'hilega-group1-rollout-v1';raw=regular(folder/'MANIFEST.json')
    need(sha(raw)==plan['tool_manifest_sha256'],'ORIGINAL_ROLLOUT_TOOL_MANIFEST_CHANGED')
    for n,d in json.loads(raw).items():need(sha(regular(folder/n))==d,'ORIGINAL_ROLLOUT_TOOL_CHANGED')
    sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location('verified_group1_rollout',folder/'rollout.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.check_plan(plan);module.bound_inputs(plan)
    return folder,module


def invoke(tool,repo,plan,digest,action,log_folder,label):
    command=[sys.executable,str(tool/'manage.py'),'--repo',str(repo),'--action',action,
        '--plan',str(plan),'--approve-plan-sha256',digest]
    r=subprocess.run(command,cwd=repo,capture_output=True,text=True,timeout=240)
    save(log_folder/(label+'.json'),dict(action=action,plan=str(plan),exit_code=r.returncode,
        stdout=r.stdout[-6000:],stderr=r.stderr[-6000:]))
    need(r.returncode==0,'CLOSED_MAINTENANCE_ACTION_FAILED: '+action+'; inspect '+str(log_folder/(label+'.json')))
    return json.loads(r.stdout)


def baseline(roll,plan):
    roll.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    with closing(sqlite3.connect(Path(plan['application_db']).as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        row=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()
        sequence=json.loads(row[0])['sequence'] if row else None
        h=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0]);db.rollback()
    return dict(controller_paused=c['mode']=='PAUSED',source_sequence=sequence,
        lease_fingerprint=sha(str(h.get('run_id')).encode()),lifecycle_empty=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--action',choices=('prepare','execute'),default='prepare')
    p.add_argument('--original-plan',type=Path);p.add_argument('--approved-plan-sha256')
    p.add_argument('--cycle-plan',type=Path);p.add_argument('--approve-cycle-sha256');args=p.parse_args()
    repo=args.repo.resolve();folder=Path(__file__).resolve().parent;own=json.loads(regular(folder/'MANIFEST.json'))
    for n,d in own.items():need(sha(regular(folder/n))==d,'ROLLBACK_CYCLE_TOOL_CHANGED')
    for n,d in json.loads(regular(folder/'BASELINE_PINS.json')).items():need(sha(regular(repo/n))==d,'PRIOR_ROLLOUT_PACKAGE_CHANGED')
    if args.action=='execute':
        need(args.cycle_plan is not None and args.approve_cycle_sha256 is not None,'EXACT_CYCLE_PLAN_APPROVAL_REQUIRED')
        cycle_path=args.cycle_plan.absolute();raw=regular(cycle_path);need(sha(raw)==args.approve_cycle_sha256,'CYCLE_PLAN_DIGEST_CHANGED')
        cp=json.loads(raw);review=cycle_path.parent
        need(review.parent==repo and review.name.startswith('hilega-group1-rollback-cycle-review-') and cycle_path.name=='CYCLE-PLAN.json','EXACT_CYCLE_PLAN_FOLDER_REQUIRED')
        need(cp['repo']==str(repo) and cp['scope']=='ROLLBACK_OLD_CLOSED_WORKER_THEN_RESTORE_IDENTICAL_APPROVED_CANDIDATE'
            and cp['tool_manifest_sha256']==sha(regular(folder/'MANIFEST.json')),'CYCLE_SCOPE_OR_TOOL_CHANGED')
        check=json.loads(regular(review/'CHECK-VALIDATION.json'))
        need(check['status']=='PASS_TARGETED_ONLY' and check['cycle_plan_sha256']==args.approve_cycle_sha256,'PASSING_CYCLE_PLAN_CHECK_REQUIRED')
        original=Path(cp['original_plan']);new=Path(cp['reinstall_plan']);digest=cp['original_plan_sha256']
        need(original.parent.parent==repo and new.parent.parent==repo and new.parent.name.startswith('hilega-group1-rollout-plan-'),'EXACT_EXISTING_ROLLOUT_PLAN_FOLDERS_REQUIRED')
        need(sha(regular(original))==digest and regular(new)==regular(original),'ORIGINAL_OR_REINSTALL_PLAN_CHANGED')
        need(sha(regular(original.parent/'CHECK-VALIDATION.json'))==cp['original_validation_sha256']
            and regular(new.parent/'CHECK-VALIDATION.json')==regular(original.parent/'CHECK-VALIDATION.json'),'REUSED_VALIDATION_CHANGED')
        for name,d in cp['backup_hashes'].items():need(sha(regular(Path(name)))==d,'REAL_BACKUP_CHANGED')
        need(sha(regular(original.parent/'TRANSACTION.json'))==cp['original_transaction_sha256'],'ORIGINAL_DEPLOYMENT_PHASE_CHANGED')
        need(not (new.parent/'TRANSACTION.json').exists() and not (review/'CYCLE-TRANSACTION.json').exists(),'CYCLE_ALREADY_STARTED_REQUIRES_INSPECTION')
        plan=json.loads(regular(original));tool,roll=load_original_tool(repo,plan)
        need(json.loads(regular(original.parent/'TRANSACTION.json'))['phase']=='CLOSED_BUNDLE_RUNNING','CURRENT_CLOSED_BUNDLE_MUST_BE_RUNNING')
        fd=os.open(repo/'.hilega-group1-rollback-cycle.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        need(sha(regular(repo/roll.TARGET))==plan['new_worker_sha256'],'CURRENT_CANDIDATE_WRAPPER_CHANGED')
        invoke(tool,repo,original,digest,'status',review,'initial-status')
        before=baseline(roll,plan);observations={}
        sequence=steps(original,new)
        def call(path,action):
            index=call.index;call.index+=1
            print('Cycle step',index+1,'of',len(sequence),':',action,flush=True)
            return invoke(tool,repo,path,digest,action,review,'step-'+str(index+1))
        call.index=0
        def observe(index,result):
            if index in {3,6}:
                expected=plan['old_worker_sha256'] if index==3 else plan['new_worker_sha256']
                need(sha(regular(repo/roll.TARGET))==expected,'VERIFIED_WORKER_HASH_NOT_RESTORED')
                observations['old' if index==3 else 'candidate']=baseline(roll,plan)
        try:transaction=perform(sequence,call,lambda state:save(review/'CYCLE-TRANSACTION.json',state),observe)
        except BaseException as exc:
            save(review/'RESULT.json',dict(status='CYCLE_STOPPED_REVIEW_REQUIRED',reason=str(exc),
                original_plan=str(original),reinstall_plan=str(new),automatic_recovery_attempted=False,
                automatic_database_restore=False,production_execution_enabled=False))
            raise
        after=observations['candidate']
        need(before['source_sequence'] is None or after['source_sequence']>=before['source_sequence'],'SOURCE_CURSOR_REGRESSION_REQUIRES_REVIEW')
        need(len({before['lease_fingerprint'],observations['old']['lease_fingerprint'],after['lease_fingerprint']})==3,'DISTINCT_ROLLBACK_AND_RESTORE_LEASES_REQUIRED')
        report=dict(status='GROUP1_ROLLBACK_AND_CANDIDATE_RESTORE_PASS',group1_closed_worker_deployment_complete=True,
            actual_old_worker_restored_and_running=True,identical_candidate_reinstalled_and_running=True,
            verified_maintenance_steps=len(transaction['completed_steps']),controller_remains_paused=True,
            lifecycle_tables_remain_empty=True,source_cursor_not_rewound=True,automatic_database_restore=False,
            retained_original_and_reinstall_backups=True,active_plan=str(new),active_plan_sha256=digest,
            original_plan=str(original),execution_factory_configured=False,live_database_enrolled=False,
            full_repository_regression_reexecuted=False,full_production_readiness_certified=False,
            production_execution_enabled=False,production_ready=False)
        save(review/'RESULT.json',report);save(folder/'VM-VALIDATION.json',report);print(json.dumps(report,indent=2));return 0
    need(args.original_plan is not None and args.approved_plan_sha256 is not None,'EXISTING_APPROVED_PLAN_REQUIRED')
    original=args.original_plan.absolute();raw=regular(original);digest=args.approved_plan_sha256
    need(sha(raw)==digest,'EXISTING_APPROVED_PLAN_DIGEST_CHANGED');plan=json.loads(raw)
    need(original.parent.parent==repo and original.parent.name.startswith('hilega-group1-rollout-plan-') and original.name=='PLAN.json','EXACT_EXISTING_PLAN_REQUIRED')
    validate_receipt(regular(original.parent/'CHECK-VALIDATION.json'),digest);tool,roll=load_original_tool(repo,plan)
    need(json.loads(regular(original.parent/'TRANSACTION.json'))['phase']=='CLOSED_BUNDLE_RUNNING','RUNNING_CLOSED_BUNDLE_REQUIRED')
    review=Path(tempfile.mkdtemp(prefix='hilega-group1-rollback-cycle-review-',dir=repo));review.chmod(0o700)
    invoke(tool,repo,original,digest,'status',review,'preparation-status');baseline(roll,plan)
    backup=original.parent/'backups';backup_hashes={str(p):sha(regular(p)) for p in [backup/'worker.old',backup/'application.sqlite',backup/'adapter.sqlite']}
    need(backup_hashes[str(backup/'worker.old')]==plan['old_worker_sha256'],'VERIFIED_OLD_WORKER_BACKUP_REQUIRED')
    for name in ('application.sqlite','adapter.sqlite'):
        with closing(sqlite3.connect((backup/name).as_uri()+'?mode=ro',uri=True)) as db:need(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','RETAINED_DATABASE_BACKUP_INVALID')
    reinstall=Path(tempfile.mkdtemp(prefix='hilega-group1-rollout-plan-',dir=repo));reinstall.chmod(0o700)
    copy_plan(original,reinstall,digest)
    cp=dict(scope='ROLLBACK_OLD_CLOSED_WORKER_THEN_RESTORE_IDENTICAL_APPROVED_CANDIDATE',repo=str(repo),
        original_plan=str(original),original_plan_sha256=digest,reinstall_plan=str(reinstall/'PLAN.json'),
        original_validation_sha256=sha(regular(original.parent/'CHECK-VALIDATION.json')),
        original_transaction_sha256=sha(regular(original.parent/'TRANSACTION.json')),backup_hashes=backup_hashes,
        tool_manifest_sha256=sha(regular(folder/'MANIFEST.json')),service_stop_start_windows=2,
        automatic_database_restore=False,controller_resume_permitted=False,production_execution_enabled=False)
    path=review/'CYCLE-PLAN.json';save(path,cp);cycle_digest=sha(regular(path))
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_cycle.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items())
    passed=code==0 and len(cases)==8 and failed==skipped==0 and unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='GROUP1_CONTROLLED_ROLLBACK_AND_IDENTICAL_RESTORE_PREPARATION',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,prior_closed_release_cases_passed=314,
        prior_regression_reexecuted=False,cycle_plan=str(path),cycle_plan_sha256=cycle_digest,
        unchanged_approved_plan_reused=True,validation_receipt_copied_byte_for_byte=True,existing_backups_verified=True,
        actual_cycle_executed=False,application_services_changed=False,installed_sources_modified=False,
        automatic_database_restore=False,production_execution_enabled=False,production_ready=False)
    save(review/'CHECK-VALIDATION.json',report);save(folder/'VM-VALIDATION.json',report);print(json.dumps(report,indent=2));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
