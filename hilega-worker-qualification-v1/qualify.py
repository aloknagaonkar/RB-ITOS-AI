import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def prepare_batch(a,root,here,fd,old,m,h):
    need,regular,sha,save,load=h.need,h.regular,h.sha,h.save,h.load
    need(a.current_plan is not None and a.current_plan_sha256,'CURRENT_TRUST_WORKER_PLAN_REQUIRED')
    path=a.current_plan.absolute();need(sha(regular(path))==a.current_plan_sha256,'CURRENT_PLAN_CHANGED')
    plan=load(path);need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    need(load(path.parent/'TRANSACTION.json')['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLOSED_UPGRADE_NOT_RUNNING')
    h.verify_inputs(plan,installed=True);source=Path(plan['destination']);original=h.verify_bundle(source,plan['release_sha256'])
    review=Path(tempfile.mkdtemp(prefix='hilega-worker-health-review-',dir=root));review.chmod(0o700)
    (review/'.gitignore').write_text('*\n');candidate=review/'candidate';candidate.mkdir(mode=0o700)
    files=dict(original['files'])
    for name,digest in files.items():
        target=candidate/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);raw=regular(source/name)
        need(sha(raw)==digest,'INSTALLED_SOURCE_CHANGED');target.write_bytes(raw)
    name='runtime/worker_binding.py'
    old_text=regular(source/name).decode();new_text=regular(here/'worker_binding.py').decode()
    need(old_text.count('    return _DEFAULT.poll(source,journal)')==1,'CURRENT_DISPATCH_ANCHOR_CHANGED')
    expected=old_text.replace('    return _DEFAULT.poll(source,journal)','    return poll_with_journal_health(_DEFAULT,source,journal)')
    need(new_text.startswith(expected) and '\ndef poll_with_journal_health(' in new_text[len(expected):],'REVIEWED_HEARTBEAT_CHANGE_REQUIRED')
    (candidate/name).write_text(new_text);files[name]=sha(regular(candidate/name))
    dependency='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';deps=load(candidate/dependency)
    need(deps[name]==original['files'][name],'OLD_WORKER_DEPENDENCY_CHANGED');deps[name]=files[name]
    (candidate/dependency).write_text(json.dumps(deps,indent=2)+'\n');files[dependency]=sha(regular(candidate/dependency))
    for relative,digest in deps.items():need(sha(regular(candidate/relative))==digest,'CANDIDATE_DEPENDENCY_CHANGED')
    manifest=dict(original,files=files,worker_journal_health_candidate=True)
    (candidate/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for p in candidate.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in candidate.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    candidate.chmod(0o500)
    combined=root/'hilega-group2-combined-v2';authority=root/'hilega-authority-factory-candidate-v1';trust=root/'hilega-trust-worker-batch-v2'
    for label,package,target,count in [('worker-health-and-lease',here,'tests',8),('seed-preflight',combined,'seed_preflight.py',1)]:
        print('Offline worker qualification: '+label,flush=True)
        work=review/label;work.mkdir(mode=0o700)
        paths=[package,here/'tests',combined/'tests',combined/'fixtures',authority/'tests',trust/'tests',candidate/'backend',candidate/'runtime'] if package==here else [combined,candidate/'backend',candidate/'runtime',combined/'fixtures']
        env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(work),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',HILEGA_PACKAGE_B_BUNDLE=str(candidate),PYTHONPATH=os.pathsep.join(map(str,paths)))
        junit=work/'TESTS.xml'
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(package),'--confcutdir='+str(package),str(package/target),'--basetemp='+str(work/'synthetic'),'--junitxml='+str(junit)],cwd=work,env=env,capture_output=True,text=True,timeout=120)
        save(work/'PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(r.returncode==0 and len(cases)==count and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'WORKER_QUALIFICATION_FAILED: '+label+'; inspect '+str(work/'PROCESS.json'))
    h.verify_bundle(source,plan['release_sha256']);h.verify_bundle(candidate,sha(regular(candidate/'RELEASE-MANIFEST.json')))
    h.atomic(review/'MILESTONES.md',regular(path.parent/'MILESTONES.md'),0o600)
    with (review/'MILESTONES.md').open('a') as f:
        f.write('\n## Worker health and lease qualification\n- [x] Verified journal time retained without cursor consumption or manufactured freshness.\n- [x] Closed-gate enabled-registration heartbeat and cached stale-lease rejection tested.\n- [ ] Worker heartbeat metadata fix deployed.\n- [ ] Configured factory process bootstrap/current-lease handoff qualified end to end.\n')
    changes=dict(changed_modules=[name],changed_dependency_manifest=dependency,release_sha256=sha(regular(candidate/'RELEASE-MANIFEST.json')),
                 factory_registration_enabled=False,execution_port_bytes_unchanged=True)
    receipt=dict(status='WORKER_HEALTH_QUALIFICATION_CANDIDATE_PASS',targeted_cases=9,new_qualification_cases=8,seed_preflight_cases=1,
                 candidate=str(candidate),candidate_changes=changes,installed_sources_modified=False,production_execution_enabled=False,
                 configured_factory_process_end_to_end_tested=False,source_review_bindings={str(path):a.current_plan_sha256})
    save(review/'RESULT.json',receipt)
    a.policy_review=review
    from plan_prepare import prepare
    prepare(a,root,here,fd,old,m,h)
