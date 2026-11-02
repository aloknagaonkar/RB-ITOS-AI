"""One GET-only timestamp audit and support evidence packet; never changes the running adapter."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

def need(ok,reason):
    if not ok:raise ValueError(reason)
def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_AUDIT_INPUT_REQUIRED');return p.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(p,value):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,required=True);a=p.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'TIMESTAMP_AUDIT_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'VERIFIED_SOURCE_CODE_CHANGED')
    prior_raw=regular(root/'hilega-group2-combined-v2/VM-VALIDATION.json');prior=json.loads(prior_raw)
    need(prior['targeted_cases']==74 and prior['seed_preflight_cases']==1 and prior['failed']==prior['skipped']==0 and prior['candidate_test_batch_complete'] is True,'PASSED_COMBINED_GROUP2_BATCH_REQUIRED')
    old=json.loads(regular(root/'hilega-recovery-install-v1/VM-VALIDATION.json'));path=Path(old['plan']);need(sha(regular(path))==old['plan_sha256'],'INSTALLED_RECOVERY_PLAN_CHANGED')
    installed=json.loads(regular(path));active=Path(installed['active_plan']);raw=regular(active);need(sha(raw)==installed['active_plan_sha256'],'ACTIVE_CLOSED_PLAN_CHANGED');plan=json.loads(raw)
    output=Path(tempfile.mkdtemp(prefix='hilega-broker-time-audit-',dir=root));output.chmod(0o700);(output/'.gitignore').write_text('*\n');(output/'PRIOR-GROUP2-RECEIPT.json').write_bytes(prior_raw)
    def health(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-recovery-install-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',old['plan_sha256']],cwd=root,capture_output=True,text=True,timeout=90)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_RECOVERY_INSTALLED_RUNNING','CLOSED_RECOVERY_STATUS_FAILED')
    health('CLOSED-BEFORE')
    junit=output/'TESTS.xml';code=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_compare.py'),'--junitxml='+str(junit)],cwd=output).returncode
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else [];need(code==0 and len(cases)==8 and all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in cases),'TIMESTAMP_AUDIT_TESTS_FAILED')
    bundle=Path(plan['destination']);manifest_raw=regular(bundle/'RELEASE-MANIFEST.json');need(sha(manifest_raw)==plan['release_manifest_sha256'],'APPROVED_RELEASE_CHANGED')
    for name,digest in json.loads(manifest_raw)['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts and sha(regular(bundle/rel))==digest,'APPROVED_RELEASE_INPUT_CHANGED')
    pid=int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip());need(pid>0,'RUNNING_SOURCE_WORKER_REQUIRED')
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(Path.home()),PYTHONDONTWRITEBYTECODE='1')
    r=subprocess.run([sys.executable,'-B',str(here/'capture_audit.py'),'--repo',str(root),'--bundle',str(bundle),'--adapter',plan['adapter_db'],'--pid',str(pid),'--output',str(output)],cwd=root,env=env,capture_output=True,text=True,timeout=150)
    try:capture=json.loads(r.stdout)
    except ValueError:capture=dict(status='TIMESTAMP_AUDIT_BLOCKED',reason='AUDIT_PROCESS_FAILED')
    if r.stderr:save(output/'PRIVATE-PROCESS-DIAGNOSTIC.json',dict(stderr=r.stderr))
    health('CLOSED-AFTER')
    current_pid=int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip())
    source_stable=current_pid==pid
    support=dict(subject='Please confirm timestamp semantics across order and trade endpoints',
        endpoints=['GET /v2/order/retrieve-all','GET /v2/order/trades/get-trades-for-day','GET /v2/order/trades?order_id=…','GET /v2/order/history?order_id=…'],
        questions=['What timezone does exchange_timestamp use on each trade endpoint when its string has no offset?',
            'Why can the exchange timestamp be exactly 19,800 seconds later than the matching order timestamp?',
            'Which field and representation should clients use for authoritative execution chronology?'],
        anonymized_comparison=capture,contains_credentials=False,automatically_sent=False)
    save(output/'SUPPORT-REVIEW.json',support)
    report=dict(status='TIMESTAMP_CROSS_ENDPOINT_AUDIT_COMPLETE_REVIEW_REQUIRED' if r.returncode==0 and source_stable else 'TIMESTAMP_AUDIT_REQUIRES_REVIEW',
        new_test_cases=8,prior_combined_group2_cases_passed=74,prior_seed_preflight_passed=1,prior_candidate_tests_reexecuted=False,
        capture=capture,source_process_stable_during_audit=source_stable,broker_timezone_contract_confirmed=False,
        timestamps_corrected=False,installed_normalizer_modified=False,controller_resumed=False,
        live_database_mutations_issued=False,application_services_changed=False,orders_sent=False,
        support_summary_created=True,support_message_sent=False,group2_complete=False,
        production_execution_enabled=False,production_ready=False,audit_folder=str(output))
    save(output/'RESULT.json',report);(here/'VM-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if r.returncode==0 and source_stable else 2
if __name__=='__main__':raise SystemExit(main())
