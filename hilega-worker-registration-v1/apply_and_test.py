"""Prepare four-part closed worker registration review; optional exact-plan transient probe."""
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
from registration_tools import transform,worker_rollback,probe_command
from worker_registration_v1 import MODEL


def sha(raw):return hashlib.sha256(raw).hexdigest()


def checkpoint(folder,repo):
    r=subprocess.run([sys.executable,str(folder/'checkpoint.py'),'--repo',str(repo),
        '--plan',str(repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json'),
        '--compatibility-review',str(repo/'hilega-reference-compatibility-2jkluc07')],cwd=repo)
    need(r.returncode==0,'CLOSED_RUNNING_HEALTH_REQUIRES_REVIEW')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true');parser.add_argument('--action',choices=('prepare','probe'),default='prepare')
    parser.add_argument('--plan',type=Path);parser.add_argument('--approve-plan-sha256');args=parser.parse_args()
    repo=args.repo.resolve();folder=Path(__file__).resolve().parent;own=json.loads(regular(folder/'MANIFEST.json'))
    for n,d in own.items():need(sha(regular(folder/n))==d,'REGISTRATION_PACKAGE_CHANGED')
    for n,d in json.loads(regular(folder/'BASELINE_PINS.json')).items():need(sha(regular(repo/n))==d,'ASSEMBLY_TOOLS_CHANGED')
    if args.action=='probe':
        need(args.plan is not None and args.approve_plan_sha256 is not None,'EXACT_PROBE_PLAN_APPROVAL_REQUIRED')
        raw=regular(args.plan.absolute());need(sha(raw)==args.approve_plan_sha256,'EXACT_PROBE_PLAN_DIGEST_REQUIRED');plan=json.loads(raw)
        need(plan['repo']==str(repo) and plan['scope']=='DISPOSABLE_MANAGED_CLOSED_REGISTRATION_PROBE'
            and plan['tool_manifest_sha256']==sha(regular(folder/'MANIFEST.json')),'PROBE_PLAN_BINDING_CHANGED')
        release=Path(plan['release_folder']);need(release.parent.parent==repo and release.parent.name.startswith('hilega-worker-registration-review-'),
            'EXPLICIT_REVIEW_RELEASE_REQUIRED')
        need(plan['python']==sys.executable and plan['probe_script']==str(release/'probe.py')
            and plan['registration']==str(release/'CLOSED-REGISTRATION.json'),'FIXED_PROBE_COMMAND_REQUIRED')
        manifest_raw=regular(release/'RELEASE-MANIFEST.json');need(sha(manifest_raw)==plan['release_manifest_sha256'],'PROBE_RELEASE_CHANGED')
        verify(release,json.loads(manifest_raw));need(sha(regular(Path(plan['registration'])))==plan['registration_sha256'],'PUBLIC_REGISTRATION_CHANGED')
        checkpoint(folder,repo)
        result=subprocess.run(probe_command(plan),cwd=repo,capture_output=True,text=True,timeout=35)
        report=dict(status='MANAGED_CLOSED_PROBE_PASS' if result.returncode==0 else 'MANAGED_CLOSED_PROBE_REQUIRES_REVIEW',
            command_exit_code=result.returncode,disposable_managed_unit_start_requested=True,
            application_service_control_commands_issued=False,source_worker_executed=False,
            actual_worker_managed_startup_validated=False,live_database_opened_by_probe=False,
            production_execution_enabled=False,production_ready=False)
        (release.parent/'MANAGED-PROBE.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        if result.returncode:print(result.stderr[-2000:])
        return 0 if result.returncode==0 else 1
    previous=repo/'hilega-release-assembly-v1'
    if args.integration:
        code=subprocess.run([sys.executable,str(previous/'apply_and_test.py'),'--repo',str(repo),'--integration'],cwd=repo).returncode
        need(code==0,'PREVIOUS_RELEASE_INTEGRATION_REQUIRES_REVIEW')
    else:checkpoint(folder,repo)
    prior=json.loads(regular(previous/'VM-VALIDATION.json'))
    need(prior['status']=='PASS_TARGETED_ONLY' and prior['collected_cases']==276 and prior['broader_integration_reexecuted'] is True,
        'PRIOR_276_CASE_RELEASE_PASS_REQUIRED')
    old=Path(prior['release_folder']);old_manifest_raw=regular(old/'RELEASE-MANIFEST.json');old_manifest=json.loads(old_manifest_raw);verify(old,old_manifest)
    review=Path(tempfile.mkdtemp(prefix='hilega-worker-registration-review-',dir=repo));release=review/'release';release.mkdir(mode=0o700)
    for n,d in old_manifest['files'].items():
        p=Path(n);need(not p.is_absolute() and '..' not in p.parts,'RELATIVE_RELEASE_PATH_REQUIRED')
        raw=regular(old/p);need(sha(raw)==d,'OLD_RELEASE_CHANGED');target=release/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    worker=release/'scripts/hilega_production_simulator_bridge.py';old_worker=worker.read_bytes();worker.write_text(transform(old_worker.decode()))
    module=release/'backend/market_lab/hilega_worker_registration_v1.py';module.write_bytes(regular(folder/'worker_registration_v1.py'))
    (release/'probe.py').write_bytes(regular(folder/'probe.py'))
    registration=dict(model=MODEL,mode='CLOSED_PREPARATION_ONLY',base_release_manifest_sha256=sha(old_manifest_raw),
        production_execution_enabled=False,execution_factory_configured=False)
    (release/'CLOSED-REGISTRATION.json').write_text(json.dumps(registration,indent=2)+'\n')
    files={p.relative_to(release).as_posix():sha(p.read_bytes()) for p in release.rglob('*') if p.is_file()}
    manifest=dict(old_manifest,files=files,model='HILEGA_CLOSED_REGISTERED_WORKER_RELEASE_V1')
    (release/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');verify(release,manifest)
    for p in release.rglob('*.py'):compile(p.read_bytes(),str(p),'exec')
    registration_path=release/'CLOSED-REGISTRATION.json';registration_sha=sha(regular(registration_path))
    environment={'PATH':os.defpath,'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HOME':str(review)}
    r=subprocess.run([sys.executable,'-B',str(release/'probe.py'),'--registration',str(registration_path),'--sha256',registration_sha],
        cwd=release,env=environment,capture_output=True,text=True,timeout=15)
    need(r.returncode==0,'DIRECT_CLOSED_REGISTRATION_PROBE_FAILED');need(json.loads(r.stdout)['status']=='MANAGED_CLOSED_REGISTRATION_PROBE_PASS','PROBE_OUTPUT_CHANGED')
    rollback=worker_rollback(review,old_worker,worker.read_bytes());verify(release,manifest);verify(old,old_manifest)
    (review/'ROLLBACK-REHEARSAL.json').write_text(json.dumps(rollback,indent=2)+'\n')
    unit='hilega-closed-registration-probe-'+uuid.uuid4().hex[:12]+'.service'
    plan=dict(scope='DISPOSABLE_MANAGED_CLOSED_REGISTRATION_PROBE',repo=str(repo),release_folder=str(release),
        release_manifest_sha256=sha(regular(release/'RELEASE-MANIFEST.json')),registration=str(registration_path),
        registration_sha256=registration_sha,tool_manifest_sha256=sha(regular(folder/'MANIFEST.json')),
        python=sys.executable,probe_script=str(release/'probe.py'),probe_unit=unit,
        application_services_modified=False,application_databases_opened=False,credentials_opened=False,
        source_worker_executed=False,production_execution_enabled=False)
    plan_path=review/'PROBE-PLAN.json';plan_path.write_text(json.dumps(plan,indent=2)+'\n')
    approval=dict(scope='PROPOSED_NEW_RELEASE_BINDINGS',base_release_manifest_sha256=sha(old_manifest_raw),
        new_release_manifest_sha256=plan['release_manifest_sha256'],public_registration_sha256=registration_sha,
        old_supervisor_approval_retained=True,new_supervisor_approval_written=False,release_approved=False,
        source_service_execstart_changed=False,companion_pin_chain_reconciled_for_new_deployment=False,
        execution_factory_configured=False,production_execution_enabled=False)
    (review/'PROPOSED-APPROVAL-BINDINGS.json').write_text(json.dumps(approval,indent=2)+'\n')
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_registration.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items());verify(release,manifest);verify(old,old_manifest)
    passed=code==0 and len(cases)==10 and failed==skipped==0 and unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='CLOSED_WORKER_REGISTRATION_APPROVAL_BINDINGS_PROBE_AND_ROLLBACK_PREPARATION',
        collected_cases=len(cases)+(276 if args.integration else 0),new_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        prior_integration_cases_passed=276,broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,
        explicit_closed_worker_registration_staged=True,new_release_approval_bindings_proposed=True,
        direct_closed_registration_probe_passed=True,managed_probe_plan_created=True,managed_probe_started=False,
        disposable_registered_worker_rollback_rehearsed=True,actual_managed_worker_startup_or_rollback_tested=False,
        live_apply_available=False,new_release_approved=False,runtime_registration_installed=False,
        review_folder=str(review),release_folder=str(release),probe_plan=str(plan_path),probe_plan_sha256=sha(regular(plan_path)),
        installed_sources_modified=False,application_services_changed=False,packages_installed=False,
        controller_resumed=False,live_database_enrolled=False,production_execution_enabled=False,production_ready=False)
    dest=folder/'VM-VALIDATION.json';dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));print('Report:',dest)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
