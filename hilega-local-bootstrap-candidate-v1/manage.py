"""Offline signed local-enrollment/recovery implementation tests; no live provisioning action."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from stage import stage,sha,need


def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_BOOTSTRAP_INPUT_REQUIRED')
    return p.read_bytes()


def save(p,value):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--current-plan',type=Path,required=True);ap.add_argument('--current-plan-sha256',required=True)
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'BOOTSTRAP_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'STATUS_TOOL_OR_FIXTURE_CHANGED')
    path=a.current_plan.absolute();need(sha(regular(path))==a.current_plan_sha256,'CURRENT_PLAN_CHANGED')
    plan=json.loads(regular(path));need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_CURRENT_PLAN_REQUIRED')
    source=Path(plan['destination']);need(sha(regular(source/'RELEASE-MANIFEST.json'))==plan['release_sha256'],'DEPLOYED_RELEASE_CHANGED')
    output=Path(tempfile.mkdtemp(prefix='hilega-local-bootstrap-review-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-worker-qualification-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.current_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_WORKER_STATUS_FAILED')
    status('STATUS-BEFORE');candidate=output/'candidate';changes=stage(source,candidate,here);save(output/'CANDIDATE-CHANGES.json',changes)
    combined=root/'hilega-group2-combined-v2'
    for label,package,target,count in [('seed-preflight',combined,'seed_preflight.py',1),('signed-local-bootstrap',here,'tests',19)]:
        print('Offline local-bootstrap validation: '+label,flush=True)
        work=output/label;work.mkdir(mode=0o700)
        paths=[package,combined/'tests',combined/'fixtures',candidate/'backend',candidate/'runtime']
        env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(work),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',HILEGA_PACKAGE_B_BUNDLE=str(candidate),PYTHONPATH=os.pathsep.join(map(str,paths)))
        junit=work/'TESTS.xml'
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(package),'--confcutdir='+str(package),str(package/target),'--basetemp='+str(work/'synthetic'),'--junitxml='+str(junit)],cwd=work,env=env,capture_output=True,text=True,timeout=120)
        save(work/'PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(r.returncode==0 and len(cases)==count and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'LOCAL_BOOTSTRAP_TESTS_FAILED: '+label+'; inspect '+str(work/'PROCESS.json'))
    for bundle in (source,candidate):
        manifest=json.loads(regular(bundle/'RELEASE-MANIFEST.json'))
        for name,digest in manifest['files'].items():need(sha(regular(bundle/name))==digest,'SOURCE_OR_CANDIDATE_CHANGED_DURING_TESTS')
    status('STATUS-AFTER')
    report=dict(status='SIGNED_LOCAL_BOOTSTRAP_AND_COMMIT_RECOVERY_CANDIDATE_PASS',new_bootstrap_cases=19,seed_preflight_cases=1,
        signed_disabled_enrollment_tested_with_real_order_gate_closed=True,
        positive_bootstrap_tests_do_not_override_order_gate=True,original_gated_provisioner_preserved=True,
        approval_scoped_to_account_release_policy_paths_seed_lease_and_state=True,
        precommit_interruption_and_expiry_owner_rollback_tested=True,
        postcommit_recovery_reuses_existing_key_and_owner=True,
        new_source_lease_requires_explicit_rebinding=True,automatic_key_rotation_or_reenrollment=False,
        candidate=str(candidate),candidate_changes=changes,live_apply_available=False,
        live_secret_material_created=False,production_trust_root_provisioned=False,live_database_enrolled=False,
        worker_process_dynamic_bootstrap_end_to_end_verified=False,controller_resumed_on_live_database=False,
        application_services_changed=False,installed_sources_modified=False,broker_requests_issued=False,
        production_execution_enabled=False,production_ready=False,group2_complete=False,
        remaining=['SIGNED_BOOTSTRAP_WORKER_HANDOFF_AND_LEASE_REBINDING','MANAGED_QUALIFICATION_AND_REVIEWED_DEPLOYMENT',
            'ACTUAL_TRUST_ROOT_PROVISIONING','BROKER_TIME_AND_FEE_RESOLUTION','REAL_FRESH_ENROLLMENT_AND_FINAL_READINESS'],audit_folder=str(output))
    save(output/'RESULT.json',report)
    tracker=regular(path.parent/'MILESTONES.md').decode()
    tracker+='\n## Signed local bootstrap candidate\n- [x] Explicit local-only approval permits synthetic disabled enrollment while the real order gate stays closed.\n'
    tracker+='- [x] Precommit rollback, blocked duplicate-key retry and postcommit same-key recovery tested.\n'
    tracker+='- [ ] Worker-process signed handoff and explicit new-lease rebinding implemented/qualified.\n- [ ] New local bootstrap code deployed after managed qualification.\n- [ ] Real trust provisioning, broker evidence and fresh real enrollment.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
