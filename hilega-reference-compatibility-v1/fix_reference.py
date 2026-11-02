"""Validate the exact approved source delta, then optionally refresh the dependent pin chain."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from compatibility import prepare,regular,sha,need,SOURCE,GUARD,APPROVED


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--apply',action='store_true')
    args=p.parse_args();repo=args.repo.resolve();tool=Path(__file__).resolve().parent
    for n,d in json.loads(regular(tool/'MANIFEST.json')).items():need(sha(regular(tool/n))==d,'COMPATIBILITY_TOOL_CHANGED')
    plan_path=repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json';plan_raw=regular(plan_path)
    need(sha(plan_raw)==APPROVED,'EXACT_APPROVED_PLAN_REQUIRED');plan=json.loads(plan_raw)
    old=repo/'hilega-closed-rollout-v1'
    need(sha(regular(old/'MANIFEST.json'))==plan['tool_manifest_sha256'],'ORIGINAL_ROLLOUT_MANIFEST_CHANGED')
    for n,d in json.loads(regular(old/'MANIFEST.json')).items():need(sha(regular(old/n))==d,'ORIGINAL_ROLLOUT_TOOL_CHANGED')
    roll=load(old/'rollout.py','approved_compatibility_rollout')
    need(plan['repo']==str(repo),'APPROVED_REPOSITORY_CHANGED')
    for e in plan['files']:need(sha(regular(repo/e['name']))==e['new_sha256'],'APPROVED_INSTALLED_FILE_CHANGED')
    tx=json.loads(regular(plan_path.parent/'TRANSACTION.json'))
    need(tx['phase']=='STARTUP_FAILED_SERVICES_STOPPED','EXACT_FAILED_STOPPED_PHASE_REQUIRED')
    manager=roll.Systemd()
    need(all(manager.state(u)['active'] in {'inactive','failed'} and manager.state(u)['pid']==0 for u in roll.UNITS),'SERVICES_MUST_REMAIN_STOPPED')
    roll.no_unmanaged_python(repo);roll.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    package=repo/'hilega-operational-lifecycle-tools-6cexrur_'
    service=repo/'hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py'
    update=prepare(repo,package,service,repo/'hilega-exclusive-route-v1/reviewed/source.py.txt')
    folder=Path(tempfile.mkdtemp(prefix='hilega-reference-compatibility-',dir=repo));folder.chmod(0o700)
    staged=folder/'package';staged.mkdir(mode=0o700)
    for n in update['manifest']['modules']:shutil.copyfile(package/n,staged/n)
    for n in ('manifest.json','cli.py'):(staged/n).write_bytes(update['replacements'][n])
    staged_service=folder/'lifecycle_reference_service.py';staged_service.write_bytes(update['replacements']['service.py'])
    # Import the service under a non-main name, then invoke only its read-only check.
    companion=load(staged_service,'staged_reference_compatibility')
    companion.check_package(repo,staged)
    with tempfile.TemporaryDirectory(prefix='hilega-reference-compat-tests-') as temp:
        junit=Path(temp)/'junit.xml';env=dict(os.environ,PYTHONPATH=str(tool))
        code=subprocess.run([sys.executable,'-m','pytest',str(tool/'test_compatibility.py'),'-q','--junitxml='+str(junit)],cwd=repo,env=env).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(code==0 and len(cases)==6 and not any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases),'COMPATIBILITY_TESTS_MUST_PASS')
    targets={'manifest.json':package/'manifest.json','cli.py':package/'cli.py','service.py':service}
    receipt=dict(status='COMPATIBILITY_CHECK_PASS',collected_cases=6,approved_runtime_delta_verified=True,
        new_guard_pin_added=True,staged_companion_check_passed=True,review_folder=str(folder),
        dependent_pin_chain_modified=False,installed_hook_sources_modified=False,services_started=False,
        production_execution_enabled=False,production_ready=False)
    for n,p in targets.items():
        roll.atomic(folder/(n+'.original'),update['originals'][n],0o600)
    if args.apply:
        # Revalidate all preconditions immediately before the first write.
        prepare(repo,package,service,repo/'hilega-exclusive-route-v1/reviewed/source.py.txt')
        need(all(manager.state(u)['active'] in {'inactive','failed'} and manager.state(u)['pid']==0 for u in roll.UNITS),'SERVICES_MUST_REMAIN_STOPPED')
        modes={n:stat.S_IMODE(p.stat().st_mode) for n,p in targets.items()}
        roll.save(folder/'TRANSACTION.json',dict(phase='APPLYING_DEPENDENT_PIN_CHAIN',production_execution_enabled=False))
        try:
            for n,p in targets.items():
                need(regular(p)==update['originals'][n],'DEPENDENT_FILE_CHANGED_DURING_REVIEW')
                roll.atomic(p,update['replacements'][n],modes[n])
            load(service,'installed_reference_compatibility').check_package(repo,package)
        except BaseException:
            for n,p in targets.items():need(regular(p) in (update['originals'][n],update['replacements'][n]),'EXTERNAL_EDIT_REQUIRES_MANUAL_RECOVERY')
            for n,p in reversed(list(targets.items())):roll.atomic(p,update['originals'][n],modes[n])
            roll.save(folder/'TRANSACTION.json',dict(phase='COMPATIBILITY_RESTORED_ORIGINALS',production_execution_enabled=False));raise
        # Clear only the stopped companion's failed-unit marker; do not start it.
        unit='hilega-lifecycle-reference.service'
        if manager.state(unit)['active']=='failed':
            result=subprocess.run(['systemctl','--user','reset-failed',unit],capture_output=True,timeout=15)
            need(result.returncode==0,'FAILED_UNIT_MARKER_RESET_REQUIRES_REVIEW')
        need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in roll.UNITS),'STOPPED_UNIT_STATE_REQUIRES_REVIEW')
        receipt.update(status='COMPATIBILITY_APPLIED_SERVICES_STOPPED',dependent_pin_chain_modified=True)
        roll.save(folder/'TRANSACTION.json',dict(phase=receipt['status'],production_execution_enabled=False))
    roll.save(folder/'REPORT.json',receipt);print(json.dumps(receipt,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
