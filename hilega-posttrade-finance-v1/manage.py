"""After-hours finance tests plus optional historical GET-only account charge capture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from finance import scope, need


def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)), 'REGULAR_FINANCE_INPUT_REQUIRED')
    return p.read_bytes()


def save(p, value):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream: json.dump(value,stream,indent=2);stream.write('\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True)
    ap.add_argument('--active-plan-sha256',required=True);ap.add_argument('--session',required=True)
    ap.add_argument('--evidence-review',type=Path,required=True);ap.add_argument('--broker-read',action='store_true')
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    sha=lambda raw:hashlib.sha256(raw).hexdigest()
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'FINANCE_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'CLOSED_UPGRADE_TOOL_CHANGED')
    path=a.active_plan.absolute();need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED')
    plan=json.loads(regular(path));need(plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'DEPLOYED_CLOSED_PLAN_REQUIRED')
    prior=a.evidence_review.absolute();need(prior.parent==root and prior.name.startswith('hilega-group2-evidence-review-'),'EXACT_PRIOR_EVIDENCE_FOLDER_REQUIRED')
    receipt=json.loads(regular(prior/'RESULT.json'))
    need(receipt['status']=='CLOSED_EVIDENCE_CAPTURE_COMPLETE_REVIEW_REQUIRED' and receipt['source_process_stable'] is True,'PASSED_STRUCTURAL_EVIDENCE_REVIEW_REQUIRED')
    query=scope(a.session)
    output=Path(tempfile.mkdtemp(prefix='hilega-posttrade-finance-review-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-group2-closed-upgrade-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','DEPLOYED_RUNTIME_STATUS_FAILED')
    status('STATUS-BEFORE')
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(Path.home()),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    junit=output/'TESTS.xml'
    r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),str(here/'test_finance.py'),'--basetemp='+str(output/'tests'),'--junitxml='+str(junit)],cwd=here,env=env,capture_output=True,text=True,timeout=60)
    save(output/'TEST-LOG.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==8 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'FINANCE_TESTS_FAILED')
    summary=None;captured=False;stable=None
    if a.broker_read:
        def pid():return int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip())
        before=pid();need(before>0,'RUNNING_SOURCE_REQUIRED')
        r=subprocess.run([sys.executable,'-B',str(here/'capture.py'),'--repo',str(root),'--bundle',plan['destination'],'--adapter',plan['adapter_db'],'--pid',str(before),'--output',str(output),'--session',a.session,'--evidence-review',str(prior)],cwd=root,env=env,capture_output=True,text=True,timeout=140)
        try:summary=json.loads(r.stdout)
        except ValueError:summary=dict(status='POSTTRADE_CAPTURE_BLOCKED',reason='PROCESS_FAILED')
        if r.stderr:save(output/'PRIVATE-CAPTURE-DIAGNOSTIC.json',dict(stderr=r.stderr))
        stable=before==pid();captured=r.returncode==0 and stable
    status('STATUS-AFTER')
    report=dict(status='POSTTRADE_AGGREGATE_CAPTURE_REVIEW_REQUIRED' if captured else ('OFFLINE_FINANCE_CANDIDATE_PASS' if not a.broker_read else 'POSTTRADE_CAPTURE_BLOCKED'),
        new_finance_tests=8,prior_tests_reexecuted=False,session=a.session,query=query,
        historical_get_requested=a.broker_read,historical_capture_completed=captured,source_process_stable=stable,
        finance_review=summary,broker_timezone_contract_confirmed=False,actual_fees_reconciled=False,
        per_trade_fee_attribution_verified=False,net_pnl_certified=False,strategy_ownership_verified=False,
        reservation_release_executed=False,controller_resumed=False,application_sql_mutations_issued=False,
        application_services_changed=False,orders_sent=False,production_execution_enabled=False,
        group2_complete=False,audit_folder=str(output))
    save(output/'RESULT.json',report)
    tracker=regular(prior/'MILESTONES.md').decode()+'\n## Historical finance work\n- [x] Eight offline finance schema/arithmetic tests passed.\n'
    tracker+=('- [x]' if captured else '- [ ]')+' Account-bound historical F&O aggregate charges captured.\n'
    tracker+='- [ ] Report finality and exact per-trade fee attribution verified.\n- [ ] Actual net P&L and cash-release readiness verified.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2));return 0 if captured or not a.broker_read else 2


if __name__=='__main__':raise SystemExit(main())
