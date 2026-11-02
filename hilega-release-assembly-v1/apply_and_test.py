"""Assemble and rehearse a closed candidate release. No service or installed-code changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from assembly import assemble,regular,verify,disposable_rollback,need
from supervisor_review import supervisor_review


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true');args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(regular(folder/'MANIFEST.json'));pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for n,d in own.items():need(sha(regular(folder/n))==d,'ASSEMBLY_PACKAGE_CHANGED')
    for n,d in pins.items():need(sha(regular(repo/n))==d,'PREVIOUS_LOCK_TOOLS_CHANGED')
    previous=repo/'hilega-dependency-lock-v1';prior=json.loads(regular(previous/'VM-VALIDATION.json'))
    need(prior['status']=='PASS_TARGETED_ONLY' and prior['collected_cases']==268 and prior['broader_integration_reexecuted'] is True,'PRIOR_268_CASE_INTEGRATION_REQUIRED')
    previous_review=Path(prior['review_folder']);lock=json.loads(regular(previous_review/'WHEEL-LOCK.json'))
    wheel=previous_review/'wheels'/lock['wheel_filename']
    if args.integration:
        code=subprocess.run([sys.executable,str(previous/'apply_and_test.py'),'--repo',str(repo),'--integration','--wheel',str(wheel)],cwd=repo).returncode
        need(code==0,'PREVIOUS_INTEGRATION_REQUIRES_REVIEW')
        prior=json.loads(regular(previous/'VM-VALIDATION.json'));need(prior['collected_cases']==268 and prior['status']=='PASS_TARGETED_ONLY','CURRENT_268_CASE_PASS_REQUIRED')
        previous_review=Path(prior['review_folder']);lock=json.loads(regular(previous_review/'WHEEL-LOCK.json'));wheel=previous_review/'wheels'/lock['wheel_filename']
    else:
        code=subprocess.run([sys.executable,str(folder/'checkpoint.py'),'--repo',str(repo),
            '--plan',str(repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json'),
            '--compatibility-review',str(repo/'hilega-reference-compatibility-2jkluc07')],cwd=repo).returncode
        need(code==0,'RUNNING_CLOSED_HEALTH_REQUIRES_REVIEW')
    supervisor,_=supervisor_review(repo,Path.home());need(supervisor['approval_hashes_match'],'SUPERVISOR_BINDINGS_REQUIRE_REVIEW')
    stage=Path(prior['stage']);manifest=json.loads(regular(previous_review/'STAGED-MANIFEST.json'))
    for n,d in manifest.items():
        rel=Path(n);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_STAGE_PATH_REQUIRED')
        need(sha(regular(stage/rel))==d,'PRIOR_STAGE_CHANGED')
    graph=json.loads(regular(previous_review/'TRANSITIVE-IMPORT-REVIEW.json'))
    dynamic_pins=json.loads(regular(previous/'DYNAMIC_PINS.json'))
    review=Path(tempfile.mkdtemp(prefix='hilega-release-assembly-review-',dir=repo));bundle=review/'release'
    release=assemble(repo,stage,graph,dynamic_pins,wheel,lock,bundle);verify(bundle,release)
    # Only an inert CLI is exercised; no application databases, secrets or session injection.
    environment={'PATH':os.defpath,'LANG':'C.UTF-8','PYTHONPATH':os.pathsep.join(map(str,[bundle/'runtime',bundle/'backend'])),
        'PYTHONDONTWRITEBYTECODE':'1','HOME':str(review)}
    startup=[]
    for attempt in range(2):
        r=subprocess.run([sys.executable,str(bundle/'runtime/closed_application_coordinator_v1.py'),'--once'],
            cwd=bundle,env=environment,capture_output=True,text=True,timeout=15)
        need(r.returncode==0,'CLOSED_BUNDLE_CLI_FAILED');value=json.loads(r.stdout)
        need(value['status']=='EXECUTION_COORDINATOR_CLOSED_IN_CODE' and value['application_database_opened'] is False
            and value['token_loaded'] is False and value['production_execution_enabled'] is False,'CLOSED_CLI_CONTRACT_CHANGED')
        startup.append(dict(attempt=attempt+1,status=value['status'],application_database_opened=False,token_loaded=False))
    verify(bundle,release);rollback=disposable_rollback(review)
    proposal=dict(scope='ASSEMBLED_CANDIDATE_RELEASE_REVIEW_ONLY',release_manifest_sha256=sha(regular(bundle/'RELEASE-MANIFEST.json')),
        old_supervisor_approval_bindings_match=True,new_release_approval_reconciled=False,
        current_supervisor_runner_sha256=sha(regular(Path.home()/'hilega-persistent-supervision-stage-v1/runner.py')),
        private_config_exported=False,live_apply_available=False,managed_service_rehearsal_completed=False,
        proposed_next_review=['EXPLICIT_WORKER_BOOTSTRAP_REGISTRATION_AND_EXISTING_STORE_ASSEMBLY',
            'NEW_RELEASE_AND_SUPERVISOR_APPROVAL_BINDINGS','COMPANION_PIN_CHAIN_IMPACT',
            'FULL_APPLICATION_SERVICE_DEPENDENCIES_AND_RELEASE_REGRESSION',
            'BROKER_AUTHORITY_FEES_CASH_AND_PARTIAL_FILL_POLICIES','FRESH_SEED_ENROLLMENT_AND_CONTROLLED_LIVE_APPROVAL'],
        installed_sources_modified=False,production_execution_enabled=False)
    for name,data in [('SUPERVISOR-REVIEW.json',supervisor),('CLOSED-STARTUP.json',startup),('ROLLBACK-REHEARSAL.json',rollback),('RELEASE-PROPOSAL.json',proposal)]:
        (review/name).write_text(json.dumps(data,indent=2)+'\n')
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_assembly.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items()) and all(sha(regular(repo/n))==d for n,d in pins.items())
    stage_ok=all(sha(regular(stage/n))==d for n,d in manifest.items());verify(bundle,release)
    passed=code==0 and len(cases)==8 and failed==skipped==0 and unchanged and stage_ok
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='ASSEMBLED_CLOSED_CANDIDATE_RELEASE_AND_SUPERVISOR_REVIEW',
        collected_cases=len(cases)+(268 if args.integration else 0),new_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        prior_integration_cases_passed=268,broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,
        candidate_release_assembled=True,release_manifest_verified=True,bundled_file_count=len(release['files']),
        bounded_closed_cli_startup_and_restart_verified=True,disposable_file_rollback_rehearsed=True,
        existing_supervisor_approval_bindings_match=True,new_release_approval_reconciled=False,
        actual_managed_startup_or_rollback_tested=False,full_application_service_closure_verified=False,
        dependency_manifest_fully_reconciled=False,release_folder=str(bundle),review_folder=str(review),
        pinned_sources_unchanged=unchanged,previous_stage_unchanged=stage_ok,
        installed_sources_modified=False,services_changed=False,packages_installed=False,
        runtime_registration_installed=False,controller_resumed=False,live_database_enrolled=False,
        production_authority_provisioned=False,actual_broker_network_validated=False,
        production_execution_enabled=False,production_ready=False)
    dest=folder/'VM-VALIDATION.json';dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));print('Report:',dest)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
