"""Stage explicit one-position policy and test admission/legacy flows; installed runtime unchanged."""
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
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED')
    return p.read_bytes()


def save(p,value):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True)
    ap.add_argument('--readiness-review',type=Path,required=True)
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'POLICY_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'PINNED_TEST_OR_UPGRADE_SOURCE_CHANGED')
    path=a.active_plan.absolute();need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED')
    plan=json.loads(regular(path));need(plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_UPGRADE_REQUIRED')
    readiness=a.readiness_review.absolute()
    need(readiness.parent==root and readiness.name.startswith('hilega-closed-readiness-batch-'),'EXACT_READINESS_REVIEW_REQUIRED')
    prior=json.loads(regular(readiness/'RESULT.json'))
    need(prior['status']=='SCOPED_CLOSED_INSTALLED_RELEASE_REGRESSION_PASS' and prior['reexecuted_cases']==99 and prior['deployed_release_sha256']==plan['release_sha256'],'CURRENT_RELEASE_READINESS_RECEIPT_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-position-policy-review-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-group2-closed-upgrade-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLOSED_STATUS_FAILED')
    status('STATUS-BEFORE');source=Path(plan['destination'])
    need(sha(regular(source/'RELEASE-MANIFEST.json'))==plan['release_sha256'],'INSTALLED_RELEASE_CHANGED')
    candidate=output/'candidate';changes=stage(source,candidate,here);save(output/'CANDIDATE-CHANGES.json',changes)
    combined=root/'hilega-group2-combined-v2';results=[]
    for label,package,target,count,context in [('position-admission',here,'test_position_policy.py',14,False),('seed-preflight',combined,'seed_preflight.py',1,True),('legacy-context-cycles',combined,'tests',74,True)]:
        print('Policy candidate validation: '+label,flush=True)
        work=output/label;work.mkdir(mode=0o700)
        env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(work),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        search=[package]
        if context:env['HILEGA_PACKAGE_B_BUNDLE']=str(candidate);search += [candidate/'backend',candidate/'runtime',combined/'fixtures']
        env['PYTHONPATH']=os.pathsep.join(map(str,search));junit=work/'TESTS.xml'
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(package),'--confcutdir='+str(package),str(package/target),'--basetemp='+str(work/'synthetic'),'--junitxml='+str(junit)],cwd=work,env=env,capture_output=True,text=True,timeout=100)
        save(work/'PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(r.returncode==0 and len(cases)==count and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'POLICY_TESTS_FAILED: '+label+'; inspect '+str(work/'PROCESS.json'))
        results.append(dict(batch=label,passed_cases=count))
    # Verify neither the sealed candidate nor original release changed during tests.
    for bundle in (source,candidate):
        manifest=json.loads(regular(bundle/'RELEASE-MANIFEST.json'))
        for name,digest in manifest['files'].items():need(sha(regular(bundle/name))==digest,'RELEASE_CHANGED_DURING_TESTS')
    status('STATUS-AFTER')
    report=dict(status='POSITION_POLICY_CANDIDATE_PASS',targeted_cases=89,new_policy_cases=14,legacy_candidate_cases_reexecuted=75,batches=results,
        max_simultaneous_positions=1,max_premium_per_entry_cents=None,daily_loss_cutoff_cents=None,
        pending_unknown_and_partial_entries_hold_position_slots=True,exit_requests_do_not_add_slots=True,
        verified_retired_cycles_excluded=True,existing_cash_and_reservation_checks_retained=True,
        automatic_capacity_increase=False,multi_position_coordinator_support_verified=False,
        candidate=str(candidate),candidate_changes=changes,
        deployed_policy_changed=False,installed_sources_modified=False,controller_resumed=False,
        actual_live_admission_tested=False,production_execution_enabled=False,group2_complete=False,
        remaining=['CANDIDATE_MANAGED_REHEARSAL_AND_CLOSED_POLICY_DEPLOYMENT','BROKER_TIMESTAMP_AND_FEE_EVIDENCE','INDEPENDENT_AUTHORITY_AND_REAL_FRESH_ENROLLMENT','FINAL_READINESS'],audit_folder=str(output))
    save(output/'RESULT.json',report)
    tracker=regular(readiness/'MILESTONES.md').decode()
    tracker+='\n## Explicit position policy\n- [x] User choice: maximum one position; premium and daily-loss caps unconfigured.\n- [x] Candidate admission tests and 75 changed-release regression cases passed.\n- [ ] Explicit position-policy guard deployed and managed validation completed.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
