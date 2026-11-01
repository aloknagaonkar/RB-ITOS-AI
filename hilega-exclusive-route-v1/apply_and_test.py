"""Stage guarded Source/worker and run VM tests. No deployment or service commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from stage_sources import stage,SOURCE,WORKER


def need(ok,reason):
    if not ok:raise SystemExit('STOP: '+reason)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def check(folder):
    p=folder/'MANIFEST.json';need(p.is_file() and not p.is_symlink(),'regular package manifest required: '+str(p))
    data=json.loads(p.read_text())
    for name,expected in data.items():
        need(not Path(name).is_absolute() and '..' not in Path(name).parts,'invalid manifest path')
        p=folder/name
        need(p.is_file() and not p.is_symlink() and sha(p)==expected,'PACKAGE_CHANGED: '+str(p))
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true',help='191 cases including previous 172')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    coordinator=repo/'hilega-durable-coordinator-v1';second=repo/'hilega-second-application-cycle-v3'
    previous=repo/'hilega-history-aware-preparation-v1';base=repo/'hilega-application-cycle-close-v1'
    directories=(folder,coordinator,second,previous,base)
    manifests={d:check(d) for d in directories}
    reviewed=json.loads((folder/'BASELINE_PINS.json').read_text())
    for name,expected in reviewed.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and sha(p)==expected,'REVIEWED_BASELINE_CHANGED: '+name)
    evidence=coordinator/'VM-VALIDATION.json'
    need(evidence.is_file() and not evidence.is_symlink(),'172-case coordinator VM report required')
    prior=json.loads(evidence.read_text())
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases')==172
         and prior.get('failed')==0 and prior.get('skipped')==0 and prior.get('pytest_exit_code')==0
         and prior.get('broader_integration_reexecuted') is True
         and prior.get('pinned_application_sources_unchanged') is True
         and prior.get('previous_candidate_sources_unchanged') is True
         and all(prior.get(k) is False for k in ('production_execution_enabled','runtime_deployed','production_ready')),
         'combined 172-case coordinator milestone must pass first')
    pins=json.loads((base/'SOURCE_PINS.json').read_text());pins[WORKER]=reviewed[WORKER]
    for name,expected in pins.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and sha(p)==expected,'INSTALLED_SOURCE_CHANGED: '+name)
    need((repo/SOURCE).read_bytes()==(folder/'reviewed/source.py.txt').read_bytes(),'reviewed Source mismatch')
    need((repo/WORKER).read_bytes()==(folder/'reviewed/worker.py.txt').read_bytes(),'reviewed worker mismatch')
    for d in directories:
        for p in d.glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    root=Path(tempfile.mkdtemp(prefix='hilega-exclusive-route-stage-',dir=repo));candidate=root/'candidate'
    staged=stage(repo,folder,candidate)
    (root/'STAGED-MANIFEST.json').write_text(json.dumps(staged,indent=2)+'\n')
    selected=[str(folder/'test_exclusive_closed_route_v1.py')]
    if args.integration:
        selected += [str(coordinator/'test_closed_application_coordinator_v1.py'),str(second/'test_second_application_cycle_v1.py'),
            str(previous/'test_history_aware_preparation_v1.py')]
        selected += [str(base/n) for n in ('test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
    environment=dict(os.environ)
    environment['PYTHONPATH']=os.pathsep.join(map(str,[*directories,repo/'backend',repo/'tests',repo]))
    environment['HILEGA_EXCLUSIVE_TEST_STAGE']=str(candidate)
    with tempfile.TemporaryDirectory(prefix='hilega-exclusive-route-results-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=environment).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all((repo/n).is_file() and sha(repo/n)==v for n,v in pins.items())
    baseline=all((repo/n).is_file() and sha(repo/n)==v for n,v in reviewed.items())
    packages=all((d/n).is_file() and sha(d/n)==v for d,m in manifests.items() for n,v in m.items())
    stage_unchanged=all((candidate/n).is_file() and sha(candidate/n)==v for n,v in staged.items())
    expected=191 if args.integration else 19
    passed=code==0 and len(cases)==expected and failed==skipped==0 and unchanged and baseline and packages and stage_unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='STAGED_EXCLUSIVE_SOURCE_AND_COORDINATOR_ROUTING',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        syntax_checked_on_vm=True,broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,
        prior_integration_cases_passed=172,prior_report_sha256=sha(evidence),
        pinned_application_sources_unchanged=unchanged,previous_candidate_sources_unchanged=baseline and packages,
        staged_source_guard_implemented=True,staged_coordinator_route_guard_implemented=True,
        actual_worker_closed_call_site_staged=True,staged_sources_unchanged=stage_unchanged,
        stage=str(candidate),tests_use_temporary_synthetic_databases=True,positive_order_transport_intercepted=True,
        exclusive_routing_tested_in_staged_temporary_environment=passed,
        running_service_hook_installed=False,exclusive_running_source_routing_validated=False,
        production_execution_session_factory_configured=False,
        actual_broker_network_validated=False,live_database_inspected=False,
        fees_complete=False,broker_cash_release_implemented=False,dependency_manifest_fully_reconciled=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False,
        runtime_deployed=False,production_ready=False)
    path=folder/'VM-VALIDATION.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',path)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
