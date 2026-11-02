"""Scoped installed-release regression and public authority/policy preparation; no broker GETs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def need(ok, reason):
    if not ok: raise ValueError(reason)


def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)), 'REGULAR_BATCH_INPUT_REQUIRED')
    return p.read_bytes()


def sha(raw): return hashlib.sha256(raw).hexdigest()


def save(p, value):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True)
    ap.add_argument('--active-plan-sha256',required=True);ap.add_argument('--finance-review',type=Path,required=True)
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'BATCH_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'TEST_OR_TOOL_SOURCE_CHANGED')
    path=a.active_plan.absolute();need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED')
    plan=json.loads(regular(path));need(plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_DEPLOYED_RELEASE_REQUIRED')
    bundle=Path(plan['destination']);raw=regular(bundle/'RELEASE-MANIFEST.json');need(sha(raw)==plan['release_sha256'],'DEPLOYED_RELEASE_CHANGED')
    manifest=json.loads(raw)
    def verify_release():
        for name,digest in manifest['files'].items():
            rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'UNSAFE_RELEASE_PATH')
            need(sha(regular(bundle/rel))==digest,'DEPLOYED_FILE_CHANGED: '+name)
        reg=json.loads(regular(bundle/'CLOSED-REGISTRATION.json'))
        need(reg['execution_factory_configured'] is False and reg['production_execution_enabled'] is False,'FACTORY_DISABLED_REGISTRATION_REQUIRED')
    verify_release()
    finance_folder=a.finance_review.absolute()
    need(finance_folder.parent==root and finance_folder.name.startswith('hilega-posttrade-finance-review-'),'EXACT_FINANCE_REVIEW_FOLDER_REQUIRED')
    finance_raw=regular(finance_folder/'RESULT.json');finance=json.loads(finance_raw)
    need(finance['historical_capture_completed'] is True and finance['source_process_stable'] is True,'PRIOR_HISTORICAL_CAPTURE_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-closed-readiness-batch-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-group2-closed-upgrade-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CLOSED_RUNTIME_STATUS_FAILED')
    status('STATUS-BEFORE')
    combined=root/'hilega-group2-combined-v2'
    batches=[('seed-preflight',combined,'seed_preflight.py',1,True),
             ('context-policy-timestamp',combined,'tests',74,True),
             ('file-transactions',root/'hilega-group2-closed-upgrade-v1','test_transaction.py',8,False),
             ('account-structure',root/'hilega-group2-evidence-reconciliation-v1','test_activity_review.py',8,False),
             ('historical-finance',root/'hilega-posttrade-finance-v1','test_finance.py',8,False)]
    results=[]
    for label,package,target,expected,context in batches:
        print('Offline installed-release batch: '+label,flush=True)
        work=output/label;work.mkdir(mode=0o700)
        env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(work),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        search=[package]
        if context:
            env['HILEGA_PACKAGE_B_BUNDLE']=str(bundle)
            search += [bundle/'backend',bundle/'runtime',combined/'fixtures']
        env['PYTHONPATH']=os.pathsep.join(map(str,search))
        junit=work/'TESTS.xml'
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(package),'--confcutdir='+str(package),str(package/target),'--basetemp='+str(work/'synthetic-state'),'--junitxml='+str(junit)],cwd=work,env=env,capture_output=True,text=True,timeout=100)
        save(work/'PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        passed=r.returncode==0 and len(cases)==expected and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases)
        need(passed,'BATCH_FAILED: '+label+'; inspect '+str(work/'PROCESS.json'))
        results.append(dict(batch=label,passed_cases=expected,context_tests_use_deployed_module_bytes=context))
    verify_release();status('STATUS-AFTER')
    # Exact account scope is read from existing adapter metadata, without reading
    # any key/token or creating Store/schema objects.
    with sqlite3.connect(Path(plan['adapter_db']).as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
    need(meta['mode']=='LIVE_CLOSED','CLOSED_ADAPTER_REQUIRED')
    sys.path.insert(0,str(combined))
    from adoption_contract import authority_request
    request=authority_request(meta['scope'],plan['release_sha256'])
    save(output/'AUTHORITY-REVIEW-REQUEST.json',request)
    policy=dict(model='HILEGA_ORDER_POLICY_REVIEW_ONLY_V1',account_scope=meta['scope'],release_sha256=plan['release_sha256'],
        approved=False,installed_or_enforced=False,
        candidate_semantics=dict(unknown_order='HOLD_NO_RESUBMISSION',partial_fill='RECONCILE_FILLED_AND_RESIDUAL_QUANTITIES',
            cancel_or_reprice_permission=False,broker_cash_addback='NEVER',
            reservation_release='REQUIRES_TERMINAL_ORDER_VERIFIED_FLAT_CURRENT_RECONCILIATION_AND_FINAL_FEES',
            allocation_preview='HALF_OBSERVED_BROKER_CASH_MINUS_EXISTING_LOCAL_HOLDS'),
        review_decisions=['CONFIRM_APPROVED_ALLOCATION_AND_PREMIUM_LIMITS','CONFIRM_EXIT_PARTIAL_AND_UNKNOWN_ORDER_OPERATIONS',
            'CONFIRM_WHO_PROVIDES_INDEPENDENT_EXECUTION_AUTHORITY_AND_ITS_SCOPE',
            'REVIEW_EXACT_CONTEXT_RECOVERY_AND_OWNER_ENROLLMENT_BINDINGS'],
        private_authority_created=False,production_execution_enabled=False)
    save(output/'ORDER-POLICY-REVIEW.json',policy)
    fr=finance.get('finance_review') or {}
    charge_state='UNKNOWN_COMPONENTS' if fr.get('missing_or_null_components') else ('MATCH' if fr.get('aggregate_component_arithmetic_matches') is True else 'REQUIRES_REVIEW')
    report=dict(status='SCOPED_CLOSED_INSTALLED_RELEASE_REGRESSION_PASS',reexecuted_cases=99,batches=results,
        full_repository_regression_reexecuted=False,context_modules_tested_from_installed_release=True,
        positive_context_paths_use_synthetic_in_memory_gate_override=True,
        real_network_denied_in_context_tests=True,broker_reads_requested=False,
        deployed_release_sha256=plan['release_sha256'],current_status_verified_before_and_after=True,
        authority_request_created=True,order_policy_review_created=True,
        production_authority_provisioned=False,policy_approved_or_enforced=False,
        recorded_finance_receipt_sha256=sha(finance_raw),recorded_charge_review_state=charge_state,
        recorded_historical_report_rows=fr.get('report_rows'),historical_capture_refreshed=False,
        broker_timezone_contract_confirmed=False,actual_fees_reconciled=False,
        live_database_enrolled=False,live_controller_resumed=False,
        installed_sources_modified=False,application_services_changed=False,
        group2_complete=False,production_execution_enabled=False,production_ready=False,audit_folder=str(output))
    save(output/'RESULT.json',report)
    tracker=regular(finance_folder/'MILESTONES.md').decode()
    tracker+='\n## Scoped installed-release batch\n- [x] 99 cases rerun in this scoped batch; not full repository regression.\n'
    tracker+='- [x] Public authority and conservative order-policy review packet bound to deployed release.\n'
    tracker+='- [ ] Independent authority / policy approval and deployed enforcement.\n- [ ] Broker timestamp semantics and completed fee evidence.\n- [ ] Real fresh-signal enrollment, full final readiness and activation.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
