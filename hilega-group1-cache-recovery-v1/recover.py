"""Recover only the verified cache-blocked candidate reinstallation; original code/plan unchanged."""
import argparse
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from cache_repair import inventory,protect,need,sha


def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_RECOVERY_INPUT_REQUIRED')
    return p.read_bytes()


def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def snapshot(roll,plan):
    roll.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    with closing(sqlite3.connect(Path(plan['application_db']).as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        row=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
        health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
    return dict(sequence=row['sequence'],lease_hash=sha(str(health['run_id']).encode()))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--cycle-plan',type=Path,required=True);p.add_argument('--approved-cycle-sha256',required=True)
    p.add_argument('--recover',action='store_true');args=p.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(regular(folder/'MANIFEST.json'))
    for n,d in own.items():need(sha(regular(folder/n))==d,'CACHE_RECOVERY_PACKAGE_CHANGED')
    for n,d in json.loads(regular(folder/'BASELINE_PINS.json')).items():need(sha(regular(repo/n))==d,'ORIGINAL_APPROVED_TOOLS_CHANGED')
    need(args.cycle_plan.absolute().parent.parent==repo,'CYCLE_PLAN_REPOSITORY_CHANGED')
    raw=regular(args.cycle_plan.absolute());need(sha(raw)==args.approved_cycle_sha256,'EXACT_EXISTING_CYCLE_DIGEST_REQUIRED');cycle=json.loads(raw)
    need(cycle['repo']==str(repo) and cycle['scope']=='ROLLBACK_OLD_CLOSED_WORKER_THEN_RESTORE_IDENTICAL_APPROVED_CANDIDATE','EXACT_FAILED_CLOSED_CYCLE_REQUIRED')
    original=Path(cycle['original_plan']);reinstall=Path(cycle['reinstall_plan']);digest=cycle['original_plan_sha256']
    need(original.parent.parent==repo and reinstall.parent.parent==repo and original.name==reinstall.name=='PLAN.json','EXACT_PLAN_LOCATIONS_REQUIRED')
    plan_raw=regular(original);need(sha(plan_raw)==digest and regular(reinstall)==plan_raw,'UNCHANGED_APPROVED_PLAN_REQUIRED');plan=json.loads(plan_raw)
    need(not (reinstall.parent/'TRANSACTION.json').exists(),'REINSTALL_ALREADY_STARTED_REQUIRES_REVIEW')
    need(json.loads(regular(original.parent/'TRANSACTION.json'))['phase']=='ROLLED_BACK_RUNNING','OLD_CLOSED_WORKER_MUST_BE_RUNNING')
    validation=regular(original.parent/'CHECK-VALIDATION.json')
    need(sha(validation)==cycle['original_validation_sha256'] and regular(reinstall.parent/'CHECK-VALIDATION.json')==validation,'ORIGINAL_VALIDATION_RECEIPT_CHANGED')
    checked=json.loads(validation);need(checked['status']=='PASS_TARGETED_ONLY' and checked['closed_release_scope_regression_reexecuted'] is True,'PRIOR_314_CASE_CLOSED_VALIDATION_REQUIRED')
    for path,d in cycle['backup_hashes'].items():need(sha(regular(Path(path)))==d,'RETAINED_REAL_BACKUP_CHANGED')
    tool=repo/'hilega-group1-rollout-v1';tool_raw=regular(tool/'MANIFEST.json');need(sha(tool_raw)==plan['tool_manifest_sha256'],'ORIGINAL_ROLLOUT_MANIFEST_CHANGED')
    for n,d in json.loads(tool_raw).items():need(sha(regular(tool/n))==d,'ORIGINAL_ROLLOUT_CODE_CHANGED')
    sys.path.insert(0,str(tool));spec=importlib.util.spec_from_file_location('verified_rollout_for_cache_recovery',tool/'rollout.py')
    roll=importlib.util.module_from_spec(spec);spec.loader.exec_module(roll);roll.check_plan(plan);roll.bound_inputs(plan)
    need(sha(regular(repo/roll.TARGET))==plan['old_worker_sha256'],'OLD_WORKER_BYTES_NOT_RESTORED')
    root=Path(plan['destination']);manifest_raw=regular(root/'RELEASE-MANIFEST.json')
    need(sha(manifest_raw)==plan['release_manifest_sha256'],'INSTALLED_APPROVED_MANIFEST_CHANGED');manifest=json.loads(manifest_raw)
    extras=inventory(root,manifest)
    audit=Path(tempfile.mkdtemp(prefix='hilega-group1-cache-recovery-',dir=repo));audit.chmod(0o700)
    def invoke(path,action,label):
        r=subprocess.run([sys.executable,str(tool/'manage.py'),'--repo',str(repo),'--action',action,
            '--plan',str(path),'--approve-plan-sha256',digest],cwd=repo,capture_output=True,text=True,timeout=240)
        save(audit/(label+'.json'),dict(action=action,plan=str(path),exit_code=r.returncode,stdout=r.stdout[-6000:],stderr=r.stderr[-6000:]))
        need(r.returncode==0,'RECOVERY_ACTION_FAILED: '+action+'; inspect '+str(audit/(label+'.json')))
        return json.loads(r.stdout)
    invoke(original,'status','old-worker-status');before=snapshot(roll,plan)
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_cache_repair.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    need(code==0 and len(cases)==6 and failed==skipped==0,'CACHE_RECOVERY_TESTS_REQUIRE_REVIEW')
    if not args.recover:
        report=dict(status='CACHE_RECOVERY_CHECK_PASS',collected_cases=6,cache_file_count=len(extras),
            approved_files_match_manifest=True,application_services_changed=False,cache_files_moved=False,
            installed_file_bytes_modified=False,production_execution_enabled=False)
        save(audit/'CHECK.json',report);print(json.dumps(report,indent=2));return 0
    # Restore the already-approved candidate only; do not repeat the successful old-worker rollback.
    try:
        repair=protect(root,manifest,audit/'quarantined-cache');save(audit/'CACHE-REPAIR.json',repair)
        need(sha(regular(root/'RELEASE-MANIFEST.json'))==plan['release_manifest_sha256'],'MANIFEST_CHANGED_DURING_CACHE_REPAIR')
        roll.verify(root,manifest)
        save(audit/'RECOVERY-TRANSACTION.json',dict(phase='CACHE_QUARANTINED_BUNDLE_READ_ONLY',production_execution_enabled=False))
        for action,expected in [('apply','INSTALLED_SERVICES_STOPPED'),('start','CLOSED_BUNDLE_RUNNING'),('status','CLOSED_BUNDLE_RUNNING')]:
            print('Restoring approved candidate:',action,flush=True)
            result=invoke(reinstall,action,'candidate-'+action)
            need(result['phase']==expected and result['production_execution_enabled'] is False,'UNEXPECTED_CLOSED_RECOVERY_PHASE')
            save(audit/'RECOVERY-TRANSACTION.json',dict(phase=expected,production_execution_enabled=False))
        after=snapshot(roll,plan)
        need(after['sequence']>=before['sequence'] and after['lease_hash']!=before['lease_hash'],'CURSOR_OR_NEW_LEASE_REQUIRES_REVIEW')
        roll.verify(root,manifest);need(not inventory(root,manifest),'CACHE_REGENERATED_AFTER_START')
        report=dict(status='GROUP1_ROLLBACK_AND_READ_ONLY_CANDIDATE_RESTORE_PASS',group1_closed_worker_deployment_complete=True,
            actual_old_worker_rollback_verified=True,identical_candidate_reinstalled_and_running=True,
            cache_files_quarantined=len(repair['quarantined']),approved_manifest_and_source_bytes_unchanged=True,
            installed_bundle_read_only=True,cache_regeneration_after_start=False,
            collected_new_test_cases=6,prior_closed_release_cases_passed=314,prior_regression_reexecuted=False,
            controller_remains_paused=True,lifecycle_tables_remain_empty=True,source_cursor_not_rewound=True,
            automatic_database_restore=False,active_plan=str(reinstall),active_plan_sha256=digest,
            audit_folder=str(audit),execution_factory_configured=False,live_database_enrolled=False,
            full_repository_regression_reexecuted=False,production_execution_enabled=False,production_ready=False)
        save(audit/'RESULT.json',report);save(folder/'VM-VALIDATION.json',report);print(json.dumps(report,indent=2));return 0
    except BaseException as exc:
        save(audit/'RESULT.json',dict(status='RECOVERY_STOPPED_REVIEW_REQUIRED',reason=str(exc),
            active_reinstall_plan=str(reinstall),automatic_database_restore=False,production_execution_enabled=False))
        raise

if __name__=='__main__':raise SystemExit(main())
