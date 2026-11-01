"""Combined closed release review, dependency inventory, startup and rollback rehearsal."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from release_tools import service_inventory,release_plan,probe_unit,direct_dependency_inventory,sha


def need(ok,reason):
    if not ok:raise SystemExit('STOP: '+reason)


def checked(folder):
    p=folder/'MANIFEST.json';need(p.is_file() and not p.is_symlink(),'regular manifest required: '+str(p))
    data=json.loads(p.read_text())
    for name,expected in data.items():
        need(not Path(name).is_absolute() and '..' not in Path(name).parts,'invalid manifest path')
        p=folder/name
        need(p.is_file() and not p.is_symlink() and sha(p.read_bytes())==expected,'PACKAGE_CHANGED: '+str(p))
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true',help='207 combined candidate cases instead of 16 new cases')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    names=('hilega-exclusive-route-v1','hilega-durable-coordinator-v1','hilega-second-application-cycle-v3',
        'hilega-history-aware-preparation-v1','hilega-application-cycle-close-v1')
    previous=[repo/n for n in names];route,coordinator,second,preparation,base=previous
    directories=[folder,*previous];manifests={d:checked(d) for d in directories}
    reviewed=json.loads((folder/'BASELINE_PINS.json').read_text())
    for name,expected in reviewed.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and sha(p.read_bytes())==expected,'REVIEWED_BASELINE_CHANGED: '+name)
    pins=json.loads((base/'SOURCE_PINS.json').read_text())
    pins['scripts/hilega_production_simulator_bridge.py']='9fd8bc6b22af63229f59743722cfb156b12feb0ca279bc2117a103d02670de98'
    for name,expected in pins.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and sha(p.read_bytes())==expected,'INSTALLED_SOURCE_CHANGED: '+name)
    evidence=route/'VM-VALIDATION.json';need(evidence.is_file() and not evidence.is_symlink(),'191-case VM report required')
    prior=json.loads(evidence.read_text())
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases')==191
         and prior.get('failed')==0 and prior.get('skipped')==0 and prior.get('pytest_exit_code')==0
         and prior.get('broader_integration_reexecuted') is True
         and prior.get('previous_candidate_sources_unchanged') is True
         and prior.get('staged_sources_unchanged') is True
         and all(prior.get(k) is False for k in ('production_execution_enabled','runtime_deployed','production_ready')),
         'combined 191-case routing checkpoint must pass first')
    for d in directories:
        for p in d.glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    spec=importlib.util.spec_from_file_location('reviewed_route_stager',route/'stage_sources.py')
    stager=importlib.util.module_from_spec(spec);spec.loader.exec_module(stager)
    parent=Path(tempfile.mkdtemp(prefix='hilega-closed-release-stage-',dir=repo));candidate=parent/'candidate'
    staged=stager.stage(repo,route,candidate)
    (parent/'STAGED-MANIFEST.json').write_text(json.dumps(staged,indent=2)+'\n')
    inventory=service_inventory(repo,Path.home())
    (parent/'SERVICE-INVENTORY.json').write_text(json.dumps(inventory,indent=2)+'\n')
    plan=release_plan(repo,candidate,staged,inventory)
    (parent/'RELEASE-REVIEW.json').write_text(json.dumps(plan,indent=2)+'\n')
    unit=parent/'hilega-closed-release-probe.service'
    unit.write_text(probe_unit(Path(sys.executable),candidate/'closed_application_coordinator_v1.py'))
    try:
        verify=subprocess.run(['systemd-analyze','--user','verify',str(unit)],capture_output=True,text=True,timeout=20)
        unit_verified=verify.returncode==0
    except (OSError,subprocess.TimeoutExpired):unit_verified=False
    paths=[candidate/'backend',*previous,repo/'backend',repo/'tests',repo,Path.home(),*[Path(p) for p in sys.path if p]]
    sources={
        'market_lab.hilega_preparation_runtime_v1.source':(candidate/stager.SOURCE).read_text(),
        'market_lab.hilega_exclusive_closed_route_v1':(candidate/stager.GUARD).read_text(),
        'closed_application_coordinator_v1':(candidate/'closed_application_coordinator_v1.py').read_text()}
    for d in previous:
        for p in d.glob('*.py'):
            if not p.name.startswith(('test_','apply_','conftest','stage_')):sources.setdefault(p.stem,p.read_text())
    dependencies=direct_dependency_inventory(sources,paths)
    (parent/'DIRECT-DEPENDENCIES.json').write_text(json.dumps(dependencies,indent=2)+'\n')
    selected=[]
    if args.integration:
        # Collect routing folder first: its conftest installs the staged overlay once.
        selected += [str(route/'test_exclusive_closed_route_v1.py'),str(coordinator/'test_closed_application_coordinator_v1.py'),
            str(second/'test_second_application_cycle_v1.py'),str(preparation/'test_history_aware_preparation_v1.py')]
        selected += [str(base/n) for n in ('test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
    selected.append(str(folder/'test_closed_release.py'))
    environment=dict(os.environ)
    environment['PYTHONPATH']=os.pathsep.join(map(str,[*directories,repo/'backend',repo/'tests',repo]))
    environment['HILEGA_EXCLUSIVE_TEST_STAGE']=str(candidate)
    environment['HILEGA_RELEASE_STAGE']=str(candidate)
    with tempfile.TemporaryDirectory(prefix='hilega-closed-release-results-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=environment).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all((repo/n).is_file() and sha((repo/n).read_bytes())==v for n,v in pins.items())
    baseline=all((repo/n).is_file() and sha((repo/n).read_bytes())==v for n,v in reviewed.items())
    packages=all((d/n).is_file() and sha((d/n).read_bytes())==v for d,m in manifests.items() for n,v in m.items())
    stage_ok=all((candidate/n).is_file() and sha((candidate/n).read_bytes())==v for n,v in staged.items())
    expected=207 if args.integration else 16
    passed=code==0 and len(cases)==expected and failed==skipped==0 and unchanged and baseline and packages and stage_ok
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='COMBINED_CLOSED_RELEASE_PLANNING_STARTUP_AND_ROLLBACK',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,prior_integration_cases_passed=191,
        prior_report_sha256=sha(evidence.read_bytes()),pinned_application_sources_unchanged=unchanged,
        previous_candidate_sources_unchanged=baseline and packages,staged_sources_unchanged=stage_ok,
        release_review_plan_created=True,source_service_mapping_confirmed=inventory['source_service_mapping_confirmed'],
        bounded_closed_cli_startup_rehearsed=passed,disposable_file_rollback_rehearsed=passed,
        closed_probe_unit_syntax_verified=unit_verified,closed_probe_unit_started=False,
        direct_dependency_inventory_created=True,direct_unresolved_imports=dependencies['unresolved_count'],
        dependency_manifest_fully_reconciled=False,live_apply_available=False,
        stage=str(candidate),review_folder=str(parent),tests_use_temporary_synthetic_databases=True,
        positive_order_transport_intercepted=True,running_service_hook_installed=False,
        exclusive_running_source_routing_validated=False,production_execution_session_factory_configured=False,
        actual_broker_network_validated=False,live_database_inspected=False,fees_complete=False,
        broker_cash_release_implemented=False,installed_sources_modified=False,services_changed=False,
        production_execution_enabled=False,runtime_deployed=False,production_ready=False)
    destination=folder/'VM-VALIDATION.json';destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',destination)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
