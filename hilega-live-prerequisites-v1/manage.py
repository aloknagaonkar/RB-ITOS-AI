"""Combined prior-session broker evidence refresh and real-issuer provisioning requirements; GET-only."""
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
    ap.add_argument('--evidence-review',type=Path,required=True);ap.add_argument('--finance-review',type=Path,required=True);ap.add_argument('--broker-read',action='store_true')
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    sha=lambda raw:hashlib.sha256(raw).hexdigest()
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'FINANCE_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'CLOSED_UPGRADE_TOOL_CHANGED')
    path=a.active_plan.absolute();need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED')
    plan=json.loads(regular(path));need(plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'DEPLOYED_CLOSED_PLAN_REQUIRED')
    prior=a.evidence_review.absolute();need(prior.parent==root and prior.name.startswith('hilega-group2-evidence-review-'),'EXACT_PRIOR_EVIDENCE_FOLDER_REQUIRED')
    receipt=json.loads(regular(prior/'RESULT.json'))
    need(receipt['status']=='CLOSED_EVIDENCE_CAPTURE_COMPLETE_REVIEW_REQUIRED' and receipt['source_process_stable'] is True,'PASSED_STRUCTURAL_EVIDENCE_REVIEW_REQUIRED')
    finance_prior=a.finance_review.absolute();finance_receipt=json.loads(regular(finance_prior/'RESULT.json'))
    need(finance_prior.parent==root and finance_receipt['session']==a.session and finance_receipt['historical_capture_completed'] is True,'PRIOR_FINANCE_CAPTURE_REQUIRED')
    query=scope(a.session)
    output=Path(tempfile.mkdtemp(prefix='hilega-live-prerequisites-review-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','DEPLOYED_RUNTIME_STATUS_FAILED')
    status('STATUS-BEFORE')
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(Path.home()),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    junit=output/'TESTS.xml'
    r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),str(here/'test_finance.py'),str(here/'test_historical.py'),'--basetemp='+str(output/'tests'),'--junitxml='+str(junit)],cwd=here,env=env,capture_output=True,text=True,timeout=60)
    save(output/'TEST-LOG.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==14 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'PREREQUISITE_TESTS_FAILED')
    summary=None;captured=False;stable=None
    if a.broker_read:
        def pid():return int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip())
        before=pid();need(before>0,'RUNNING_SOURCE_REQUIRED')
        r=subprocess.run([sys.executable,'-B',str(here/'capture.py'),'--repo',str(root),'--bundle',plan['destination'],'--adapter',plan['adapter_db'],'--pid',str(before),'--output',str(output),'--session',a.session,'--evidence-review',str(prior),'--prior-finance',str(finance_prior)],cwd=root,env=env,capture_output=True,text=True,timeout=185)
        try:summary=json.loads(r.stdout)
        except ValueError:summary=dict(status='POSTTRADE_CAPTURE_BLOCKED',reason='PROCESS_FAILED')
        if r.stderr:save(output/'PRIVATE-CAPTURE-DIAGNOSTIC.json',dict(stderr=r.stderr))
        stable=before==pid();captured=r.returncode==0 and stable
    status('STATUS-AFTER')
    report=dict(status='LIVE_PREREQUISITE_EVIDENCE_CAPTURED_REVIEW_REQUIRED' if captured else ('OFFLINE_FINANCE_CANDIDATE_PASS' if not a.broker_read else 'POSTTRADE_CAPTURE_BLOCKED'),
        reexecuted_finance_cases=8,new_historical_cases=6,prior_tests_reexecuted=False,session=a.session,query=query,
        historical_get_requested=a.broker_read,historical_capture_completed=captured,source_process_stable=stable,
        finance_review=summary,broker_timezone_contract_confirmed=False,actual_fees_reconciled=False,
        per_trade_fee_attribution_verified=False,net_pnl_certified=False,strategy_ownership_verified=False,
        reservation_release_executed=False,controller_resumed=False,application_sql_mutations_issued=False,
        application_services_changed=False,orders_sent=False,production_execution_enabled=False,
        group2_complete=False,audit_folder=str(output))
    scope_value=summary.get('account_scope') if captured else None
    proposed_parent=(Path.home()/'hilega-private/production-issuers'/scope_value.split(':',1)[1]) if scope_value and scope_value.startswith('UPSTOX:') else None
    path_safe=proposed_parent is not None and not any(p.is_symlink() for p in (proposed_parent,*proposed_parent.parents))
    request=dict(model='HILEGA_REAL_ISSUER_PROVISIONING_REQUIREMENTS_V1',active_plan=str(path),active_plan_sha256=a.active_plan_sha256,
        release_sha256=plan['release_sha256'],position_policy=plan['position_policy'],account_scope=summary.get('account_scope') if captured else None,
        account_scope_fresh_profile_verified=bool(captured),private_parent_mode='0700',private_file_mode='0600',
        issuer_key_bytes_minimum=32,issuer_key_must_differ_from_capture_token_and_execution_authority=True,
        key_fingerprint=None,issuer_id=None,private_context_sha256=None,owner_row_sha256=None,seed_request_id=None,bridge_run_id=None,
        proposed_private_parent=str(proposed_parent) if proposed_parent else None,
        proposed_issuer_id='hilega-'+scope_value.split(':',1)[1][:12] if scope_value else None,
        proposed_key_file=str(proposed_parent/'issuer.key') if proposed_parent else None,
        proposed_registry_file=str(proposed_parent/(plan['release_sha256']+'.registry.json')) if proposed_parent else None,
        proposed_paths_have_no_symlink=path_safe,existing_key_requires_explicit_reuse_review=bool(proposed_parent and (proposed_parent/'issuer.key').exists()),
        automatic_key_overwrite_or_rotation=False,key_generation_performed=False,provisioning_apply_available=False,production_execution_enabled=False,
        remaining=['EXACT_ISSUER_PRIVATE_PATH_AND_OPERATOR_APPROVAL','KEY_GENERATION_AND_PINNED_REGISTRY_REVIEW',
            'BROKER_TIMESTAMP_CONTRACT_AND_FINAL_FEES_OWNERSHIP','FRESH_REAL_DISABLED_SEED_DURABLE_HANDOFF_AND_OWNER_ENROLLMENT',
            'EXACT_ACTIVATION_SUPERVISOR_WRAPPER_RECOVERY_PLAN_AND_FINAL_READINESS'])
    save(output/'ISSUER-PROVISIONING-REQUIREMENTS.json',request)
    report.update(issuer_requirements=str(output/'ISSUER-PROVISIONING-REQUIREMENTS.json'),
        issuer_requirements_sha256=sha(regular(output/'ISSUER-PROVISIONING-REQUIREMENTS.json')),
        real_trust_keys_created=False,provisioning_apply_available=False,prior_session_historical_refresh=True,
        docs_review_date='2026-11-03',official_example_ipft_nullable=True,timestamp_timezone_not_specified_on_reviewed_trade_api_page=True)
    save(output/'RESULT.json',report)
    tracker='# Live prerequisites — combined evidence refresh\n\n'
    tracker+='- [x] Current closed installation/status verified before and after.\n- [x] Fourteen finance/history validation cases passed.\n'
    tracker+=('- [x]' if captured else '- [ ]')+' Prior-session account-bound GET capture refreshed.\n'
    tracker+='- [x] Official docs reviewed: ipft null appears in example; trade timestamp field has no explicit timezone contract.\n'
    tracker+='- [ ] Broker timestamp semantics independently confirmed.\n- [ ] Final report/fee attribution and strategy ownership verified.\n'
    tracker+='- [ ] Real issuer exact-path approval, key creation and registry provisioning.\n'
    tracker+='- [ ] Fresh real disabled seed/handoff/enrollment and exact activation/recovery plan.\n'
    tracker+='- [ ] Final readiness and controlled live activation.\n\nNo live database/service/configuration changes or key creation were performed.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2));return 0 if captured or not a.broker_read else 2


if __name__=='__main__':raise SystemExit(main())
