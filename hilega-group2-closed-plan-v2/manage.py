"""Combined closed candidate/recovery review and disposable rehearsal; no live apply."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from live_recovery import regular, sha, need
from wrapper import wrapper


def save(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    return sha(raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--review', type=Path, required=True)
    ap.add_argument('--context-sha256', required=True)
    a = ap.parse_args()
    root, here = a.repo.absolute(), Path(__file__).absolute().parent
    for name, digest in json.loads(regular(here/'MANIFEST.json')).items():
        need(sha(regular(here/name)) == digest, 'PACKAGE_CHANGED')
    for name, digest in json.loads(regular(here/'BASELINE-PINS.json')).items():
        need(sha(regular(root/name)) == digest, 'RECOVERY_TOOL_CHANGED')
    receipt = json.loads(regular(root/'hilega-recovery-install-v1/VM-VALIDATION.json'))
    installed_path = Path(receipt['plan'])
    need(sha(regular(installed_path)) == receipt['plan_sha256'], 'RECOVERY_PLAN_CHANGED')
    installed = json.loads(regular(installed_path))
    need(installed['repo'] == str(root), 'REPOSITORY_CHANGED')
    active_path = Path(installed['active_plan'])
    need(sha(regular(active_path)) == installed['active_plan_sha256'], 'ACTIVE_PLAN_CHANGED')
    active = json.loads(regular(active_path))
    output = Path(tempfile.mkdtemp(prefix='hilega-group2-closed-plan-', dir=root))
    output.chmod(0o700)
    env = dict(PATH=os.defpath, LANG='C.UTF-8', HOME=str(Path.home()), PYTHONDONTWRITEBYTECODE='1')
    # Status needs the user's systemd bus; preserve only these two session selectors.
    status_env = dict(env)
    for key in ('XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'):
        if key in os.environ:
            status_env[key] = os.environ[key]

    def run(label, command, timeout=120, environment=env):
        r = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=timeout)
        save(output/(label+'.json'), dict(exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr))
        need(r.returncode == 0, 'CHECK_FAILED: '+label+'; inspect '+str(output/(label+'.json'))+'; diagnostic: '+r.stderr[-4000:])
        return json.loads(r.stdout)

    def status(label):
        value = run(label, [sys.executable, '-B', str(root/'hilega-recovery-install-v1/manage.py'),
            '--repo', str(root), '--action', 'status', '--plan', str(installed_path),
            '--approve-plan-sha256', receipt['plan_sha256']], environment=status_env)
        need(value['phase'] == 'CLOSED_RECOVERY_INSTALLED_RUNNING', 'INSTALLED_RECOVERY_NOT_RUNNING')

    status('CURRENT-STATUS-BEFORE')
    run('CANDIDATE-REVIEW', [sys.executable, '-B', str(here/'candidate_review.py'),
        '--review', str(a.review.absolute()), '--approve-context-sha256', a.context_sha256])
    result = json.loads(regular(a.review.absolute()/'RESULT.json'))
    candidate = Path(result['candidate_folder'])
    digest = sha(regular(candidate/'RELEASE-MANIFEST.json'))
    destination = root/'data/runtime/hilega-closed-releases'/digest
    need(not destination.exists(), 'NEW_RELEASE_DESTINATION_MUST_BE_ABSENT')
    worker = root/'scripts/hilega_production_simulator_bridge.py'
    need(sha(regular(worker)) == active['new_worker_sha256'], 'INSTALLED_WRAPPER_CHANGED')
    payload = output/'payload'
    payload.mkdir(mode=0o700)
    proposed_wrapper = wrapper(destination, digest)
    (payload/'worker.py').write_bytes(proposed_wrapper)
    (payload/'worker.py').chmod(0o600)
    config = dict(model='HILEGA_CLOSED_PAUSE_RECOVERY_CONFIG_V1', bundle=str(destination),
        release_manifest_sha256=digest, worker=str(worker), worker_sha256=sha(proposed_wrapper),
        application_db=active['application_db'], production_execution_enabled=False)
    # Rehearse the exact recovery implementation against candidate bytes and a matching
    # staged wrapper. The helper creates only new synthetic databases, never copies live data.
    rehearsal_wrapper = payload/'rehearsal-worker.py'
    rehearsal_wrapper.write_bytes(wrapper(candidate, digest))
    rehearsal_wrapper.chmod(0o600)
    rehearsal_config = dict(config, bundle=str(candidate), worker=str(rehearsal_wrapper),
        worker_sha256=sha(regular(rehearsal_wrapper)))
    save(payload/'REHEARSAL-CONFIG.json', rehearsal_config)
    rehearsed = run('NATIVE-RECOVERY-REHEARSAL', [sys.executable, '-I', '-B', '-c',
        'import sys,runpy; sys.path.insert(0, '+repr(str(here))+'); runpy.run_path('+repr(str(here/'rehearse.py'))+', run_name="__main__")',
        '--config', str(payload/'REHEARSAL-CONFIG.json'), '--output', str(output/'synthetic')], timeout=210)
    need(rehearsed['status'] == 'LIVE_ADAPTER_SYNTHETIC_REHEARSAL_PASS'
         and len(rehearsed['scenarios']) == 2, 'TWO_NATIVE_RECOVERY_SCENARIOS_REQUIRED')
    config_sha = save(payload/'CONFIG.json', config)
    status('CURRENT-STATUS-AFTER')
    proposal = dict(model='HILEGA_GROUP2_CLOSED_DEPLOYMENT_PROPOSAL_V1',
        created_at=datetime.now(timezone.utc).isoformat(), repo=str(root),
        candidate=str(candidate), candidate_release_sha256=digest, destination=str(destination),
        context_adoption_plan_sha256=a.context_sha256,
        installed_recovery_plan=str(installed_path), installed_recovery_plan_sha256=receipt['plan_sha256'],
        previous_release=str(active['destination']), previous_release_sha256=active['release_manifest_sha256'],
        wrapper_path=str(worker), old_wrapper_sha256=sha(regular(worker)), new_wrapper_sha256=sha(proposed_wrapper),
        proposed_recovery_config_sha256=config_sha,
        services_to_quiesce=installed['application_services_affected'],
        install_sequence=['VERIFY_EXACT_CURRENT_STATE_AND_ACQUIRE_SHARED_LOCK',
            'STOP_ALL_SIX_APPLICATION_SERVICES_AND_VERIFY_NO_WRITERS',
            'BACK_UP_EXACT_WRAPPER_RECOVERY_UNIT_CONFIG_DROPINS_AND_CONSISTENT_DATABASES',
            'INSTALL_SEALED_CANDIDATE_WRAPPER_AND_NEW_RECOVERY_BINDING_AS_ONE_TRANSACTION',
            'RELOAD_AND_RUN_NEW_PAUSE_RECOVERY_BEFORE_STARTING_APPLICATION_SERVICES',
            'VERIFY_PAUSED_CLOSED_BASELINE_AND_STABLE_SERVICES'],
        rollback_sequence=['STOP_APPLICATION_SERVICES', 'VERIFY_AND_RESTORE_EXACT_OLD_CODE_AND_RECOVERY_BINDINGS',
            'RELOAD_RUN_OLD_PAUSE_RECOVERY_THEN_START_SERVICES', 'VERIFY_OLD_CLOSED_RUNTIME'],
        automatic_database_restore=False, real_backups_created=False,
        exact_unit_payload_and_transactional_installer_still_required=True,
        native_candidate_recovery_scenarios_passed=2, actual_managed_candidate_startup_tested=False,
        factory_enabled=False, live_apply_available=False, broker_timestamp_contract_resolved=False,
        production_authority_provisioned=False, group2_complete=False, production_execution_enabled=False)
    plan_sha = save(output/'DEPLOYMENT-PROPOSAL.json', proposal)
    print(json.dumps(dict(status='COMBINED_CLOSED_RECOVERY_REHEARSAL_AND_PROPOSAL_PASS',
        candidate_files_verified=len(json.loads(regular(candidate/'RELEASE-MANIFEST.json'))['files']),
        native_recovery_scenarios=2, current_installed_status_checked_before_and_after=True,
        proposal=str(output/'DEPLOYMENT-PROPOSAL.json'), proposal_sha256=plan_sha,
        prior_74_tests_reexecuted=False, live_apply_available=False, installed_sources_modified=False,
        live_controller_resumed=False, production_execution_enabled=False, group2_complete=False), indent=2))


if __name__ == '__main__':
    main()
