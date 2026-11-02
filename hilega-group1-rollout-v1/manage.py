"""Default checks only. Closed maintenance requires exact prepared plan approval."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from assembly import regular,verify,need
from maintenance_primitives import UNITS,Systemd,sha,save,require_empty_closed_baseline
from rollout import TARGET,wrapper,apply,start,hold,rollback,bound_inputs,check_plan,read_health,wait_health
from rehearse import verify_runtime_payload
from supervisor_review import supervisor_review

OLD_PLAN_SHA='55ba58b26771b81ade1511e0b9f3324767fbc6768c2e2fa4d6ee3e6acbad4965'


def old_checkpoint(folder,repo):
    r=subprocess.run([sys.executable,str(folder/'checkpoint.py'),'--repo',str(repo),
        '--plan',str(repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json'),
        '--compatibility-review',str(repo/'hilega-reference-compatibility-2jkluc07')],cwd=repo)
    need(r.returncode==0,'CURRENT_CLOSED_BASELINE_REQUIRES_REVIEW')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--candidate-review',type=Path);parser.add_argument('--integration',action='store_true')
    parser.add_argument('--action',choices=('check','apply','start','hold','rollback','status'),default='check')
    parser.add_argument('--plan',type=Path);parser.add_argument('--approve-plan-sha256');args=parser.parse_args()
    repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(regular(folder/'MANIFEST.json'));pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for n,d in own.items():need(sha(regular(folder/n))==d,'GROUP1_ROLLOUT_TOOL_CHANGED')
    for n,d in pins.items():need(sha(regular(repo/n))==d,'VERIFIED_GROUP1_TOOLS_CHANGED')
    if args.action!='check':
        need(args.plan is not None and args.approve_plan_sha256 is not None,'EXACT_PLAN_AND_DIGEST_REQUIRED')
        path=args.plan.absolute();raw=regular(path);need(sha(raw)==args.approve_plan_sha256,'EXACT_PLAN_APPROVAL_DIGEST_REQUIRED')
        plan=json.loads(raw);review=path.parent
        need(path.name=='PLAN.json' and review.parent==repo and review.name.startswith('hilega-group1-rollout-plan-'),'EXACT_GROUP1_PLAN_FOLDER_REQUIRED')
        need(plan['repo']==str(repo) and plan['tool_manifest_sha256']==sha(regular(folder/'MANIFEST.json')),'PLAN_TOOL_OR_REPOSITORY_CHANGED')
        check=json.loads(regular(review/'CHECK-VALIDATION.json'))
        need(check['status']=='PASS_TARGETED_ONLY' and check['plan_sha256']==args.approve_plan_sha256,'PASSING_EXACT_PLAN_CHECK_REQUIRED')
        need(check['closed_release_scope_regression_reexecuted'] is True,'CLOSED_RELEASE_SCOPE_INTEGRATION_REQUIRED_BEFORE_MAINTENANCE')
        fd=os.open(repo/'.hilega-closed-rollout.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(fd);need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_SHARED_MAINTENANCE_LOCK_REQUIRED')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);check_plan(plan);bound_inputs(plan);manager=Systemd()
        if args.action=='apply':
            verify_runtime_payload(Path(plan['source_bundle']))
            save(review/'EXPLICIT-CLOSED-RELEASE-APPROVAL.json',dict(plan_sha256=args.approve_plan_sha256,
                scope='CLOSED_PREPARATION_BUNDLE_ONLY_NO_EXECUTION_FACTORY',production_execution_enabled=False))
            result=apply(plan,review,manager)
        elif args.action=='start':result=start(plan,review,manager)
        elif args.action=='hold':result=hold(plan,review,manager)
        elif args.action=='rollback':result=rollback(plan,review,manager)
        else:
            tx=json.loads(regular(review/'TRANSACTION.json'))
            expected=plan['old_worker_sha256'] if tx['phase']=='ROLLED_BACK_RUNNING' else plan['new_worker_sha256']
            need(sha(regular(repo/TARGET))==expected,'STATUS_WORKER_HASH_CHANGED')
            wait_health(Path(plan['application_db']),'STATUS_OBSERVATION',manager,[u for u in UNITS if tx['before'][u]['active']=='active'],timeout=35)
            require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']));result=tx
        print(json.dumps(dict(phase=result['phase'],production_execution_enabled=False,production_ready=False),indent=2));return 0
    old_checkpoint(folder,repo)
    candidate=args.candidate_review.absolute() if args.candidate_review else Path(json.loads(regular(repo/'hilega-group1-closed-runtime-v4/VM-VALIDATION.json'))['review_folder'])
    need(candidate.parent==repo and candidate.name.startswith('hilega-group1-review-'),'EXPLICIT_GROUP1_CANDIDATE_REVIEW_REQUIRED')
    managed=json.loads(regular(candidate/'MANAGED-REHEARSAL.json'))
    need(managed['status']=='GROUP1_MANAGED_DISPOSABLE_WORKER_PASS' and managed['isolated_managed_startup_and_restart_verified'] is True,
        'ACTUAL_MANAGED_DISPOSABLE_WORKER_PASS_REQUIRED')
    source=candidate/'release';manifest_raw=regular(source/'RELEASE-MANIFEST.json');manifest=json.loads(manifest_raw);verify(source,manifest);verify_runtime_payload(source)
    if args.integration:
        r=subprocess.run([sys.executable,str(repo/'hilega-group1-closed-runtime-v4/manage.py'),'--repo',str(repo),
            '--integration','--reuse-wheel-review',str(candidate)],cwd=repo)
        need(r.returncode==0,'GROUP1_COMBINED_INTEGRATION_REQUIRES_REVIEW')
        combined=json.loads(regular(repo/'hilega-group1-closed-runtime-v4/VM-VALIDATION.json'))
        need(combined['status']=='PASS_TARGETED_ONLY' and combined['collected_cases']==304,'CURRENT_304_CASE_PASS_REQUIRED')
        tested=json.loads(regular(Path(combined['release_folder'])/'RELEASE-MANIFEST.json'))
        need(tested['files']==manifest['files'],'MANAGED_CANDIDATE_DIFFERS_FROM_INTEGRATION_ARTIFACT')
    supervisor,_=supervisor_review(repo,Path.home());need(supervisor['approval_hashes_match'],'SUPERVISOR_APPROVAL_BINDINGS_CHANGED')
    old_plan_path=repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json';old_raw=regular(old_plan_path)
    need(sha(old_raw)==OLD_PLAN_SHA,'EXACT_PREVIOUS_CLOSED_PLAN_REQUIRED');previous=json.loads(old_raw)
    home=Path.home()/'hilega-persistent-supervision-stage-v1';config=home/'config-private.json'
    need(previous['environment_pins']==dict(configuration_sha256=sha(regular(config)),environment_sha256=sha(regular(repo/'.env'))),'APPROVED_STARTUP_ENVIRONMENT_CHANGED')
    app,adapter=Path(previous['application_db']),Path(previous['adapter_db']);require_empty_closed_baseline(app,adapter)
    bindings={str(p):sha(regular(p)) for p in [home/'runner.py',config,home/'MIGRATION_APPROVED.json',repo/'.env',
        repo/'backend/market_lab/hilega_preparation_runtime_v1/source.py',repo/'backend/market_lab/hilega_exclusive_closed_route_v1.py',
        repo/'backend/market_lab/hilega_execution_port_v1/adapter.py',repo/'hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py',
        repo/'hilega-operational-lifecycle-tools-6cexrur_/manifest.json',repo/'hilega-operational-lifecycle-tools-6cexrur_/cli.py']}
    release_digest=sha(manifest_raw);destination=repo/'data/runtime/hilega-closed-releases'/release_digest
    old_worker=regular(repo/TARGET);manager=Systemd();states={u:manager.state(u) for u in UNITS}
    need(all(s['active']=='active' and s['pid']>0 for s in states.values()),'ALL_SIX_SERVICES_REQUIRED_FOR_PLAN')
    review=Path(tempfile.mkdtemp(prefix='hilega-group1-rollout-plan-',dir=repo));review.chmod(0o700)
    plan=dict(model='HILEGA_GROUP1_EXACT_CLOSED_ROLLOUT_V1',repo=str(repo),source_bundle=str(source),destination=str(destination),
        release_manifest_sha256=release_digest,old_worker_sha256=sha(old_worker),new_worker_sha256=sha(wrapper(destination,release_digest)),
        worker_mode=stat.S_IMODE((repo/TARGET).stat().st_mode),application_db=str(app),adapter_db=str(adapter),bindings=bindings,
        tool_manifest_sha256=sha(regular(folder/'MANIFEST.json')),services_observed=states,
        scope='ONE_WORKER_WRAPPER_AND_IMMUTABLE_CLOSED_BUNDLE_NO_FACTORY_OR_OWNER',
        supervisor_configuration_modified=False,companion_sources_modified=False,automatic_database_restore=False,
        all_six_services_stopped_during_apply=True,new_release_approved=False,production_execution_enabled=False,production_ready=False)
    save(review/'PLAN.json',plan);digest=sha(regular(review/'PLAN.json'));(review/'worker-wrapper.py').write_bytes(wrapper(destination,release_digest))
    compile((review/'worker-wrapper.py').read_bytes(),'worker-wrapper.py','exec')
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_rollout.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items()) and all(sha(regular(repo/n))==d for n,d in pins.items())
    bound_inputs(plan);need(sha(regular(repo/TARGET))==plan['old_worker_sha256'],'INSTALLED_WORKER_CHANGED_DURING_CHECK')
    passed=code==0 and len(cases)==10 and failed==skipped==0 and unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='GROUP1_EXACT_CLOSED_BUNDLE_ROLLOUT_CHECK',
        collected_cases=len(cases)+(304 if args.integration else 0),new_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        closed_release_scope_regression_reexecuted=args.integration,full_repository_regression_reexecuted=False,
        prior_integration_cases_passed=288,prior_group1_targeted_cases_passed=16,plan=str(review/'PLAN.json'),plan_sha256=digest,
        candidate_matches_managed_rehearsal=True,immutable_bundle_and_wrapper_plan_created=True,
        existing_supervisor_and_companion_bindings_pinned=True,supervisor_configuration_modified=False,
        closed_apply_ready=passed and args.integration,new_release_approved=False,real_backups_created=False,
        application_services_changed=False,installed_sources_modified=False,controller_resumed=False,
        execution_factory_configured=False,live_database_enrolled=False,production_execution_enabled=False,production_ready=False)
    save(review/'CHECK-VALIDATION.json',report);save(folder/'VM-VALIDATION.json',report);print(json.dumps(report,indent=2));print('Report:',folder/'VM-VALIDATION.json')
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
