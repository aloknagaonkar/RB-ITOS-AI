"""Validate isolated coordinator on VM. No installation or service control."""
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


def check_manifest(folder):
    p=folder/'MANIFEST.json'
    need(p.is_file() and not p.is_symlink(),'regular manifest required: '+str(p))
    data=json.loads(p.read_text())
    for name,expected in data.items():
        source=folder/name
        need(not Path(name).is_absolute() and '..' not in Path(name).parts,'invalid manifest path')
        need(source.is_file() and not source.is_symlink() and hashlib.sha256(source.read_bytes()).hexdigest()==expected,
             'PACKAGE_OR_BASELINE_CHANGED: '+str(source))
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true',help='172 cases: previous 147 plus 25 coordinator cases')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    second=repo/'hilega-second-application-cycle-v3'
    previous=repo/'hilega-history-aware-preparation-v1';base=repo/'hilega-application-cycle-close-v1'
    directories=(folder,second,previous,base)
    manifests={d:check_manifest(d) for d in directories}
    evidence=second/'VM-VALIDATION.json'
    need(evidence.is_file() and not evidence.is_symlink(),'previous 147-case VM report required')
    prior=json.loads(evidence.read_text())
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases')==147
         and prior.get('failed')==0 and prior.get('skipped')==0 and prior.get('pytest_exit_code')==0
         and prior.get('candidate_revision')=='V3_PENDING_SELL_SCOPE'
         and prior.get('broader_integration_reexecuted') is True
         and prior.get('pinned_application_sources_unchanged') is True
         and prior.get('previous_candidate_sources_unchanged') is True
         and all(prior.get(k) is False for k in ('production_execution_enabled','runtime_deployed','production_ready')),
         '147-case V3 integration checkpoint must pass first')
    pins_file=base/'SOURCE_PINS.json'
    need(pins_file.is_file() and not pins_file.is_symlink(),'regular source pins required')
    pins=json.loads(pins_file.read_text())
    for name,expected in pins.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,
             'PINNED_APPLICATION_SOURCE_CHANGED: '+name)
    for d in directories:
        for p in d.glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    selected=[str(folder/'test_closed_application_coordinator_v1.py')]
    if args.integration:
        selected += [str(second/'test_second_application_cycle_v1.py'),str(previous/'test_history_aware_preparation_v1.py')]
        selected += [str(base/n) for n in ('test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
    expected=172 if args.integration else 25
    environment=dict(os.environ);environment['PYTHONPATH']=os.pathsep.join(map(str,[*directories,repo/'backend',repo/'tests',repo]))
    with tempfile.TemporaryDirectory(prefix='hilega-coordinator-validation-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=environment).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all((repo/n).is_file() and hashlib.sha256((repo/n).read_bytes()).hexdigest()==v for n,v in pins.items())
    sources_unchanged=all((d/n).is_file() and hashlib.sha256((d/n).read_bytes()).hexdigest()==v for d,m in manifests.items() for n,v in m.items())
    passed=code==0 and len(cases)==expected and failed==skipped==0 and unchanged and sources_unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        scope='DURABLE_CLOSED_APPLICATION_COORDINATOR_CANDIDATE',collected_cases=len(cases),failed=failed,skipped=skipped,
        pytest_exit_code=code,syntax_checked_on_vm=True,broader_integration_reexecuted=args.integration,
        full_regression_reexecuted=False,prior_integration_cases_passed=147,
        prior_report_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
        pinned_application_sources_unchanged=unchanged,previous_candidate_sources_unchanged=sources_unchanged,
        durable_application_coordinator_candidate_implemented=True,
        default_cli_closed_in_code=True,candidate_session_python_injection_only=True,
        tests_use_temporary_synthetic_databases=True,positive_order_transport_intercepted=True,
        running_service_hook_installed=False,exclusive_running_source_routing_validated=False,
        actual_broker_network_validated=False,live_database_inspected=False,
        fees_complete=False,broker_cash_release_implemented=False,dependency_manifest_fully_reconciled=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False,
        runtime_deployed=False,production_ready=False)
    destination=folder/'VM-VALIDATION.json';destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',destination)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
