"""Combine private-file implementation tests, native recovery, staged worker hooks and exact upgrade planning."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from stage import stage


def prepare_batch(a,root,here,fd,old,m,h):
    need,regular,sha,save,load=h.need,h.regular,h.sha,h.save,h.load
    need(a.current_plan is not None and a.current_plan_sha256 and a.authority_candidate_review is not None
         and a.authority_review is not None and a.authority_review_sha256,'CURRENT_PLAN_AND_PASSED_AUTHORITY_REVIEWS_REQUIRED')
    current_path=a.current_plan.absolute();need(sha(regular(current_path))==a.current_plan_sha256,'CURRENT_PLAN_CHANGED')
    current=load(current_path);need(current['repo']==str(root) and current['production_execution_enabled'] is False,'CURRENT_CLOSED_PLAN_REQUIRED')
    need(load(current_path.parent/'TRANSACTION.json')['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_UPGRADE_NOT_RUNNING')
    h.verify_inputs(current,installed=True);h.verify_bundle(Path(current['destination']),current['release_sha256'])
    prior=a.authority_candidate_review.absolute();need(prior.parent==root and prior.name.startswith('hilega-authority-factory-candidate-'),'EXACT_PRIOR_AUTHORITY_CANDIDATE_REQUIRED')
    passed=load(prior/'RESULT.json');need(passed['status']=='OFFLINE_AUTHORITY_FACTORY_RECOVERY_CANDIDATE_PASS' and passed['new_targeted_cases']==22,'PASSED_22_CASE_AUTHORITY_CANDIDATE_REQUIRED')
    packet_path=a.authority_review.absolute();need(sha(regular(packet_path))==a.authority_review_sha256,'AUTHORITY_REVIEW_CHANGED')
    packet=load(packet_path);need(packet['release_sha256']==current['release_sha256'] and packet['active_plan_sha256']==a.current_plan_sha256 and packet['live_arming_permitted'] is False,'AUTHORITY_REVIEW_RELEASE_CHANGED')
    review=Path(tempfile.mkdtemp(prefix='hilega-trust-worker-review-',dir=root));review.chmod(0o700)
    (review/'.gitignore').write_text('*\n')
    old.wait_health(Path(current['application_db']),'STATUS_OBSERVATION',m.Systemd(),list(m.UNITS),timeout=35)
    m.require_empty_closed_baseline(Path(current['application_db']),Path(current['adapter_db']))
    source=Path(current['destination']);candidate=review/'candidate';changes=stage(source,candidate,here)
    save(review/'CANDIDATE-CHANGES.json',changes)
    combined=root/'hilega-group2-combined-v2';prior_code=root/'hilega-authority-factory-candidate-v1'
    for label,package,target,count,is_new in [('private-file-and-worker-tests',here,'tests',16,True),('seed-preflight',combined,'seed_preflight.py',1,False)]:
        print('Combined trust/worker validation: '+label,flush=True)
        work=review/label;work.mkdir(mode=0o700)
        paths=[package,here/'tests',combined/'tests',combined/'fixtures',prior_code/'tests',candidate/'backend',candidate/'runtime'] if is_new else [combined,candidate/'backend',candidate/'runtime',combined/'fixtures']
        env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(work),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',HILEGA_PACKAGE_B_BUNDLE=str(candidate),PYTHONPATH=os.pathsep.join(map(str,paths)))
        junit=work/'TESTS.xml'
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(package),'--confcutdir='+str(package),str(package/target),'--basetemp='+str(work/'synthetic'),'--junitxml='+str(junit)],cwd=work,env=env,capture_output=True,text=True,timeout=120)
        save(work/'PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(r.returncode==0 and len(cases)==count and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'TRUST_WORKER_TESTS_FAILED: '+label+'; inspect '+str(work/'PROCESS.json'))
    clean=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(review),PYTHONDONTWRITEBYTECODE='1')
    r=subprocess.run([sys.executable,'-I','-B',str(here/'startup_rehearsal.py'),'--release',str(candidate),'--output',str(review/'native-startup')],cwd=review,env=clean,capture_output=True,text=True,timeout=60)
    save(review/'NATIVE-STARTUP.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    need(r.returncode==0,'NATIVE_STARTUP_RECOVERY_FAILED: '+r.stderr[-3500:])
    need(json.loads(r.stdout)['status']=='NATIVE_REGISTRATION_STARTUP_RECOVERY_PASS','NATIVE_STARTUP_RECOVERY_RECEIPT_REQUIRED')
    h.verify_bundle(source,current['release_sha256']);h.verify_bundle(candidate,changes['release_sha256'])
    h.atomic(review/'MILESTONES.md',regular(prior/'MILESTONES.md'),0o600)
    with (review/'MILESTONES.md').open('a') as f:
        f.write('\n## Combined trust-file and worker implementation\n- [x] Pinned private registry/grant providers and candidate issuer tested.\n- [x] File-bound worker factory integrated through two synthetic cycles.\n- [x] Native startup pause verified with already-paused and armed disposable controllers.\n- [ ] Disabled-by-default worker hook deployed.\n- [ ] Production trust roots, real grant/context provisioning and enabled factory deployment.\n')
    receipt=dict(status='TRUST_WORKER_IMPLEMENTATION_CANDIDATE_PASS',targeted_cases=17,new_file_binding_cases=16,seed_preflight_cases=1,
                 native_startup_scenarios=2,candidate=str(candidate),candidate_changes=changes,installed_sources_modified=False,
                 prior_authority_cases_reexecuted=False,live_secret_material_created=False,production_authority_provisioned=False,
                 factory_registration_enabled=False,production_execution_enabled=False,
                 source_review_bindings={str(prior/'RESULT.json'):sha(regular(prior/'RESULT.json')),str(packet_path):a.authority_review_sha256})
    save(review/'RESULT.json',receipt)
    # The shared exact-plan preparation performs candidate native recovery,
    # managed default-worker startup/restart, unit syntax, current-state binding,
    # and emits the executable closed plan. No apply is performed by this branch.
    a.policy_review=review
    from plan_prepare import prepare
    prepare(a,root,here,fd,old,m,h)
