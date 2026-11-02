"""Package A: combined process preparation, restart recovery and maintenance-plan review."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
import xml.etree.ElementTree as ET
from window import need,save
from end_to_end import run

def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_PACKAGE_A_INPUT_REQUIRED');return p.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/n))==h,'PACKAGE_A_CHANGED')
    for n,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/n))==h,'PRIOR_VERIFIED_PACKAGE_CHANGED')
    prior_raw=regular(root/'hilega-group2-managed-recovery-v2/VM-VALIDATION.json');prior=json.loads(prior_raw)
    need(prior['status']=='PASS_MANAGED_DISPOSABLE_AND_SYNTHETIC_PREPARATION_ONLY' and len(prior['managed_rehearsals'])==2 and all(x['managed_recovery_pause_verified'] and x['stop_post_recovery_verified'] for x in prior['managed_rehearsals']),'PRIOR_MANAGED_RECOVERY_PASS_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-package-a-review-',dir=root));output.chmod(0o700);(output/'.gitignore').write_text('*\n');(output/'PRIOR-RECEIPT.json').write_bytes(prior_raw)
    junit=output/'TESTS.xml'
    code=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_package_a.py'),'--junitxml='+str(junit)],cwd=root).returncode
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(code==0 and len(cases)==6 and all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in cases),'PACKAGE_A_RECOVERY_TESTS_FAILED')
    review=root/'hilega-group2-window-review-v2'
    def baseline(label):
        begin=datetime.now(timezone.utc)
        need(subprocess.run([sys.executable,'-B',str(review/'manage.py'),'--repo',str(root)],cwd=root).returncode==0,'CURRENT_BASELINE_REQUIRES_REVIEW')
        raw=regular(review/'VM-VALIDATION.json');value=json.loads(raw)
        need(datetime.fromisoformat(value['assessed_at'])>=begin and value['review']['blockers']==[],'CURRENT_EMPTY_PAUSED_BASELINE_REQUIRED')
        (output/(label+'.json')).write_bytes(raw);return value,sha(raw)
    before,before_sha=baseline('BASELINE-BEFORE')
    recovery=json.loads(regular(root/'hilega-group1-cache-recovery-v1/VM-VALIDATION.json'));active=Path(recovery['active_plan']);raw=regular(active)
    need(sha(raw)==before['active_plan_sha256']==recovery['active_plan_sha256'],'ACTIVE_PLAN_CHANGED');plan=json.loads(raw);bundle=Path(plan['destination'])
    schema=subprocess.run([sys.executable,'-B',str(here/'validate_fixture.py'),'--bundle',str(bundle)],capture_output=True,text=True,timeout=15)
    save(output/'SIGNAL-SCHEMA-CHECK.json',dict(exit_code=schema.returncode,stdout=schema.stdout,stderr=schema.stderr))
    need(schema.returncode==0,'BUNDLED_SIGNAL_SCHEMA_CHECK_FAILED; inspect SIGNAL-SCHEMA-CHECK.json')
    print(schema.stdout,flush=True)
    results=[]
    for scenario in ('fresh-signal','pending-restart'):
        print('Package A disposable process rehearsal:',scenario,flush=True)
        try:results.append(run(bundle,output/scenario,scenario=scenario))
        except Exception as exc:
            workspace=output/scenario;diagnostics={}
            for name in ('worker-1.log','managed-arm.log','guard.log','fresh-synthetic-evidence.log','MANAGED-LAUNCH.json','GUARD-RESULT.json'):
                file=workspace/name
                diagnostics[name]=file.read_text()[-5000:] if file.is_file() and not file.is_symlink() else 'NOT_CREATED'
            app=workspace/'application.sqlite';outcomes=[]
            if app.is_file():
                db=sqlite3.connect(app.as_uri()+'?mode=ro',uri=True)
                try:
                    for row in db.execute('SELECT data FROM preparation_events ORDER BY seq DESC LIMIT 5'):
                        value=json.loads(row[0]);outcomes.append({k:value.get(k) for k in ('at','status','reasons')})
                except sqlite3.Error:pass
                finally:db.close()
            failure=dict(status='PACKAGE_A_REHEARSAL_FAILED',scenario=scenario,error_type=type(exc).__name__,reason=str(exc),
                synthetic_logs=diagnostics,preparation_outcomes=outcomes,audit_folder=str(output),live_controller_resumed_by_package=False)
            save(output/'FAILURE.json',failure);print(json.dumps(failure,indent=2),flush=True);raise

    after,after_sha=baseline('BASELINE-AFTER')
    need(before['control_version']==after['control_version'] and before['control_mode']==after['control_mode']=='PAUSED','LIVE_CONTROLLER_CHANGED_DURING_REHEARSAL')
    now=datetime.now(timezone.utc)
    proposal=dict(model='HILEGA_PACKAGE_A_MAINTENANCE_REVIEW_V1',scope='CLOSED_PREPARATION_WINDOW_ONLY',
        created_at=now.isoformat(),expires_at=(now+timedelta(minutes=10)).isoformat(),
        repo=str(root),active_plan=str(active),active_plan_sha256=sha(raw),runtime_destination=str(bundle),
        baseline_before_sha256=before_sha,baseline_after_sha256=after_sha,
        expected_controller_version=after['control_version'],expected_route='PREPARATION_ONLY',
        source_cursor_observed=after['source_sequence'],source_cursor_must_not_rewind=True,
        preparation_window_max_seconds=300,new_post_resume_signal_only=True,
        native_worker_restart_pause_verified_in_disposable_state=True,
        recovery_candidate_source_hashes={n:sha(regular(here/n)) for n in ('recovery.py','managed_guard.py','managed_arm.py','native.py')},
        recovery_unit_template=dict(Type='oneshot',Before=['hilega-production-source-worker.service'],
            worker_dependency_required=['Requires=reviewed-window-recovery.service','After=reviewed-window-recovery.service'],
            persistent_registry_scan_required=True,template_only=True,installed=False),
        backup_plan=dict(services_must_be_quiesced=True,application_db=plan['application_db'],adapter_db=plan['adapter_db'],
            code_and_configuration_hashes_required=True,sqlite_backup_and_integrity_check_required=True,
            independent_running_database_copies_are_not_cross_database_atomic=True,automatic_database_restore=False),
        approval_scope_requires_final_review=['LIVE_NATIVE_ADAPTER_WITHOUT_DISPOSABLE_MARKER',
            'PERSISTENT_BOOT_UNIT_AND_SOURCE_SERVICE_DEPENDENCY_BINDINGS',
            'QUIESCENT_CODE_DATABASE_BACKUP_RECEIPTS','FRESH_EXACT_CONTROLLER_STATE'],
        live_apply_available=False,production_execution_enabled=False)
    save(output/'MAINTENANCE-PLAN.json',proposal);proposal_sha=sha(regular(output/'MAINTENANCE-PLAN.json'))
    report=dict(status='PACKAGE_A_CANDIDATE_VALIDATION_PASS',recovery_test_cases=6,bundled_signal_schema_contract_cases=3,
        current_baseline_test_cases_per_run=10,baseline_runs=2,prior_managed_results_reused=True,
        prior_managed_receipt_sha256=sha(prior_raw),prior_full_regression_reexecuted=False,
        process_rehearsals=results,managed_window_fresh_synthetic_signal_end_to_end_verified=True,
        source_request_binding_signed_reservation_and_restart_replay_verified=True,
        native_worker_restart_pauses_pending_arm=True,managed_registry_recovery_admission_verified=True,
        synthetic_clock_and_evidence_only=True,actual_broker_signal_or_credentials_used=False,
        actual_vm_reboot_tested=False,automatic_live_boot_recovery_installed=False,
        recovery_unit_template_created=True,maintenance_plan_created=True,maintenance_plan=str(output/'MAINTENANCE-PLAN.json'),maintenance_plan_sha256=proposal_sha,
        real_quiescent_backups_created=False,live_apply_available=False,live_controller_remained_paused=True,
        live_application_database_mutations_issued=False,application_services_changed=False,
        installed_sources_modified=False,disposable_unit_control_commands_issued=True,
        production_authority_provisioned=False,live_database_enrolled=False,group2_complete=False,
        production_execution_enabled=False,production_ready=False,audit_folder=str(output))
    save(output/'RESULT.json',report);(here/'VM-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
