"""Bounded post-deploy checkpoint plus isolated execution-factory candidate tests. No install."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import hashlib

APPROVED='55ba58b26771b81ade1511e0b9f3324767fbc6768c2e2fa4d6ee3e6acbad4965'


def need(ok,reason):
    if not ok:raise SystemExit('STOP: '+reason)


def raw(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'regular source required')
    return p.read_bytes()


def sha(value):return hashlib.sha256(value).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--integration',action='store_true',help='222 cases including previous 212')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    own=json.loads(raw(folder/'MANIFEST.json'))
    for n,d in own.items():need(sha(raw(folder/n))==d,'PACKAGE_CHANGED: '+n)
    pins=json.loads(raw(folder/'BASELINE_PINS.json'))
    plan_path=repo/'hilega-closed-rollout-plan-qz5zlrk2/PLAN.json';plan_raw=raw(plan_path)
    need(sha(plan_raw)==APPROVED,'exact approved deployed plan required');plan=json.loads(plan_raw)
    need(plan['repo']==str(repo),'approved repository changed')
    for e in plan['files']:pins[e['name']]=e['new_sha256']
    for n,d in pins.items():need(sha(raw(repo/n))==d,'POSTDEPLOY_BASELINE_CHANGED: '+n)
    compat=repo/'hilega-reference-compatibility-2jkluc07'
    code=subprocess.run([sys.executable,str(folder/'checkpoint.py'),'--repo',str(repo),'--plan',str(plan_path),
        '--compatibility-review',str(compat)],cwd=repo).returncode
    need(code==0,'bounded post-deployment checkpoint requires review; services unchanged')
    checkpoint=json.loads(raw(plan_path.parent/'POST-DEPLOYMENT-BOUNDED.json'))
    need(checkpoint['status']=='CLOSED_POSTDEPLOY_CHECK_PASS','running closed baseline required')
    names=('hilega-exclusive-route-v1','hilega-durable-coordinator-v1','hilega-second-application-cycle-v3',
        'hilega-history-aware-preparation-v1','hilega-application-cycle-close-v1')
    route,coordinator,second,preparation,base=[repo/n for n in names];v2=repo/'hilega-closed-release-v2'
    prior=json.loads(raw(v2/'VM-VALIDATION.json'))
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases')==212
         and prior.get('broader_integration_reexecuted') is True,'prior 212-case integration required')
    existing=Path(prior['stage']);existing_pins=json.loads(raw(Path(prior['review_folder'])/'STAGED-MANIFEST.json'))
    parent=Path(tempfile.mkdtemp(prefix='hilega-session-factory-stage-',dir=repo));stage=parent/'candidate';stage.mkdir(mode=0o700)
    for n,d in existing_pins.items():
        p=Path(n);need(not p.is_absolute() and '..' not in p.parts,'invalid stage path')
        data=raw(existing/p);need(sha(data)==d,'previous stage changed')
        target=stage/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    worker=stage/'scripts/hilega_production_simulator_bridge.py';text=worker.read_text()
    old='from market_lab.hilega_exclusive_closed_route_v1 import closed_poll'
    need(text.count(old)==1 and text.count('result=closed_poll(bridge,a.source)')==1,'exact closed worker anchor required')
    text=text.replace(old,'from market_lab.hilega_execution_session_factory_v1 import worker_poll',1)
    text=text.replace('result=closed_poll(bridge,a.source)','result=worker_poll(bridge,a.source)',1);worker.write_text(text)
    module=stage/'backend/market_lab/hilega_execution_session_factory_v1.py'
    module.write_bytes(raw(folder/'execution_session_factory_v1.py'))
    for p in [worker,module,*folder.glob('*.py')]:compile(p.read_bytes(),str(p),'exec')
    staged={str(p.relative_to(stage)):sha(p.read_bytes()) for p in stage.rglob('*.py')}
    (parent/'STAGED-MANIFEST.json').write_text(json.dumps(staged,indent=2)+'\n')
    # Load the proven staged Source/coordinator only inside the pytest subprocess.
    bootstrap="import os,sys,runpy\nfrom pathlib import Path\nstage=Path(os.environ['HILEGA_EXCLUSIVE_TEST_STAGE']).resolve()\nname='closed_application_coordinator_v1'\nif name in sys.modules:\n    assert Path(sys.modules[name].__file__).resolve()==stage/'closed_application_coordinator_v1.py'\nelse:\n    runpy.run_path("+repr(str(route/'conftest.py'))+")\n"
    (parent/'conftest.py').write_text(bootstrap)
    test_copy=parent/'test_session_factory.py';test_copy.write_bytes(raw(folder/'test_session_factory.py'))
    selected=[]
    if args.integration:
        selected += [str(route/'test_exclusive_closed_route_v1.py'),str(coordinator/'test_closed_application_coordinator_v1.py'),
            str(second/'test_second_application_cycle_v1.py'),str(preparation/'test_history_aware_preparation_v1.py')]
        selected += [str(base/n) for n in ('test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
        selected.append(str(v2/'test_closed_release.py'))
    selected.append(str(test_copy))
    environment=dict(os.environ);environment['PYTHONPATH']=os.pathsep.join(map(str,[folder,parent,v2,route,coordinator,second,preparation,base,repo/'backend',repo/'tests',repo]))
    environment['HILEGA_EXCLUSIVE_TEST_STAGE']=str(stage);environment['HILEGA_RELEASE_STAGE']=str(stage)
    with tempfile.TemporaryDirectory(prefix='hilega-factory-test-results-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=environment).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(raw(repo/n))==d for n,d in pins.items()) and all(sha(raw(folder/n))==d for n,d in own.items())
    stage_ok=all(sha(raw(stage/n))==d for n,d in staged.items())
    passed=code==0 and len(cases)==(222 if args.integration else 10) and failed==skipped==0 and unchanged and stage_ok
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='CLOSED_EXECUTION_SESSION_FACTORY_CANDIDATE',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        prior_integration_cases_passed=212,broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,
        bounded_postdeployment_checkpoint_passed=True,pinned_postdeployment_sources_unchanged=unchanged,
        execution_factory_candidate_implemented=True,worker_factory_callsite_staged=True,
        factory_context_loader_is_python_injection_only=True,production_context_loader_configured=False,
        credential_files_opened_by_factory=False,positive_order_transport_intercepted=True,
        stage=str(stage),staged_sources_unchanged=stage_ok,
        installed_sources_modified=False,services_changed=False,execution_factory_deployed=False,
        actual_broker_network_validated=False,production_execution_enabled=False,production_ready=False)
    destination=folder/'VM-VALIDATION.json';destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',destination);return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
