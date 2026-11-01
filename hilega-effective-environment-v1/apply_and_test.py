"""Read-only environment, adapter baseline and proposed release review; no apply."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def need(ok,reason):
    if not ok:raise SystemExit('STOP: '+reason)


def regular(path):
    p=Path(path)
    need(p.is_absolute() and p.is_file() and p.stat().st_size<=4_000_000
        and not any(q.is_symlink() for q in [p,*p.parents]),'regular bounded source required')
    return p.read_bytes()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true',help='234 cases: previous 212, 14 readiness and 8 environment cases')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    readiness_folder=repo/'hilega-readonly-readiness-v1';sys.path.insert(0,str(readiness_folder))
    pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for name,expected in pins.items():need(sha(regular(repo/name))==expected,'REVIEWED_SOURCE_CHANGED: '+name)
    own=json.loads(regular(folder/'MANIFEST.json'))
    for name,expected in own.items():need(sha(regular(folder/name))==expected,'PACKAGE_CHANGED: '+name)
    from effective_environment import combined_review
    v2=repo/'hilega-closed-release-v2';old=json.loads(regular(v2/'VM-VALIDATION.json'))
    need(old.get('status')=='PASS_TARGETED_ONLY' and old.get('collected_cases')==212
        and old.get('failed')==0 and old.get('broader_integration_reexecuted') is True
        and old.get('production_execution_enabled') is False,'previous combined 212-case pass required')
    prior_path=readiness_folder/'VM-VALIDATION.json';prior=json.loads(regular(prior_path))
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases') in {14,226}
        and prior.get('failed')==0 and prior.get('supervisor_approval_hashes_match') is True
        and prior.get('production_execution_enabled') is False,'successful read-only readiness checkpoint required')
    candidate=Path(old['stage']);stage_pins=json.loads(regular(Path(old['review_folder'])/'STAGED-MANIFEST.json'))
    for name,expected in stage_pins.items():
        relative=Path(name);need(not relative.is_absolute() and '..' not in relative.parts,'invalid stage path')
        need(sha(regular(candidate/relative))==expected,'VERIFIED_STAGE_CHANGED')
    for p in folder.glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    output=Path(tempfile.mkdtemp(prefix='hilega-effective-environment-',dir=repo))
    environment,baseline,contract=combined_review(repo,Path.home(),candidate,stage_pins)
    for name,data in [('EFFECTIVE-ENVIRONMENT.json',environment),('CONFIRMED-PATH-BASELINE.json',baseline),('PROPOSED-RELEASE-CONTRACT.json',contract)]:
        (output/name).write_text(json.dumps(data,indent=2)+'\n')
    route=repo/'hilega-exclusive-route-v1';coordinator=repo/'hilega-durable-coordinator-v1';second=repo/'hilega-second-application-cycle-v3'
    preparation=repo/'hilega-history-aware-preparation-v1';base=repo/'hilega-application-cycle-close-v1'
    selected=[]
    if args.integration:
        selected=[str(route/'test_exclusive_closed_route_v1.py'),str(coordinator/'test_closed_application_coordinator_v1.py'),
            str(second/'test_second_application_cycle_v1.py'),str(preparation/'test_history_aware_preparation_v1.py')]
        selected += [str(base/n) for n in ('test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
        selected += [str(v2/'test_closed_release.py'),str(readiness_folder/'test_readiness.py')]
    selected.append(str(folder/'test_effective_environment.py'))
    env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join(map(str,[folder,readiness_folder,v2,route,coordinator,second,preparation,base,repo/'backend',repo/'tests',repo]))
    env['HILEGA_EXCLUSIVE_TEST_STAGE']=str(candidate);env['HILEGA_RELEASE_STAGE']=str(candidate)
    with tempfile.TemporaryDirectory(prefix='hilega-effective-env-tests-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=env).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(repo/n))==v for n,v in pins.items()) and all(sha(regular(folder/n))==v for n,v in own.items())
    stage_ok=all(sha(regular(candidate/n))==v for n,v in stage_pins.items())
    passed=code==0 and len(cases)==(234 if args.integration else 8) and failed==skipped==0 and unchanged and stage_ok
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='PINNED_EFFECTIVE_ENVIRONMENT_AND_PROPOSED_CLOSED_RELEASE',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,prior_integration_cases_passed=212,
        prior_readiness_report_sha256=sha(regular(prior_path)),pinned_sources_unchanged=unchanged,staged_sources_unchanged=stage_ok,
        environment_hash_revalidated=environment['environment_hash_revalidated'],
        effective_database_paths_confirmed_from_startup_contract=environment['effective_database_paths_confirmed'],
        actual_running_process_environment_verified=False,live_database_inspected=baseline['live_database_inspected'],
        database_baseline_status=baseline['status'],baseline_blockers=baseline.get('blockers',[]),
        proposed_release_contract_created=True,new_release_approved=False,dependency_manifest_fully_reconciled=False,
        review_folder=str(output),approvals_modified=False,environment_values_exported=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False,runtime_deployed=False,production_ready=False)
    destination=folder/'VM-VALIDATION.json';destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',destination)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
