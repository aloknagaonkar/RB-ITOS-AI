"""Review fixed dynamic dependencies, installed dotenv and proposed runtime registration."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from release_review import regular,review_dynamic,distribution_snapshot,registration_plan


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true');args=parser.parse_args()
    repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(regular(folder/'MANIFEST.json'))
    for n,d in own.items():
        if sha(regular(folder/n))!=d:raise SystemExit('STOP: package changed: '+n)
    pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for n,d in pins.items():
        if sha(regular(repo/n))!=d:raise SystemExit('STOP: baseline changed: '+n)
    previous=repo/'hilega-runtime-bootstrap-v1'
    if args.integration:
        code=subprocess.run([sys.executable,str(previous/'apply_and_test.py'),'--repo',str(repo),'--integration'],cwd=repo).returncode
        if code:raise SystemExit('STOP: previous combined integration requires review')
    else:
        code=subprocess.run([sys.executable,str(folder/'checkpoint.py'),'--repo',str(repo),
            '--plan',str(repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json'),
            '--compatibility-review',str(repo/'hilega-reference-compatibility-2jkluc07')],cwd=repo).returncode
        if code:raise SystemExit('STOP: bounded deployment checkpoint requires review')
    prior=json.loads(regular(previous/'VM-VALIDATION.json'))
    if not (prior['status']=='PASS_TARGETED_ONLY' and prior['collected_cases']==254 and prior['broader_integration_reexecuted'] is True):
        raise SystemExit('STOP: passing prior 254-case integration required')
    stage=Path(prior['stage']);manifest=json.loads(regular(stage.parent/'STAGED-MANIFEST.json'))
    for n,d in manifest.items():
        p=Path(n)
        if p.is_absolute() or '..' in p.parts or sha(regular(stage/p))!=d:raise SystemExit('STOP: prior stage changed')
    # Pin reviewed loader and each fixed target before collecting any external source metadata.
    dynamic=review_dynamic(repo,json.loads(regular(folder/'DYNAMIC_PINS.json')))
    external=distribution_snapshot('1.2.3')
    review=Path(tempfile.mkdtemp(prefix='hilega-runtime-registration-review-',dir=repo))
    for name,data in [('DYNAMIC-REVIEW.json',dynamic),('DOTENV-INSTALLED-SNAPSHOT.json',external),
        ('REGISTRATION-PLAN.json',registration_plan(stage,manifest,dynamic,external))]:
        (review/name).write_text(json.dumps(data,indent=2)+'\n')
    with tempfile.TemporaryDirectory() as temporary:
        junit=Path(temporary)/'results.xml'
        code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_release_review.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(folder/n))==d for n,d in own.items()) and all(sha(regular(repo/n))==d for n,d in pins.items())
    stage_unchanged=all(sha(regular(stage/n))==d for n,d in manifest.items())
    passed=code==0 and len(cases)==6 and failed==skipped==0 and unchanged and stage_unchanged
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        scope='FIXED_DYNAMIC_DEPENDENCY_REVIEW_AND_PROPOSED_RUNTIME_REGISTRATION',
        collected_cases=len(cases)+(254 if args.integration else 0),new_cases=len(cases),failed=failed,skipped=skipped,
        pytest_exit_code=code,broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,
        prior_integration_cases_passed=254,reviewed_fixed_dynamic_hashes_match=True,
        dotenv_expected_version=external['expected_version'],dotenv_installed_version=external['installed_version'],
        dotenv_version_matches=external['version_matches'],installed_distribution_source_snapshot_created=True,
        external_wheel_hash_locked=False,transitive_dynamic_import_review_complete=False,
        dependency_manifest_fully_reconciled=False,registration_plan_created=True,
        stage=str(stage),review_folder=str(review),pinned_sources_unchanged=unchanged,staged_sources_unchanged=stage_unchanged,
        installed_sources_modified=False,services_changed=False,secret_material_created=False,
        controller_resumed=False,live_database_enrolled=False,runtime_registration_installed=False,
        production_authority_provisioned=False,actual_broker_network_validated=False,
        production_execution_enabled=False,production_ready=False)
    dest=folder/'VM-VALIDATION.json';dest.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',dest)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
