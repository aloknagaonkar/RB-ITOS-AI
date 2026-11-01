"""Isolated VM checks; no production install, controller action or order access."""
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

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--new-only',action='store_true',help='18 new cases instead of combined 122')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    previous=repo/'hilega-application-cycle-close-v1'
    manifest=json.loads((folder/'MANIFEST.json').read_text())
    for name,expected in manifest.items():
        p=folder/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,
             'PACKAGE_CHANGED: '+name)
    report_path=previous/'VM-VALIDATION.json'
    need(report_path.is_file() and not report_path.is_symlink(),'prior 104-case cycle-close report required')
    baseline=json.loads(report_path.read_text())
    need(baseline.get('status')=='PASS_TARGETED_ONLY' and baseline.get('collected_cases')==104
         and baseline.get('broader_handoff_integration_reexecuted') is True
         and baseline.get('pinned_application_sources_unchanged') is True
         and baseline.get('production_execution_enabled') is False,'prior 104-case milestone must pass')
    prior_manifest=json.loads((previous/'MANIFEST.json').read_text())
    for name,expected in prior_manifest.items():
        p=previous/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,
             'PREVIOUS_CANDIDATE_CHANGED: '+name)
    pins=json.loads((previous/'SOURCE_PINS.json').read_text())
    for name,expected in pins.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,
             'VM_SOURCE_DIFFERS_FROM_REVIEW: '+name)
    # The artifact was assembled without an active execution workspace. Syntax
    # validation is explicitly done HERE before any test module can execute.
    for p in list(folder.glob('*.py'))+list(previous.glob('*.py')):
        compile(p.read_bytes(),str(p),'exec')
    env=dict(os.environ)
    env['PYTHONPATH']=os.pathsep.join(map(str,[folder,previous,repo/'backend',repo/'tests',repo]))
    selected=[str(folder/'test_history_aware_preparation_v1.py')]
    if not args.new_only:
        selected += [str(previous/name) for name in (
            'test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py',
            'test_application_cycle_close_v1.py')]
    expected=18 if args.new_only else 122
    with tempfile.TemporaryDirectory(prefix='hilega-next-preparation-') as tmp:
        junit=Path(tmp)/'results.xml'
        result=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=env)
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(hashlib.sha256((repo/k).read_bytes()).hexdigest()==v for k,v in pins.items())
    previous_unchanged=all(hashlib.sha256((previous/k).read_bytes()).hexdigest()==v for k,v in prior_manifest.items())
    passed=result.returncode==0 and len(cases)==expected and failed==skipped==0 and unchanged and previous_unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        scope='HISTORY_AWARE_NEXT_DISABLED_APPLICATION_PREPARATION',collected_cases=len(cases),
        failed=failed,skipped=skipped,pytest_exit_code=result.returncode,
        reviewed_application_commit='c96fbb4a55951432ddd48dcca3825350dfe1721b',
        syntax_checked_on_vm=True,pinned_application_sources_unchanged=unchanged,
        previous_candidate_sources_unchanged=previous_unchanged,
        broader_integration_reexecuted=not args.new_only,full_regression_reexecuted=False,
        history_aware_next_preparation_candidate_implemented=True,
        next_buy_execution_adoption_integrated=False,installed_source_reentry_hook_enabled=False,
        tests_use_temporary_synthetic_databases=True,positive_order_transport_intercepted=True,
        live_database_inspected=False,actual_broker_network_validated=False,
        fees_complete=False,broker_cash_release_implemented=False,
        dependency_manifest_fully_reconciled=False,installed_sources_modified=False,
        services_changed=False,production_execution_enabled=False,runtime_deployed=False,production_ready=False)
    path=folder/'VM-VALIDATION.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',path)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
