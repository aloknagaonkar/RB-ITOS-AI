"""Produce a scoped candidate dependency lock; no install or live enrollment."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dependency_lock import lock_wheel,transitive_review
from release_review import regular,review_dynamic,distribution_snapshot


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--integration',action='store_true');p.add_argument('--wheel',type=Path,help='Existing python-dotenv 1.2.3 wheel; otherwise download only from public PyPI')
    args=p.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(regular(folder/'MANIFEST.json'));pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for n,d in own.items():
        if sha(regular(folder/n))!=d:raise SystemExit('STOP: package changed: '+n)
    for n,d in pins.items():
        if sha(regular(repo/n))!=d:raise SystemExit('STOP: prior review tools changed: '+n)
    previous=repo/'hilega-runtime-registration-v1'
    if args.integration:
        command=[sys.executable,str(previous/'apply_and_test.py'),'--repo',str(repo),'--integration']
    else:
        command=[sys.executable,str(previous/'apply_and_test.py'),'--repo',str(repo)]
    if subprocess.run(command,cwd=repo).returncode:raise SystemExit('STOP: preceding review requires attention')
    prior=json.loads(regular(previous/'VM-VALIDATION.json'))
    # In targeted mode the preceding runner rechecks health and reports six new cases.
    if prior['status']!='PASS_TARGETED_ONLY' or (args.integration and prior['collected_cases']!=260):
        raise SystemExit('STOP: passing preceding dependency review required')
    old=Path(prior['stage']);manifest=json.loads(regular(old.parent/'STAGED-MANIFEST.json'))
    review=Path(tempfile.mkdtemp(prefix='hilega-dependency-lock-review-',dir=repo));stage=review/'candidate';stage.mkdir(mode=0o700)
    for n,d in manifest.items():
        rel=Path(n)
        if rel.is_absolute() or '..' in rel.parts:raise SystemExit('STOP: invalid stage path')
        raw=regular(old/rel)
        if sha(raw)!=d:raise SystemExit('STOP: prior runtime stage changed')
        target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    dynamic_pins=json.loads(regular(folder/'DYNAMIC_PINS.json'));review_dynamic(repo,dynamic_pins)
    graph=transitive_review(repo,stage,dynamic_pins)
    (review/'TRANSITIVE-IMPORT-REVIEW.json').write_text(json.dumps(graph,indent=2)+'\n')
    installed=distribution_snapshot('1.2.3')
    if args.wheel:
        wheel=args.wheel.absolute();regular(wheel)
    else:
        wheels=review/'wheels';wheels.mkdir()
        # Download only. Isolated pip ignores user environment/configured indexes; no credentials used.
        try:
            result=subprocess.run([sys.executable,'-m','pip','--isolated','--disable-pip-version-check','download',
                '--index-url','https://pypi.org/simple','--no-cache-dir','--no-deps','--only-binary=:all:',
                '--dest',str(wheels),'python-dotenv==1.2.3'],cwd=repo,capture_output=True,timeout=60)
        except subprocess.TimeoutExpired:raise SystemExit('STOP: wheel download timed out; services unchanged. Supply --wheel /absolute/file.whl')
        if result.returncode:raise SystemExit('STOP: wheel download failed; no install performed. Supply --wheel /absolute/file.whl')
        found=list(wheels.glob('*.whl'))
        if len(found)!=1:raise SystemExit('STOP: unique wheel required')
        wheel=found[0]
    lock=lock_wheel(wheel,installed)
    if wheel.parent!=review/'wheels':
        destination=review/'wheels';destination.mkdir(exist_ok=True);shutil.copyfile(wheel,destination/wheel.name)
    (review/'WHEEL-LOCK.json').write_text(json.dumps(lock,indent=2)+'\n')
    (review/'requirements-candidate.lock').write_text('--only-binary=:all:\n'+lock['requirement']+'\n')
    (review/'STAGED-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_dependency_lock.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items()) and all(sha(regular(repo/n))==d for n,d in pins.items())
    stage_ok=all(sha(regular(old/n))==d and sha(regular(stage/n))==d for n,d in manifest.items())
    passed=code==0 and len(cases)==8 and failed==skipped==0 and unchanged and stage_ok
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='SCOPED_CANDIDATE_WHEEL_LOCK_AND_FIXED_DYNAMIC_TRANSITIVE_REVIEW',
        collected_cases=len(cases)+(260 if args.integration else 6),new_cases=len(cases),failed=failed,skipped=skipped,
        pytest_exit_code=code,broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,
        prior_integration_cases_passed=260,fixed_dynamic_transitive_imports_reviewed=True,
        scoped_external_wheel_hash_locked=True,installed_dotenv_python_sources_match_wheel=True,
        unresolved_local_imports=graph['unresolved_local'],external_imports=graph['external_imports'],
        scoped_candidate_dependency_inputs_verified=True,dependency_manifest_fully_reconciled=False,
        full_application_and_service_dependency_closure_verified=False,
        review_folder=str(review),stage=str(stage),pinned_sources_unchanged=unchanged,staged_sources_unchanged=stage_ok,
        installed_sources_modified=False,services_changed=False,packages_installed=False,
        controller_resumed=False,live_database_enrolled=False,runtime_registration_installed=False,
        production_authority_provisioned=False,actual_broker_network_validated=False,
        production_execution_enabled=False,production_ready=False)
    dest=folder/'VM-VALIDATION.json';dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));print('Report:',dest)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
