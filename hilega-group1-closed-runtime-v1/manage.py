"""One Group 1 entry point: prepare, integration and approved disposable managed rehearsal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from assembly import regular,verify,need
from group1 import expand_worker,launcher_text,proposal
from rehearse import run
from supervisor_review import supervisor_review


def sha(raw):return hashlib.sha256(raw).hexdigest()


def health(folder,repo):
    r=subprocess.run([sys.executable,str(folder/'checkpoint.py'),'--repo',str(repo),
        '--plan',str(repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json'),
        '--compatibility-review',str(repo/'hilega-reference-compatibility-2jkluc07')],cwd=repo)
    need(r.returncode==0,'CURRENT_CLOSED_HEALTH_REQUIRES_REVIEW')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--integration',action='store_true');p.add_argument('--action',choices=('prepare','managed-rehearse'),default='prepare')
    p.add_argument('--plan',type=Path);p.add_argument('--approve-plan-sha256');args=p.parse_args()
    repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(regular(folder/'MANIFEST.json'));pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for n,d in own.items():need(sha(regular(folder/n))==d,'GROUP1_PACKAGE_CHANGED')
    for n,d in pins.items():need(sha(regular(repo/n))==d,'PRIOR_REGISTRATION_TOOLS_CHANGED')
    if args.action=='managed-rehearse':
        need(args.plan is not None and args.approve_plan_sha256 is not None,'EXACT_REHEARSAL_PLAN_APPROVAL_REQUIRED')
        raw=regular(args.plan.absolute());need(sha(raw)==args.approve_plan_sha256,'REHEARSAL_PLAN_DIGEST_CHANGED');plan=json.loads(raw)
        need(plan['scope']=='ACTUAL_CLOSED_WORKER_DISPOSABLE_MANAGED_REHEARSAL' and plan['repo']==str(repo)
            and plan['tool_manifest_sha256']==sha(regular(folder/'MANIFEST.json')),'EXACT_GROUP1_REHEARSAL_PLAN_REQUIRED')
        release=Path(plan['release_folder']);review=release.parent
        need(review.parent==repo and review.name.startswith('hilega-group1-review-') and release.name=='release','EXACT_GROUP1_RELEASE_REQUIRED')
        need(plan['python']==sys.executable and plan['output']==str(review/'managed-disposable-state'),'FIXED_REHEARSAL_ARGUMENTS_REQUIRED')
        manifest_raw=regular(release/'RELEASE-MANIFEST.json');need(sha(manifest_raw)==plan['release_manifest_sha256'],'REHEARSAL_RELEASE_CHANGED')
        verify(release,json.loads(manifest_raw));unit=plan['unit']
        need(unit.startswith('hilega-group1-worker-rehearsal-') and unit.endswith('.service')
            and all(c.isalnum() or c in '-.' for c in unit),'ISOLATED_GROUP1_UNIT_REQUIRED')
        health(folder,repo)
        command=['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot',
            '--property=NoNewPrivileges=yes','--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=55',
            '--working-directory='+str(review),sys.executable,'-B',str(release/'rehearse.py'),
            '--release',str(release),'--output',plan['output']]
        result=subprocess.run(command,cwd=repo,capture_output=True,text=True,timeout=60)
        output=Path(plan['output']);receipt=json.loads(regular(output/'RESULT.json')) if (output/'RESULT.json').is_file() else {}
        passed=result.returncode==0 and receipt.get('status')=='ACTUAL_DISPOSABLE_CLOSED_WORKER_RESTART_PASS'
        report=dict(status='GROUP1_MANAGED_DISPOSABLE_WORKER_PASS' if passed else 'GROUP1_MANAGED_REHEARSAL_REQUIRES_REVIEW',
            command_exit_code=result.returncode,actual_candidate_worker_executed=True if passed else None,
            isolated_managed_startup_and_restart_verified=passed,application_service_control_commands_issued=False,
            disposable_databases_only=True,production_worker_deployed=False,group1_complete=False,
            production_execution_enabled=False,production_ready=False)
        (review/'MANAGED-REHEARSAL.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        if not passed:print(result.stderr[-4000:])
        return 0 if passed else 1
    previous=repo/'hilega-worker-registration-v2';prior=json.loads(regular(previous/'VM-VALIDATION.json'))
    need(prior['status']=='PASS_TARGETED_ONLY' and prior['collected_cases']==288 and prior['broader_integration_reexecuted'] is True,'PRIOR_288_CASE_INTEGRATION_REQUIRED')
    prior_probe=Path(prior['review_folder'])/'MANAGED-PROBE.json';probe_raw=regular(prior_probe)
    need(json.loads(probe_raw)['status']=='MANAGED_CLOSED_PROBE_PASS','PRIOR_MANAGED_CLOSED_PROBE_REQUIRED')
    if args.integration:
        r=subprocess.run([sys.executable,str(previous/'apply_and_test.py'),'--repo',str(repo),'--integration'],cwd=repo)
        need(r.returncode==0,'PRIOR_INTEGRATION_REQUIRES_REVIEW');prior=json.loads(regular(previous/'VM-VALIDATION.json'))
        need(prior['collected_cases']==288 and prior['status']=='PASS_TARGETED_ONLY','CURRENT_288_CASE_PASS_REQUIRED')
    else:health(folder,repo)
    old=Path(prior['release_folder']);old_manifest=json.loads(regular(old/'RELEASE-MANIFEST.json'));verify(old,old_manifest)
    review=Path(tempfile.mkdtemp(prefix='hilega-group1-review-',dir=repo));release=review/'release';release.mkdir(mode=0o700)
    for n,d in old_manifest['files'].items():
        rel=Path(n);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_BUNDLE_INPUT_REQUIRED')
        data=regular(old/rel);need(sha(data)==d,'PREVIOUS_RELEASE_CHANGED');target=release/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    graph=expand_worker(repo,release)
    (release/'closed_worker_launcher.py').write_text(launcher_text());(release/'rehearse.py').write_bytes(regular(folder/'rehearse.py'))
    files={p.relative_to(release).as_posix():sha(p.read_bytes()) for p in release.rglob('*') if p.is_file()}
    manifest=dict(model='HILEGA_GROUP1_CLOSED_SOURCE_WORKER_BUNDLE_V1',files=files,
        source_worker_static_imports_bundled=True,execution_factory_configured=False,production_execution_enabled=False)
    (release/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for source in release.rglob('*.py'):compile(source.read_bytes(),str(source),'exec')
    verify(release,manifest)
    try:rehearsal=run(release,review/'direct-disposable-state')
    except Exception as exc:
        (review/'PREPARATION-FAILURE.json').write_text(json.dumps(dict(status='GROUP1_REQUIRES_REVIEW',reason=str(exc),
            installed_sources_modified=False,application_services_changed=False,production_execution_enabled=False),indent=2)+'\n')
        raise
    verify(release,manifest);supervisor,_=supervisor_review(repo,Path.home())
    deployment=proposal(repo,release,sha(regular(release/'RELEASE-MANIFEST.json')),supervisor)
    rollout_bytes=(json.dumps(deployment,indent=2)+'\n').encode();(review/'DEPLOYMENT-PROPOSAL.json').write_bytes(rollout_bytes)
    (review/'WORKER-IMPORT-GRAPH.json').write_text(json.dumps(graph,indent=2)+'\n')
    (review/'SUPERVISOR-REVIEW.json').write_text(json.dumps(supervisor,indent=2)+'\n')
    (review/'PRIOR-MANAGED-PROBE.json').write_bytes(probe_raw)
    plan=dict(scope='ACTUAL_CLOSED_WORKER_DISPOSABLE_MANAGED_REHEARSAL',repo=str(repo),release_folder=str(release),
        release_manifest_sha256=sha(regular(release/'RELEASE-MANIFEST.json')),python=sys.executable,
        unit='hilega-group1-worker-rehearsal-'+uuid.uuid4().hex[:12]+'.service',output=str(review/'managed-disposable-state'),
        tool_manifest_sha256=sha(regular(folder/'MANIFEST.json')),application_services_modified=False,
        live_database_opened=False,credentials_provided=False,production_execution_enabled=False)
    plan_path=review/'MANAGED-REHEARSAL-PLAN.json';plan_path.write_text(json.dumps(plan,indent=2)+'\n')
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_group1.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items()) and all(sha(regular(repo/n))==d for n,d in pins.items())
    verify(release,manifest);verify(old,old_manifest)
    passed=code==0 and len(cases)==8 and failed==skipped==0 and unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='GROUP1_CLOSED_RUNTIME_ASSEMBLY_AND_ACTUAL_DISPOSABLE_WORKER_REHEARSAL',
        collected_cases=len(cases)+(288 if args.integration else 0),new_cases=len(cases),failed=failed,skipped=skipped,
        pytest_exit_code=code,prior_integration_cases_passed=288,broader_integration_reexecuted=args.integration,
        full_regression_reexecuted=False,actual_candidate_worker_executed=True,disposable_worker_startup_and_restart_verified=True,
        empty_journal_only=True,fresh_signal_preparation_verified=False,source_worker_static_imports_bundled=True,
        full_application_service_closure_verified=False,existing_supervisor_bindings_match=supervisor['approval_hashes_match'],
        deployment_and_rollback_proposal_created=True,new_release_approved=False,real_backups_created=False,
        managed_rehearsal_plan_created=True,managed_rehearsal_started=False,production_worker_deployed=False,
        group1_complete=False,review_folder=str(review),release_folder=str(release),
        managed_rehearsal_plan=str(plan_path),managed_rehearsal_plan_sha256=sha(regular(plan_path)),
        installed_sources_modified=False,application_services_changed=False,live_database_opened_by_rehearsal=False,
        controller_resumed=False,live_database_enrolled=False,production_execution_enabled=False,production_ready=False,
        remaining_group1=deployment['required_before_apply'])
    dest=folder/'VM-VALIDATION.json';dest.write_text(json.dumps(report,indent=2)+'\n')
    (review/'STATUS.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));print('Report:',dest)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
