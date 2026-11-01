"""VM-only targeted checks for an isolated existing-request attempt candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

def need(ok, reason):
    if not ok:raise SystemExit('STOP: '+reason)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--new-only',action='store_true',help='Run 25 new cycle-close cases instead of the combined 104')
    a=parser.parse_args();repo=a.repo.resolve();folder=Path(__file__).resolve().parent
    manifest=json.loads((folder/'MANIFEST.json').read_text())
    for name,expected in manifest.items():
        p=folder/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,'PACKAGE_CHANGED: '+name)
    pins=json.loads((folder/'SOURCE_PINS.json').read_text())
    for name,expected in pins.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,'VM_SOURCE_DIFFERS_FROM_REVIEW: '+name)
    previous=repo/'hilega-application-lifecycle-candidate-v1/VM-VALIDATION.json'
    need(previous.is_file() and not previous.is_symlink(),'prior 79-case application lifecycle report required')
    baseline=json.loads(previous.read_text())
    need(baseline.get('status')=='PASS_TARGETED_ONLY' and baseline.get('collected_cases')==79 and baseline.get('broader_handoff_integration_reexecuted') is True
         and baseline.get('pinned_application_sources_unchanged') is True
         and baseline.get('production_execution_enabled') is False,'prior 79-case lifecycle milestone must pass')
    env=dict(os.environ)
    env['PYTHONPATH']=os.pathsep.join(map(str,[folder,repo/'backend',repo/'tests',repo]))
    selected=[str(folder/'test_application_cycle_close_v1.py')]
    if not a.new_only:
        selected += [str(folder/name) for name in ('test_authenticated_handoff_v1.py',
            'test_durable_closed_handoff_v1.py','test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py')]
    expected=25 if a.new_only else 104
    with tempfile.TemporaryDirectory(prefix='hilega-contract-check-') as tmp:
        junit=Path(tmp)/'results.xml'
        result=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=env)
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(hashlib.sha256((repo/k).read_bytes()).hexdigest()==v for k,v in pins.items())
    passed=result.returncode==0 and len(cases)==expected and failed==skipped==0 and unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        scope='APPLICATION_CYCLE_CLOSEOUT_RETIREMENT_REENTRY_REVIEW',collected_cases=len(cases),failed=failed,skipped=skipped,
        pytest_exit_code=result.returncode,reviewed_github_commit='c96fbb4a55951432ddd48dcca3825350dfe1721b',
        pinned_application_sources_unchanged=unchanged,full_regression_reexecuted=False,
        tests_use_temporary_synthetic_databases=True,live_database_inspected=False,
        durable_closed_handoff_implemented=True,execution_adoption_candidate_implemented=True,
        production_execution_adoption_enabled=False,positive_order_transport_intercepted=True,
        broader_handoff_integration_reexecuted=not a.new_only,
        signed_fill_position_reconciliation_candidate_implemented=True,
        actual_source_closed_exit_reference_linked=True,
        candidate_sell_attempt_and_recovery_implemented=True,
        actual_broker_network_validated=False,production_owned_fill_integration_deployed=False,
        automatic_source_execution_hook_installed=False,closeout_retirement_candidate_integrated=True,
        history_aware_reentry_review_implemented=True,actual_next_entry_preparation_integrated=False,
        fees_complete=False,broker_cash_release_implemented=False,
        dependency_manifest_fully_reconciled=False,
        installed_sources_modified=False,services_changed=False,
        production_execution_enabled=False,runtime_deployed=False,production_ready=False)
    path=folder/'VM-VALIDATION.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',path)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
