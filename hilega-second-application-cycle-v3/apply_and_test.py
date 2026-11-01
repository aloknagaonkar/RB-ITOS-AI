"""Isolated second-cycle VM integration. No install or managed service commands."""
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
    manifest=json.loads((folder/'MANIFEST.json').read_text())
    for name,expected in manifest.items():
        p=folder/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,
             'PACKAGE_OR_BASELINE_CHANGED: '+str(p))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--new-only',action='store_true',help='25 new cases instead of combined 147')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    previous=repo/'hilega-history-aware-preparation-v1';lifecycle=repo/'hilega-application-cycle-close-v1'
    own=check_manifest(folder);old=check_manifest(previous);base=check_manifest(lifecycle)
    result_path=previous/'VM-VALIDATION.json'
    need(result_path.is_file() and not result_path.is_symlink(),'prior 122-case VM report required')
    prior=json.loads(result_path.read_text())
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases')==122
         and prior.get('broader_integration_reexecuted') is True
         and prior.get('previous_candidate_sources_unchanged') is True
         and prior.get('production_execution_enabled') is False,'prior 122-case milestone must pass')
    pins=json.loads((lifecycle/'SOURCE_PINS.json').read_text())
    for name,expected in pins.items():
        p=repo/name
        need(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected,
             'REVIEWED_APPLICATION_SOURCE_CHANGED: '+name)
    for directory in (folder,previous,lifecycle):
        for p in directory.glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    selected=[str(folder/'test_second_application_cycle_v1.py')]
    if not args.new_only:
        selected += [str(previous/'test_history_aware_preparation_v1.py')]
        selected += [str(lifecycle/name) for name in ('test_authenticated_handoff_v1.py',
            'test_durable_closed_handoff_v1.py','test_existing_request_attempt_v1.py',
            'test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
    expected=25 if args.new_only else 147
    env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join(map(str,[folder,previous,lifecycle,repo/'backend',repo/'tests',repo]))
    with tempfile.TemporaryDirectory(prefix='hilega-second-cycle-') as tmp:
        junit=Path(tmp)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=env).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(hashlib.sha256((repo/k).read_bytes()).hexdigest()==v for k,v in pins.items())
    candidates_unchanged=all(hashlib.sha256((d/k).read_bytes()).hexdigest()==v for d,m in ((folder,own),(previous,old),(lifecycle,base)) for k,v in m.items())
    passed=code==0 and len(cases)==expected and failed==skipped==0 and unchanged and candidates_unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        scope='SECOND_COMPLETE_APPLICATION_CYCLE_CANDIDATE',candidate_revision='V3_PENDING_SELL_SCOPE',collected_cases=len(cases),failed=failed,skipped=skipped,
        pytest_exit_code=code,syntax_checked_on_vm=True,broader_integration_reexecuted=not args.new_only,
        full_regression_reexecuted=False,pinned_application_sources_unchanged=unchanged,
        previous_candidate_sources_unchanged=candidates_unchanged,
        history_aware_next_buy_adoption_candidate_implemented=True,
        current_cycle_scoped_lifecycle_candidate_implemented=True,
        two_cycle_closeout_retirement_candidate_implemented=True,
        third_signal_history_review_candidate_implemented=True,
        original_signed_account_capture_preserved=True,
        tests_use_temporary_synthetic_databases=True,positive_order_transport_intercepted=True,
        actual_broker_network_validated=False,live_database_inspected=False,
        installed_source_reentry_hook_enabled=False,automatic_execution_worker_installed=False,
        fees_complete=False,broker_cash_release_implemented=False,dependency_manifest_fully_reconciled=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False,
        runtime_deployed=False,production_ready=False)
    path=folder/'VM-VALIDATION.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',path)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
