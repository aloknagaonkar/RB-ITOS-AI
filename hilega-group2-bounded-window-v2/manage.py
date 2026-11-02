"""Build and rehearse a disposable bounded preparation window. Live apply is unavailable."""
import argparse,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
from rehearse import run
from window import need,save

def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_REVIEW_INPUT_REQUIRED');return p.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/n))==h,'WINDOW_PACKAGE_CHANGED')
    for n,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/n))==h,'VERIFIED_WINDOW_REVIEW_CHANGED')
    need(subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_window.py')],cwd=root).returncode==0,'WINDOW_TESTS_FAILED')
    start=datetime.now(timezone.utc)
    review=root/'hilega-group2-window-review-v2'
    need(subprocess.run([sys.executable,'-B',str(review/'manage.py'),'--repo',str(root)],cwd=root).returncode==0,'CURRENT_CLOSED_WINDOW_REVIEW_FAILED')
    raw=regular(review/'VM-VALIDATION.json');r=json.loads(raw)
    need(datetime.fromisoformat(r['assessed_at'])>=start and r['review']['blockers']==[] and r['verified_running_route']=='PREPARATION_ONLY','FRESH_UNBLOCKED_PREPARATION_REVIEW_REQUIRED')
    receipt=json.loads(regular(root/'hilega-group1-cache-recovery-v1/VM-VALIDATION.json'));active=Path(receipt['active_plan']);plan_raw=regular(active)
    need(sha(plan_raw)==receipt['active_plan_sha256']==r['active_plan_sha256'],'ACTIVE_PLAN_CHANGED')
    bundle=Path(json.loads(plan_raw)['destination'])
    folder=Path(tempfile.mkdtemp(prefix='hilega-group2-bounded-window-',dir=root));folder.chmod(0o700);(folder/'.gitignore').write_text('*\n');(folder/'BASELINE-REVIEW.json').write_bytes(raw)
    results=[]
    for label,crash in [('normal-timeout',False),('initiator-sigkill',True)]:
        print('Disposable native-worker rehearsal:',label,flush=True)
        results.append(dict(scenario=label,**run(bundle,folder/label,kill_initiator=crash)))
    proposal=dict(model='HILEGA_PREPARATION_WINDOW_MAINTENANCE_PROPOSAL_V1',
        active_closed_plan_sha256=receipt['active_plan_sha256'],baseline_review_sha256=sha(raw),
        controller_version_observed=r['control_version'],source_sequence_observed=r['source_sequence'],
        candidate_duration_seconds=300,route='PREPARATION_ONLY',new_post_resume_signals_only=True,
        native_controller_commands=['reconcile','resume','pause'],independent_guard_before_resume_required=True,
        actual_live_plan_available=False,live_apply_available=False,
        remaining=['SYSTEMD_MANAGED_GUARD_AND_REBOOT_RECOVERY_INTEGRATION',
            'WATCHDOG_LOSS_AND_POWER_FAILURE_REHEARSAL',
            'FRESH_SIGNAL_ATOMIC_PREPARATION_REHEARSAL',
            'QUIESCENT_BACKUPS_AND_EXACT_STATE_APPROVAL_PLAN'],
        production_execution_enabled=False)
    save(folder/'MAINTENANCE-PROPOSAL.json',proposal)
    report=dict(status='PASS_DISPOSABLE_ONLY',scope='BOUNDED_NATIVE_PREPARATION_WINDOW_AND_INITIATOR_CRASH_REHEARSAL',
        new_candidate_test_cases=14,window_review_test_cases=10,rehearsals=results,
        durable_deadline_state_implemented=True,independent_watchdog_candidate_implemented=True,
        explicit_disposable_recovery_entrypoint_implemented=True,automatic_reboot_recovery_configured=False,
        guard_loss_fail_closed_verified=False,fresh_signal_preparation_verified=False,
        live_apply_available=False,controller_resumed_on_live_database=False,
        live_application_sql_mutations_issued=False,application_services_changed=False,
        installed_sources_modified=False,broker_credentials_provided_to_rehearsal=False,
        orders_sent=False,live_database_enrolled=False,group2_complete=False,
        production_execution_enabled=False,production_ready=False,audit_folder=str(folder))
    save(folder/'RESULT.json',report);(here/'VM-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
