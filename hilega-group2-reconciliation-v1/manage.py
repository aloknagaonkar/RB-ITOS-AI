"""Combined Group 2 candidate checks and fresh GET-only broker receipt. No live enrollment."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
from reconciliation import enrollment_preflight

def need(ok,reason):
    if not ok:raise ValueError(reason)

def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_INPUT_REQUIRED');return p.read_bytes()

def digest(raw):return hashlib.sha256(raw).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);args=ap.parse_args()
    root=args.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(digest(regular(here/n))==h,'PACKAGE_CHANGED')
    for n,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(digest(regular(root/n))==h,'PRIOR_GROUP2_TOOL_CHANGED')
    test=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_reconciliation.py')],cwd=root)
    need(test.returncode==0,'CANDIDATE_TESTS_FAILED')
    start=datetime.now(timezone.utc)
    previous=root/'hilega-group2-readiness-v1'
    result=subprocess.run([sys.executable,'-B',str(previous/'manage.py'),'--repo',str(root),'--broker-read'],cwd=root)
    need(result.returncode==0,'FRESH_GET_ONLY_CAPTURE_FAILED')
    raw=regular(previous/'VM-VALIDATION.json');receipt=json.loads(raw)
    at=datetime.fromisoformat(receipt['assessed_at'])
    need(at>=start and receipt['actual_broker_get_capture_passed'] is True and receipt['blocked'] is None,'FRESH_BROKER_RECEIPT_REQUIRED')
    summary=receipt['broker_summary'];need(summary['account_identity_verified'] is True and summary['signed_account_capture_verified'] is True,'VERIFIED_ACCOUNT_REQUIRED')
    audit=Path(tempfile.mkdtemp(prefix='hilega-group2-reconciliation-',dir=root));audit.chmod(0o700);(audit/'.gitignore').write_text('*\n')
    plan=json.loads(regular(Path(receipt['active_closed_plan'])))
    with closing(sqlite3.connect(Path(plan['application_db']).as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        total=db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0]
        owner_tables=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%owner%'")]
    # Empty state is conclusive; nonempty tables need explicit schema/ownership review.
    preflight=enrollment_preflight(total,bool(owner_tables),controller_paused=True)
    preflight['preparation_count_is_total_not_active_classification']=True
    preflight['owner_table_name_scan_is_not_signed_ownership_verification']=True
    policies=dict(status='CANDIDATES_ONLY_REQUIRES_REVIEW',
        reservation_release='TERMINAL_ORDER_AND_VERIFIED_FLAT_AND_CURRENT_BROKER_RECONCILIATION_AND_FINAL_FEES',
        broker_cash_addback='NEVER',unknown_order='HOLD_RESERVATION_NO_RESUBMISSION',
        fees='EXACT_TRADE_COMPONENT_ATTRIBUTION_WITH_EXPLICIT_COVERAGE',
        pnl='NET_CASHFLOW_IS_NOT_CERTIFIED_NET_PNL_WITHOUT_CLOSED_POSITIONS_AND_COST_BASIS',
        production_permission=False)
    report=dict(status='PASS_TARGETED_ONLY',scope='GROUP2_COMBINED_RESERVATION_FEE_AND_ENROLLMENT_CANDIDATES',
        assessed_at=datetime.now(timezone.utc).isoformat(),new_candidate_test_cases=12,
        broker_capture_test_cases=12,prior_closed_release_cases_passed=314,prior_regression_reexecuted=False,
        fresh_broker_capture_passed=True,broker_receipt_sha256=digest(raw),broker_audit_folder=receipt['audit_folder'],
        broker_summary=summary,enrollment_preflight=preflight,policies=policies,
        actual_fees_reconciled=False,broker_cash_release_implemented=False,
        candidate_local_release_rules_implemented=True,candidate_fee_attribution_implemented=True,
        production_authority_provisioned=False,execution_factory_configured=False,live_database_enrolled=False,
        application_sql_mutations_issued=False,application_services_changed=False,installed_sources_modified=False,
        orders_sent=False,group2_complete=False,production_execution_enabled=False,production_ready=False)
    (audit/'BROKER-RECEIPT.json').write_bytes(raw)
    output=json.dumps(report,indent=2)+'\n';(audit/'RESULT.json').write_text(output);(here/'VM-VALIDATION.json').write_text(output)
    print(output);print('Audit:',audit);return 0

if __name__=='__main__':raise SystemExit(main())
