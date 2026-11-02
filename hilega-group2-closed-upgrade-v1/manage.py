"""Closed candidate upgrade: check, exact approved apply, status, or code-only rollback."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from transaction import need, regular, sha, atomic, replace_all, restore_all
from plan_tools import unit
from wrapper import wrapper

RECOVERY = 'hilega-closed-pause-recovery.service'


def save(path, value):
    atomic(path, (json.dumps(value, indent=2, sort_keys=True)+'\n').encode(), 0o600)


def load(path):
    return json.loads(regular(path))


def command(argv, *, timeout=60, env=None):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    need(r.returncode == 0, 'COMMAND_FAILED: '+str(argv[0])+'; '+r.stderr[-3500:])
    return r.stdout


def verify_bundle(path, digest):
    raw = regular(path/'RELEASE-MANIFEST.json')
    need(sha(raw) == digest, 'RELEASE_MANIFEST_CHANGED')
    manifest = json.loads(raw)
    for name, expected in manifest['files'].items():
        rel = Path(name)
        need(not rel.is_absolute() and '..' not in rel.parts, 'UNSAFE_RELEASE_PATH')
        need(sha(regular(path/rel)) == expected, 'RELEASE_FILE_CHANGED: '+name)
    actual = set()
    for p in path.rglob('*'):
        need(not p.is_symlink(), 'RELEASE_SYMLINK')
        if p.is_file(): actual.add(p.relative_to(path).as_posix())
    need(actual == set(manifest['files']) | {'RELEASE-MANIFEST.json'}, 'UNMANIFESTED_RELEASE_FILE')
    registration = load(path/'CLOSED-REGISTRATION.json')
    need(registration['mode'] == 'CLOSED_PREPARATION_ONLY' and registration['execution_factory_configured'] is False
         and registration['production_execution_enabled'] is False, 'FACTORY_DISABLED_RELEASE_REQUIRED')
    return manifest


def control(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        return json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])


def pinned_runtime(root):
    sys.path.insert(0, str(root/'hilega-group1-rollout-v1'))
    import rollout
    import maintenance_primitives as m
    return rollout, m


def systemctl(action):
    need(action in {'stop', 'start'}, 'INVALID_RECOVERY_ACTION')
    command(['systemctl', '--user', action, RECOVERY], timeout=100)


def definitions(names):
    result = {}
    for name in names:
        text = command(['systemctl', '--user', 'show', name, '--property=FragmentPath,DropInPaths'])
        values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        paths = [values['FragmentPath'], *shlex.split(values.get('DropInPaths', ''))]
        need(paths[0] and all(Path(p).is_absolute() for p in paths), 'EXACT_UNIT_DEFINITION_REQUIRED')
        result[name] = paths
    return result


def stop_services(m, manager):
    for name in m.UNITS:
        if manager.state(name)['active'] != 'inactive': manager.control('stop', name)
    need(all(manager.state(u)['active'] == 'inactive' and manager.state(u)['pid'] == 0 for u in m.UNITS), 'SERVICES_NOT_STOPPED')


def start_services(plan, old, m, manager):
    previous = old.read_health(Path(plan['application_db']))['run_id']
    for name in reversed(m.UNITS[1:]): manager.control('start', name)
    old.wait_inventory(Path(plan['repo']))
    manager.control('start', m.UNITS[0])
    old.wait_health(Path(plan['application_db']), previous, manager, list(m.UNITS), timeout=35)
    m.require_empty_closed_baseline(Path(plan['application_db']), Path(plan['adapter_db']))


def verify_inputs(plan, *, installed):
    need(definitions(plan['unit_definitions']) == plan['unit_definitions'], 'UNIT_DEFINITION_LIST_CHANGED')
    replaced = {e['destination']: e for e in plan['files']}
    for path, digest in plan['observed_bindings'].items():
        expected = replaced[path]['new_sha256'] if installed and path in replaced else digest
        need(sha(regular(Path(path))) == expected, 'BOUND_INPUT_CHANGED: '+Path(path).name)
    for entry in plan['files']:
        expected = entry['new_sha256'] if installed else entry['old_sha256']
        need(sha(regular(Path(entry['destination']))) == expected, 'INSTALLED_FILE_CHANGED')
    for entry in plan['new_recovery_files']:
        p = Path(entry['destination'])
        if installed: need(sha(regular(p)) == entry['new_sha256'], 'RECOVERY_PAYLOAD_CHANGED')
        else: need(not p.exists() and not any(q.is_symlink() for q in (p, *p.parents)), 'RECOVERY_DESTINATION_EXISTS_OR_SYMLINK')


def backup(plan, folder, m):
    base = folder/'backups'; base.mkdir(mode=0o700)
    originals = base/'replaced'; originals.mkdir(mode=0o700)
    for i, e in enumerate(plan['files']):
        raw = regular(Path(e['destination'])); need(sha(raw) == e['old_sha256'], 'OLD_FILE_CHANGED')
        atomic(originals/str(i), raw, 0o600)
    bindings = base/'bindings'; bindings.mkdir(mode=0o700)
    index = []
    for i, (path, digest) in enumerate(plan['observed_bindings'].items()):
        raw = regular(Path(path)); need(sha(raw) == digest, 'BOUND_INPUT_CHANGED')
        atomic(bindings/str(i), raw, 0o600); index.append(dict(path=path, backup=str(i), sha256=digest))
    save(bindings/'INDEX.json', index)
    # Old immutable release is retained; additionally preserve its bytes privately.
    old_bundle = Path(plan['old_bundle']); manifest = verify_bundle(old_bundle, plan['old_release_sha256'])
    for name in [*manifest['files'], 'RELEASE-MANIFEST.json']:
        target = base/'old-bundle'/name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic(target, regular(old_bundle/name), 0o600)
    for key in ('application_db', 'adapter_db'):
        target = base/(key+'.sqlite'); m.backup_database(Path(plan[key]), target)
        with sqlite3.connect(target) as db:
            need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'DATABASE_BACKUP_INVALID')
    save(folder/'BACKUP-RECEIPT.json', dict(quiescent=True, automatic_database_restore=False,
        files={str(p.relative_to(base)): sha(regular(p)) for p in base.rglob('*') if p.is_file()}))


def apply(plan, folder, old, m):
    need(not (folder/'TRANSACTION.json').exists(), 'UPGRADE_ALREADY_STARTED_USE_STATUS_OR_ROLLBACK')
    need(datetime.now(timezone.utc) <= datetime.fromisoformat(plan['apply_before']), 'PLAN_EXPIRED_RECHECK')
    verify_inputs(plan, installed=False)
    source, dest = Path(plan['candidate']), Path(plan['destination'])
    verify_bundle(source, plan['release_sha256'])
    need(not dest.exists() and not dest.is_symlink() and not any(p.is_symlink() for p in dest.parents), 'NEW_RELEASE_DESTINATION_REQUIRED')
    m.require_empty_closed_baseline(Path(plan['application_db']), Path(plan['adapter_db']))
    c = control(Path(plan['application_db']))
    need(c['version'] == plan['controller_version'] and c['session_date'] == plan['session_date'], 'CONTROLLER_STATE_CHANGED_RECHECK')
    manager = m.Systemd()
    need(all(manager.state(u)['active'] == 'active' and manager.state(u)['pid'] > 0 for u in m.UNITS), 'SIX_RUNNING_SERVICES_REQUIRED')
    tx = dict(phase='STOPPING', production_execution_enabled=False)
    save(folder/'TRANSACTION.json', tx)
    try:
        stop_services(m, manager); m.no_unmanaged_python(Path(plan['repo']))
        m.require_empty_closed_baseline(Path(plan['application_db']), Path(plan['adapter_db']))
        verify_inputs(plan, installed=False); backup(plan, folder, m)
        tx['phase'] = 'BACKED_UP_SERVICES_STOPPED'; save(folder/'TRANSACTION.json', tx)
        # The existing oneshot must leave its active state before its new ExecStart is installed.
        systemctl('stop')
        shutil.copytree(source, dest, copy_function=shutil.copyfile)
        verify_bundle(dest, plan['release_sha256'])
        for p in dest.rglob('*'):
            if p.is_file(): p.chmod(0o400)
        for p in sorted((p for p in dest.rglob('*') if p.is_dir()), key=lambda p:len(p.parts), reverse=True): p.chmod(0o500)
        dest.chmod(0o500)
        for e in plan['new_recovery_files']:
            target = Path(e['destination']); target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            need(not target.exists(), 'NEW_RECOVERY_FILE_EXISTS')
            atomic(target, regular(folder/e['payload']), 0o400)
        Path(plan['recovery_directory']).chmod(0o500)
        tx['phase'] = 'REPLACING_CLOSED_BINDINGS'; save(folder/'TRANSACTION.json', tx)
        replace_all(plan['files'], folder, folder/'backups/replaced')
        command(['systemctl', '--user', 'daemon-reload'])
        verify_inputs(plan, installed=True); systemctl('start')
        need(control(Path(plan['application_db']))['mode'] == 'PAUSED', 'RECOVERY_NOT_PAUSED')
        tx['phase'] = 'RECOVERY_VERIFIED_SERVICES_STOPPED'; save(folder/'TRANSACTION.json', tx)
        start_services(plan, old, m, manager)
        verify_inputs(plan, installed=True)
        tx['phase'] = 'CLOSED_GROUP2_CANDIDATE_RUNNING'; save(folder/'TRANSACTION.json', tx)
        save(folder/'ACTIVE-RUNTIME.json', dict(plan=str(folder/'PLAN.json'), plan_sha256=sha(regular(folder/'PLAN.json')),
            release_sha256=plan['release_sha256'], phase=tx['phase'], production_execution_enabled=False))
        return tx
    except BaseException:
        # Preserve all receipts and backups. Never automatically restore databases or
        # restart a partially installed release. Explicit rollback accepts old/new mixtures.
        try: stop_services(m, manager)
        finally:
            tx['failed_at'] = tx['phase']; tx['phase'] = 'FAILED_REQUIRES_EXPLICIT_ROLLBACK'
            save(folder/'TRANSACTION.json', tx)
        raise


def rollback(plan, folder, old, m):
    tx = load(folder/'TRANSACTION.json')
    need(tx['phase'] != 'ROLLED_BACK_RUNNING', 'ALREADY_ROLLED_BACK')
    manager = m.Systemd(); stop_services(m, manager); m.no_unmanaged_python(Path(plan['repo']))
    need(definitions(plan['unit_definitions']) == plan['unit_definitions'], 'UNIT_DEFINITION_LIST_CHANGED')
    systemctl('stop')
    if (folder/'BACKUP-RECEIPT.json').exists():
        receipt = load(folder/'BACKUP-RECEIPT.json')
        for name, digest in receipt['files'].items():
            need(sha(regular(folder/'backups'/name)) == digest, 'BACKUP_CHANGED')
        restore_all(plan['files'], folder/'backups/replaced')
    else:
        # No code replacements are allowed before a durable backup receipt.
        for e in plan['files']: need(sha(regular(Path(e['destination']))) == e['old_sha256'], 'NO_BACKUP_ORIGINAL_CHANGED')
    verify_bundle(Path(plan['old_bundle']), plan['old_release_sha256'])
    # Keep new immutable bundles/configs for audit; old unit no longer references them.
    command(['systemctl', '--user', 'daemon-reload']); systemctl('start')
    start_services(plan, old, m, manager)
    for path, digest in plan['observed_bindings'].items(): need(sha(regular(Path(path))) == digest, 'RESTORED_BINDING_CHANGED')
    tx['phase'] = 'ROLLED_BACK_RUNNING'; save(folder/'TRANSACTION.json', tx)
    return tx


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--action', choices=['check', 'apply', 'status', 'rollback'], default='check')
    ap.add_argument('--proposal', type=Path); ap.add_argument('--proposal-sha256')
    ap.add_argument('--plan', type=Path); ap.add_argument('--approve-plan-sha256')
    a = ap.parse_args(); root = a.repo.absolute(); here = Path(__file__).absolute().parent
    for name, digest in load(here/'MANIFEST.json').items(): need(sha(regular(here/name)) == digest, 'UPGRADE_PACKAGE_CHANGED')
    for name, digest in load(here/'BASELINE-PINS.json').items(): need(sha(regular(root/name)) == digest, 'REVIEWED_TOOL_CHANGED')
    lock = root/'.hilega-closed-rollout.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode)&0o077 == 0, 'PRIVATE_MAINTENANCE_LOCK_REQUIRED')
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    old, m = pinned_runtime(root)
    if a.action != 'check':
        need(a.plan is not None and a.approve_plan_sha256, 'EXACT_PLAN_REQUIRED')
        path = a.plan.absolute(); need(sha(regular(path)) == a.approve_plan_sha256, 'PLAN_APPROVAL_CHANGED')
        plan = load(path); folder = path.parent
        need(path.name == 'PLAN.json' and folder.parent == root and folder.name.startswith('hilega-group2-upgrade-plan-'), 'EXACT_UPGRADE_FOLDER_REQUIRED')
        need(plan['model'] == 'HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['repo'] == str(root)
             and plan['tool_manifest_sha256'] == sha(regular(here/'MANIFEST.json')) and plan['production_execution_enabled'] is False, 'PLAN_SCOPE_CHANGED')
        check = load(folder/'CHECK-VALIDATION.json')
        need(check['plan_sha256'] == a.approve_plan_sha256 and check['status'] == 'CLOSED_UPGRADE_CHECK_PASS', 'PASSING_EXACT_PLAN_REQUIRED')
        for e in [*plan['files'], *plan['new_recovery_files']]: need(sha(regular(folder/e['payload'])) == e['new_sha256'], 'PLANNED_PAYLOAD_CHANGED')
        if a.action == 'apply': tx = apply(plan, folder, old, m)
        elif a.action == 'rollback': tx = rollback(plan, folder, old, m)
        else:
            tx = load(folder/'TRANSACTION.json')
            installed = tx['phase'] == 'CLOSED_GROUP2_CANDIDATE_RUNNING'
            need(installed or tx['phase'] == 'ROLLED_BACK_RUNNING', 'RUNNING_PHASE_REQUIRED')
            if installed:
                verify_inputs(plan, installed=True); verify_bundle(Path(plan['destination']), plan['release_sha256'])
            else:
                for path, digest in plan['observed_bindings'].items(): need(sha(regular(Path(path))) == digest, 'OLD_BINDING_CHANGED')
            old.wait_inventory(root)
            old.wait_health(Path(plan['application_db']), 'STATUS_OBSERVATION', m.Systemd(), list(m.UNITS), timeout=35)
            m.require_empty_closed_baseline(Path(plan['application_db']), Path(plan['adapter_db']))
            command(['systemctl', '--user', 'is-active', '--quiet', RECOVERY])
        update_checklist(folder, installed=tx['phase'] == 'CLOSED_GROUP2_CANDIDATE_RUNNING', phase=tx['phase'])
        print(json.dumps(dict(phase=tx['phase'], controller_resumed=False, production_execution_enabled=False, production_ready=False), indent=2)); return

    need(a.proposal is not None and a.proposal_sha256, 'PASSED_PROPOSAL_AND_DIGEST_REQUIRED')
    proposal_path = a.proposal.absolute(); need(sha(regular(proposal_path)) == a.proposal_sha256, 'PROPOSAL_CHANGED')
    proposal = load(proposal_path)
    need(proposal['repo'] == str(root) and proposal['model'] == 'HILEGA_GROUP2_CLOSED_DEPLOYMENT_PROPOSAL_V1'
         and proposal['native_candidate_recovery_scenarios_passed'] == 2 and proposal['factory_enabled'] is False
         and proposal['production_execution_enabled'] is False, 'CLOSED_REHEARSED_PROPOSAL_REQUIRED')
    rehearsal = load(proposal_path.parent/'NATIVE-RECOVERY-REHEARSAL.json')
    need(rehearsal['exit_code'] == 0 and json.loads(rehearsal['stdout'])['status'] == 'LIVE_ADAPTER_SYNTHETIC_REHEARSAL_PASS', 'NATIVE_RECOVERY_RECEIPT_REQUIRED')
    installed_path = Path(proposal['installed_recovery_plan'])
    need(sha(regular(installed_path)) == proposal['installed_recovery_plan_sha256'], 'INSTALLED_RECOVERY_PLAN_CHANGED')
    installed = load(installed_path); active = load(Path(installed['active_plan']))
    need(sha(regular(Path(installed['active_plan']))) == installed['active_plan_sha256'], 'ACTIVE_PLAN_CHANGED')
    source = Path(proposal['candidate']); digest = proposal['candidate_release_sha256']
    verify_bundle(source, digest)
    need(proposal['destination'] == str(root/'data/runtime/hilega-closed-releases'/digest), 'EXACT_RELEASE_DESTINATION_REQUIRED')
    need(not Path(proposal['destination']).exists(), 'RELEASE_ALREADY_INSTALLED')
    output = Path(tempfile.mkdtemp(prefix='hilega-group2-upgrade-plan-', dir=root)); output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    clean_env = dict(PATH=os.defpath, HOME=str(Path.home()), LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    status_cmd = [sys.executable, '-B', str(root/'hilega-recovery-install-v1/manage.py'), '--repo', str(root), '--action', 'status', '--plan', str(installed_path), '--approve-plan-sha256', proposal['installed_recovery_plan_sha256']]
    # Old status command acquires the same lock. Release only for that read-only
    # check, then reacquire and recheck the exact bindings below.
    fcntl.flock(fd, fcntl.LOCK_UN)
    before = command(status_cmd, timeout=100); save(output/'CURRENT-STATUS-BEFORE.json', json.loads(before))
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    candidate_folder = source.parent
    text = command([sys.executable, '-B', str(here/'candidate_review.py'), '--review', str(candidate_folder), '--approve-context-sha256', proposal['context_adoption_plan_sha256']], env=clean_env)
    save(output/'CANDIDATE-REVIEW.json', json.loads(text))
    junit = output/'TESTS.xml'
    run = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--rootdir='+str(here), '--confcutdir='+str(here), str(here/'test_transaction.py'), '--basetemp='+str(output/'tests'), '--junitxml='+str(junit)], cwd=here, env=clean_env, capture_output=True, text=True, timeout=60)
    save(output/'TRANSACTION-TESTS.json', dict(exit_code=run.returncode, stdout=run.stdout, stderr=run.stderr))
    cases = list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(run.returncode == 0 and len(cases) == 8 and all(not any(c.find(tag) is not None for tag in ['failure','error','skipped']) for c in cases), 'TRANSACTION_TESTS_FAILED_INSPECT_LOG')
    name = 'hilega-group2-upgrade-rehearsal-'+uuid.uuid4().hex+'.service'
    managed_output = output/'managed-disposable'
    cmd = ['systemd-run', '--user', '--wait', '--collect', '--unit='+name, '--property=Type=oneshot', '--property=NoNewPrivileges=yes', '--property=RestrictAddressFamilies=AF_UNIX', '--property=RuntimeMaxSec=55', '--property=UMask=0077', '--working-directory='+str(output), '/usr/bin/env', '-i', 'PATH='+os.defpath, 'LANG=C.UTF-8', 'HOME='+str(output), 'PYTHONDONTWRITEBYTECODE=1', sys.executable, '-I', '-B', str(source/'rehearse.py'), '--release', str(source), '--output', str(managed_output)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
    save(output/'MANAGED-REHEARSAL.json', dict(unit=name, exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr))
    need(r.returncode == 0, 'MANAGED_CANDIDATE_FAILED: '+r.stderr[-3500:])
    managed = load(managed_output/'RESULT.json')
    need(managed['status'] == 'ACTUAL_DISPOSABLE_CLOSED_WORKER_RESTART_PASS' and managed['disposable_databases_only'] is True, 'MANAGED_WORKER_RECEIPT_REQUIRED')
    verify_bundle(source, digest)
    need(sha(regular(Path(proposal['wrapper_path']))) == proposal['old_wrapper_sha256'], 'CURRENT_WRAPPER_CHANGED')
    observed = dict(active['bindings'])
    observed[str(installed_path)] = proposal['installed_recovery_plan_sha256']
    observed[str(proposal_path)] = a.proposal_sha256
    for e in installed['files']: observed[e['destination']] = e['new_sha256']
    for paths in installed['observed_unit_paths'].values():
        for path in paths: observed[path] = sha(regular(Path(path)))
    unit_definitions = definitions([*m.UNITS, RECOVERY])
    for paths in unit_definitions.values():
        for path in paths: observed[path] = sha(regular(Path(path)))
    for path, expected in observed.items(): need(sha(regular(Path(path))) == expected, 'CURRENT_BINDING_CHANGED')
    need(list(installed['application_services_affected']) == list(m.UNITS), 'EXACT_SIX_UNITS_REQUIRED')
    m.require_empty_closed_baseline(Path(active['application_db']), Path(active['adapter_db']))
    c = control(Path(active['application_db']))
    payload = output/'payload'; payload.mkdir(mode=0o700)
    new_wrapper = wrapper(Path(proposal['destination']), digest)
    need(sha(new_wrapper) == proposal['new_wrapper_sha256'], 'PROPOSED_WRAPPER_CHANGED')
    atomic(payload/'worker.py', new_wrapper, 0o600)
    config = load(proposal_path.parent/'payload/CONFIG.json')
    config_raw = regular(proposal_path.parent/'payload/CONFIG.json')
    need(sha(config_raw) == proposal['proposed_recovery_config_sha256'] and config['bundle'] == proposal['destination'] and config['worker_sha256'] == sha(new_wrapper) and config['application_db'] == active['application_db'] and config['release_manifest_sha256'] == digest and config['worker'] == proposal['wrapper_path'] and config['model'] == 'HILEGA_CLOSED_PAUSE_RECOVERY_CONFIG_V1' and config['production_execution_enabled'] is False, 'PROPOSED_RECOVERY_CONFIG_CHANGED')
    directory = root/'data/runtime/hilega-closed-pause-recovery'/sha(config_raw)
    need(not directory.exists() and not any(p.is_symlink() for p in (directory, *directory.parents)), 'NEW_RECOVERY_DIRECTORY_REQUIRED')
    atomic(payload/'CONFIG.json', config_raw, 0o600)
    atomic(payload/'live_recovery.py', regular(here/'live_recovery.py'), 0o600)
    unit_raw = unit(sys.executable, str(directory/'live_recovery.py'), str(directory/'CONFIG.json'), sha(config_raw))
    atomic(payload/'recovery.service', unit_raw, 0o600)
    syntax = output/'hilega-closed-pause-recovery.service'; atomic(syntax, unit_raw, 0o600)
    command(['systemd-analyze', '--user', 'verify', str(syntax)], timeout=20)
    recovery_unit = next(e['destination'] for e in installed['files'] if Path(e['destination']).name == RECOVERY)
    entries = []
    for target, name in [(Path(proposal['wrapper_path']), 'worker.py'), (Path(recovery_unit), 'recovery.service')]:
        entries.append(dict(destination=str(target), payload='payload/'+name, old_sha256=sha(regular(target)), new_sha256=sha(regular(payload/name)), old_mode=stat.S_IMODE(target.stat().st_mode), mode=stat.S_IMODE(target.stat().st_mode)))
        observed[str(target)] = entries[-1]['old_sha256']
    recovery_files = [dict(destination=str(directory/name), payload='payload/'+name, new_sha256=sha(regular(payload/name))) for name in ['CONFIG.json','live_recovery.py']]
    now = datetime.now(timezone.utc)
    plan = dict(model='HILEGA_GROUP2_CLOSED_UPGRADE_V1', repo=str(root), tool_manifest_sha256=sha(regular(here/'MANIFEST.json')),
        created_at=now.isoformat(), apply_before=(now+timedelta(minutes=30)).isoformat(), candidate=str(source), destination=proposal['destination'], release_sha256=digest,
        old_bundle=active['destination'], old_release_sha256=active['release_manifest_sha256'], observed_bindings=observed,
        application_db=active['application_db'], adapter_db=active['adapter_db'], controller_version=c['version'], session_date=c['session_date'],
        recovery_directory=str(directory), files=entries, new_recovery_files=recovery_files,
        unit_definitions=unit_definitions,
        automatic_database_restore=False, execution_factory_configured=False, production_execution_enabled=False)
    # Exact bytes and unit-definition lists are checked again by old status before
    # publishing a plan. A concurrent maintainer changes hashes/version and forces recheck.
    fcntl.flock(fd, fcntl.LOCK_UN)
    after = command(status_cmd, timeout=100); save(output/'CURRENT-STATUS-AFTER.json', json.loads(after))
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    verify_inputs(plan, installed=False)
    need(control(Path(active['application_db']))['version'] == c['version'], 'CONTROLLER_CHANGED_DURING_CHECK')
    save(output/'PLAN.json', plan); plan_sha = sha(regular(output/'PLAN.json'))
    report = dict(status='CLOSED_UPGRADE_CHECK_PASS', transaction_tests=8, managed_actual_worker_startup_and_restart_verified=True,
        recovery_native_scenarios_previously_passed=2, prior_74_tests_reexecuted=False,
        plan=str(output/'PLAN.json'), plan_sha256=plan_sha, apply_before=plan['apply_before'],
        apply_available=True, backups_created=False, installed_sources_modified=False,
        live_controller_resumed=False, production_execution_enabled=False, group2_complete=False)
    save(output/'CHECK-VALIDATION.json', report)
    update_checklist(output, installed=False, phase='CHECK_PASSED_DEPLOYMENT_PENDING')
    print(json.dumps(report, indent=2))


def update_checklist(folder, *, installed, phase):
    text = regular(Path(__file__).absolute().parent/'MILESTONES.md').decode()
    text = text.replace('- [ ] Current package transaction tests on VM.', '- [x] Current package transaction tests on VM: 8 passed.')
    text = text.replace('- [ ] New candidate managed startup/restart on disposable state.', '- [x] New candidate managed startup/restart on disposable state passed.')
    text = text.replace('- [ ] Exact closed upgrade plan generated.', '- [x] Exact closed upgrade plan generated.')
    if installed:
        text = text.replace('- [ ] Quiescent code/config/database backups.', '- [x] Quiescent code/config/database backups created and verified.')
        text = text.replace('- [ ] Candidate and matching recovery deployed; stable paused runtime verified.', '- [x] Candidate and matching recovery deployed; stable paused runtime verified.')
    text += '\nCurrent transaction phase: `'+phase+'`.\n'
    atomic(folder/'MILESTONES.md', text.encode(), 0o600)


if __name__ == '__main__':
    main()
