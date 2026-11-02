"""Combined disposable managed recovery and synthetic atomic preparation validation."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from window import need,save
from rehearse import run

def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_VERIFIED_INPUT_REQUIRED');return p.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/n))==h,'MANAGED_RECOVERY_PACKAGE_CHANGED')
    for n,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/n))==h,'PRIOR_REVIEW_CODE_CHANGED')
    prior=json.loads(regular(root/'hilega-group2-bounded-window-v2/VM-VALIDATION.json'))
    need(prior['status']=='PASS_DISPOSABLE_ONLY' and len(prior['rehearsals'])==2 and all(x['independent_deadline_pause_verified'] for x in prior['rehearsals']),'PRIOR_BOUNDED_WINDOW_PASS_REQUIRED')
    begin=datetime.now(timezone.utc)
    review=root/'hilega-group2-window-review-v2'
    need(subprocess.run([sys.executable,'-B',str(review/'manage.py'),'--repo',str(root)],cwd=root).returncode==0,'CURRENT_REVIEW_FAILED')
    raw=regular(review/'VM-VALIDATION.json');current=json.loads(raw)
    need(datetime.fromisoformat(current['assessed_at'])>=begin and current['review']['blockers']==[],'CURRENT_EMPTY_PAUSED_BASELINE_REQUIRED')
    receipt=json.loads(regular(root/'hilega-group1-cache-recovery-v1/VM-VALIDATION.json'));plan_raw=regular(Path(receipt['active_plan']))
    need(sha(plan_raw)==receipt['active_plan_sha256']==current['active_plan_sha256'],'ACTIVE_PLAN_CHANGED');bundle=Path(json.loads(plan_raw)['destination'])
    output=Path(tempfile.mkdtemp(prefix='hilega-group2-managed-recovery-',dir=root));output.chmod(0o700);(output/'.gitignore').write_text('*\n');(output/'BASELINE-REVIEW.json').write_bytes(raw)
    environment=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(output),PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=os.pathsep.join(map(str,[bundle/'backend',bundle/'runtime',here])))
    junit=output/'TESTS.xml'
    code=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_preparation_window.py'),str(here/'test_managed_contract.py'),'--junitxml='+str(junit)],cwd=output,env=environment).returncode
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(code==0 and len(cases)==10 and all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in cases),'SYNTHETIC_PREPARATION_OR_MANAGED_CONTRACT_TESTS_FAILED')
    results=[]
    for label in ('managed-timeout','managed-guard-loss'):
        print('Disposable managed rehearsal:',label,flush=True)
        results.append(dict(scenario=label,**run(bundle,output/label,kill_initiator=False)))
    proposal=dict(model='HILEGA_MANAGED_PREPARATION_WINDOW_REVIEW_V1',
        active_plan_sha256=current['active_plan_sha256'],baseline_review_sha256=sha(raw),
        controller_version_observed=current['control_version'],source_sequence_observed=current['source_sequence'],
        desired_window_seconds=300,closed_route='PREPARATION_ONLY',
        guard_loss_recovery='SYSTEMD_EXEC_STOP_POST_NATIVE_PAUSE',
        reboot_recovery='DURABLE_PENDING_WINDOW_SCAN_BEFORE_CONTROLLER_ADMISSION_REQUIRES_INTEGRATION',
        backup_requirements=['QUIESCE_WRITERS','SQLITE_CONSISTENT_CODE_AND_DATABASE_BACKUPS','VERIFY_BACKUP_HASHES'],
        live_apply_available=False,actual_reboot_tested=False,
        blockers=['BOOT_RECOVERY_INSTALLATION_AND_ORDERING','SIMULTANEOUS_MANAGER_AND_GUARD_LOSS_TEST',
            'NATIVE_WORKER_FRESH_SIGNAL_WITH_MANAGED_WINDOW_END_TO_END',
            'EXACT_LIVE_STATE_BOUND_APPROVAL_AND_BACKUP_PLAN'],production_execution_enabled=False)
    save(output/'MAINTENANCE-PROPOSAL.json',proposal)
    report=dict(status='PASS_MANAGED_DISPOSABLE_AND_SYNTHETIC_PREPARATION_ONLY',
        new_targeted_cases=10,current_window_review_cases=10,prior_regression_reexecuted=False,
        managed_rehearsals=results,synthetic_fresh_signal_atomic_preparation_tested=True,
        signed_local_cash_reservation_tested=True,hard_order_gate_remained_closed=True,
        in_process_source_fixture_only=True,managed_window_fresh_signal_end_to_end_verified=False,
        persisted_state_recovery_repeated=True,actual_vm_reboot_tested=False,
        automatic_boot_recovery_installed=False,application_service_control_commands_issued=False,
        disposable_unit_control_commands_issued=True,live_database_mutations_issued=False,
        installed_sources_modified=False,live_controller_resumed=False,live_apply_available=False,
        live_database_enrolled=False,production_authority_provisioned=False,group2_complete=False,
        production_execution_enabled=False,production_ready=False,audit_folder=str(output))
    save(output/'RESULT.json',report);(here/'VM-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
