"""Run the offline authority/private-factory/recovery candidate against the verified closed release."""
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
    if not ok:raise ValueError(reason)


def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_CANDIDATE_INPUT_REQUIRED')
    return p.read_bytes()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save(p,value):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True)
    ap.add_argument('--authority-review',type=Path,required=True);ap.add_argument('--authority-review-sha256',required=True)
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'AUTHORITY_CANDIDATE_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'CONTEXT_FIXTURE_OR_STATUS_TOOL_CHANGED')
    path=a.active_plan.absolute();need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED')
    plan=json.loads(regular(path));need(plan['repo']==str(root) and plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['production_execution_enabled'] is False,'CLOSED_POLICY_PLAN_REQUIRED')
    packet_path=a.authority_review.absolute();need(sha(regular(packet_path))==a.authority_review_sha256,'REVIEW_PACKET_CHANGED')
    packet=json.loads(regular(packet_path))
    need(packet['model']=='HILEGA_DEPLOYED_AUTHORITY_CONTEXT_REVIEW_V1' and packet['release_sha256']==plan['release_sha256']
         and packet['active_plan_sha256']==a.active_plan_sha256 and packet['live_arming_permitted'] is False,'EXACT_CLOSED_REVIEW_BINDING_REQUIRED')
    bundle=Path(plan['destination']);need(sha(regular(bundle/'RELEASE-MANIFEST.json'))==plan['release_sha256'],'INSTALLED_RELEASE_CHANGED')
    output=Path(tempfile.mkdtemp(prefix='hilega-authority-factory-candidate-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-position-policy-upgrade-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLOSED_POLICY_STATUS_FAILED')
    status('STATUS-BEFORE')
    combined=root/'hilega-group2-combined-v2'
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(output),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
        HILEGA_PACKAGE_B_BUNDLE=str(bundle),PYTHONPATH=os.pathsep.join(map(str,[here,here/'tests',combined/'tests',combined/'fixtures',bundle/'backend',bundle/'runtime'])))
    junit=output/'TESTS.xml'
    r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),str(here/'tests'),'--basetemp='+str(output/'synthetic'),'--junitxml='+str(junit)],cwd=output,env=env,capture_output=True,text=True,timeout=120)
    save(output/'TEST-PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==22 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'AUTHORITY_FACTORY_TESTS_FAILED; inspect '+str(output/'TEST-PROCESS.json'))
    status('STATUS-AFTER')
    report=dict(status='OFFLINE_AUTHORITY_FACTORY_RECOVERY_CANDIDATE_PASS',new_targeted_cases=22,
        prior_tests_reexecuted=False,grant_signature_and_exact_binding_tested=True,
        unknown_or_revoked_issuer_rejected=True,expiry_rechecked_for_cached_session=True,
        existing_private_loader_and_factory_two_cycle_integration_tested=True,
        native_pause_on_authority_failure_tested=True,native_recovery_without_private_context_tested=True,
        positive_paths_use_synthetic_roots_and_in_memory_gate_override=True,real_network_denied_in_tests=True,
        production_trust_root_installed=False,actual_production_issuer_implemented=False,
        live_worker_factory_wiring_modified=False,automatic_live_boot_recovery_updated=False,
        private_files_and_databases_in_tests_are_disposable=True,
        live_secret_material_created=False,production_authority_provisioned=False,live_database_enrolled=False,
        controller_resumed_on_live_database=False,installed_sources_modified=False,application_services_changed=False,
        broker_requests_issued=False,production_execution_enabled=False,production_ready=False,group2_complete=False,
        remaining=['REVIEW_AND_INSTALL_EXACT_TRUST_ROOT_GRANT_AND_PRIVATE_FILE_BINDINGS',
                   'STAGE_WORKER_FACTORY_REGISTRATION_AND_MATCHING_STARTUP_RECOVERY',
                   'RESOLVE_BROKER_TIME_AND_FEE_EVIDENCE','REAL_FRESH_SEED_AND_OWNER_ENROLLMENT','FINAL_READINESS'],
        audit_folder=str(output))
    save(output/'RESULT.json',report)
    tracker=regular(packet_path.parent/'MILESTONES.md').decode()
    tracker+='\n## Offline authority/factory/recovery implementation\n- [x] Grant-verification candidate and exact release/account/context/owner bindings tested.\n'
    tracker+='- [x] Existing private loader/factory integrated through two synthetic candidate cycles.\n'
    tracker+='- [x] Expired cached grant pauses through the native controller without a resend.\n'
    tracker+='- [ ] Production trust root/issuer, live worker wiring and boot recovery deployment.\n- [ ] Broker evidence, real fresh enrollment and final readiness.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
