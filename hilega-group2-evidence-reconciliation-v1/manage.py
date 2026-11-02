"""Current closed upgrade status + GET-only timestamp and structural financial evidence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from hashlib import sha256


def need(ok, reason):
    if not ok: raise ValueError(reason)


def regular(path):
    need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)), 'REGULAR_INPUT_REQUIRED')
    return path.read_bytes()


def save(path, value):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream: json.dump(value,stream,indent=2);stream.write('\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--active-plan',type=Path,required=True)
    ap.add_argument('--active-plan-sha256',required=True)
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items(): need(sha256(regular(here/name)).hexdigest()==digest,'PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items(): need(sha256(regular(root/name)).hexdigest()==digest,'UPGRADE_TOOL_CHANGED')
    path=a.active_plan.absolute();raw=regular(path)
    need(sha256(raw).hexdigest()==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED')
    plan=json.loads(raw)
    need(plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_UPGRADE_PLAN_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-group2-evidence-review-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-group2-closed-upgrade-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_UPGRADE_STATUS_FAILED')
    status('STATUS-BEFORE')
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(Path.home()),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    junit=output/'TESTS.xml'
    r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),str(here/'test_activity_review.py'),'--basetemp='+str(output/'tests'),'--junitxml='+str(junit)],cwd=here,env=env,capture_output=True,text=True,timeout=60)
    save(output/'TEST-LOG.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==8 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'ACTIVITY_TESTS_FAILED')
    def pid():
        return int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip())
    before=pid();need(before>0,'RUNNING_SOURCE_REQUIRED')
    capture=subprocess.run([sys.executable,'-B',str(here/'capture_audit.py'),'--repo',str(root),'--bundle',plan['destination'],'--adapter',plan['adapter_db'],'--pid',str(before),'--output',str(output)],cwd=root,env=env,capture_output=True,text=True,timeout=150)
    try: summary=json.loads(capture.stdout)
    except ValueError: summary=dict(status='EVIDENCE_CAPTURE_BLOCKED',reason='CAPTURE_PROCESS_FAILED')
    if capture.stderr: save(output/'PRIVATE-CAPTURE-ERROR.json',dict(stderr=capture.stderr))
    status('STATUS-AFTER');stable=before==pid()
    passed=capture.returncode==0 and stable
    review=summary.get('activity_review')
    report=dict(status='CLOSED_EVIDENCE_CAPTURE_COMPLETE_REVIEW_REQUIRED' if passed else 'CLOSED_EVIDENCE_CAPTURE_BLOCKED',
        new_activity_tests=8,prior_tests_reexecuted=False,source_process_stable=stable,
        capture=summary,activity_review=review,broker_timezone_contract_confirmed=False,
        timestamps_corrected=False,fees_endpoint_called=False,actual_fees_reconciled=False,
        strategy_ownership_verified=False,controller_resumed=False,
        live_database_mutations_issued=False,application_services_changed=False,
        orders_sent=False,production_execution_enabled=False,group2_complete=False,
        audit_folder=str(output))
    save(output/'RESULT.json',report)
    # Reuse current deployed checklist; do not inherit unchecked installation state
    # from the package template. Only add the newly evidenced audit milestone.
    tracker=regular(path.parent/'MILESTONES.md').decode()
    tracker+='\n## Latest combined evidence review\n- [x] Structural account review tests: 8 passed.\n'
    tracker+=('- [x]' if passed else '- [ ]')+' Fresh GET-only timestamp/account capture with stable source process.\n'
    tracker+='- [ ] Broker timezone contract confirmed.\n- [ ] Actual fees and strategy ownership reconciled.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    save(output/'SUPPORT-REVIEW.json',dict(subject='Confirm timezone of order and trade timestamp fields',
        comparison=summary,questions=['Which timezone applies to each naive timestamp field?',
        'Why do matched order and trade execution fields differ by exactly 19800 seconds?',
        'Which field is authoritative for execution chronology?'],support_message_sent=False))
    print(json.dumps(report,indent=2))
    return 0 if passed else 2


if __name__=='__main__': raise SystemExit(main())
