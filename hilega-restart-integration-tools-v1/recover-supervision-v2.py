"""Recover the specific failed preparation-service migration. No trading activation."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import select
import signal
import subprocess
import tempfile
import time

ROLES = ('api', 'worker', 'production-source-worker')

def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)

def corrected_unit(text, root, stage, role, expected_hash):
    old = 'WorkingDirectory="' + str(root) + '"'
    new = 'WorkingDirectory=' + str(root)
    lines = text.splitlines()
    need(lines.count(old) + lines.count(new) == 1, 'DIRECTORY_SETTING_UNEXPECTED')
    # Accept only the original generated unit, or exactly its directory fix.
    original = text.replace(new + '\n', old + '\n', 1) if new in lines else text
    need(hashlib.sha256(original.encode()).hexdigest() == expected_hash,
         'OTHER_UNIT_CONTENT_CHANGED')
    return original.replace(old + '\n', new + '\n', 1)

def validate_inventory(rows):
    need(len(rows) == 2 and {r['role'] for r in rows} == {'api', 'worker'},
         'EXPECTED_ONLY_DETACHED_API_AND_WORKER')
    need(len({r['pid'] for r in rows}) == 2, 'DUPLICATE_PROCESS_ID')

def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    need(result.returncode == 0, 'COMMAND_FAILED_' + Path(args[0]).name)
    return result.stdout.strip()

def atomic_text(path, text):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)

def verify_candidate_units(texts):
    with tempfile.TemporaryDirectory(prefix='hilega-unit-verify-') as directory:
        paths = []
        for role, text in texts.items():
            path = Path(directory) / ('hilega-' + role + '.service')
            path.write_text(text); paths.append(str(path))
        result = subprocess.run(['systemd-analyze', '--user', 'verify', *paths],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            print(result.stderr, end='')  # Unit definitions contain no credentials.
            raise RuntimeError('CORRECTED_UNIT_VALIDATION_FAILED')

def main(apply=False):
    os.umask(0o077)
    root = Path.home() / 'RB-ITOS-AI'
    stage = Path.home() / 'hilega-persistent-supervision-stage-v1'
    unit_dir = Path.home() / '.config/systemd/user'
    tool = root / 'hilega-supervision-migration-tools-v1/migrate-persistent-supervision.py'
    spec = importlib.util.spec_from_file_location('existing_migration', tool)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    runner = m.load_runner(stage)
    state_path = stage / 'migration.json'
    original_state = json.loads(runner.regular(state_path))
    need(original_state.get('phase') == 'REQUIRES_REVIEW_NO_AUTOMATIC_RETRY'
         and original_state.get('failure_after_phase') == 'STARTING_SUPERVISED',
         'UNEXPECTED_MIGRATION_STATE')
    marker = stage / 'supervision-recovery-v2.json'
    need(not marker.exists() and not marker.is_symlink(), 'RECOVERY_ALREADY_ATTEMPTED')
    config_path = stage / 'config-private.json'
    config = json.loads(runner.regular(config_path))
    approval = json.loads(runner.regular(stage / 'MIGRATION_APPROVED.json'))
    need(config['root'] == str(root), 'ROOT_MISMATCH')
    need(approval['config_sha256'] == m.sha(config_path), 'CONFIG_CHANGED')
    need(approval['runner_sha256'] == m.sha(stage / 'runner.py'), 'RUNNER_CHANGED')
    need(m.sha(root / '.env') == config['env_sha256'], 'ENV_CHANGED')
    for role in ROLES: runner.validate_item(role, config['startup'][role], root)
    runner.paused(root); m.clean_database(root)
    before = m.inventory(root); validate_inventory(before)
    need(run(['loginctl','show-user',pwd.getpwuid(os.getuid()).pw_name,'-p','Linger','--value']) == 'yes',
         'LINGER_NOT_ENABLED')
    texts, originals = {}, {}
    for role in ROLES:
        name = 'hilega-' + role + '.service'
        installed, staged = unit_dir / name, stage / name
        text = runner.regular(installed).decode()
        need(text == runner.regular(staged).decode(), 'UNIT_COPIES_DIFFER')
        need(run(['systemctl','--user','show',name,'-p','MainPID','--value']) == '0',
             'SUPERVISED_PROCESS_ALREADY_RUNNING')
        active = run(['systemctl','--user','show',name,'-p','ActiveState','--value'])
        need(active in ('inactive','failed'), 'UNIT_NOT_QUIESCENT')
        texts[role] = corrected_unit(text, root, stage, role, m.expected_unit_hash(root,stage,role))
        originals[installed] = text; originals[staged] = text
    # Real systemd parser verification occurs BEFORE stopping any process.
    verify_candidate_units(texts)
    if not apply:
        print(json.dumps(dict(status='RECOVERY_V2_CHECKS_PASS', processes=before,
            corrected_units_verified=True, processes_signalled=False,
            files_modified=False, controller_mode='PAUSED', production_execution_enabled=False),indent=2))
        return
    lock = (stage / 'migration.lock').open('a')
    handles = []
    state = dict(phase='PREPARED', previous_processes=before)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        need(not marker.exists(), 'RECOVERY_ALREADY_ATTEMPTED')
        need(m.normalized(m.inventory(root)) == m.normalized(before), 'PROCESS_INVENTORY_CHANGED')
        for row in before:
            fd = os.pidfd_open(row['pid']); handles.append((row['role'],fd))
            need(m.identity(row['pid'],root) == row['start_ticks'], 'PROCESS_IDENTITY_CHANGED')
        runner.paused(root); m.clean_database(root)
        backup = Path(tempfile.mkdtemp(prefix='supervision-recovery-v2-',dir=stage))
        for i,(path,text) in enumerate(originals.items()):
            (backup / (str(i)+'-'+path.name)).write_text(text)
        (backup/'previous-migration.json').write_text(json.dumps(original_state,indent=2))
        (backup/'previous-maintenance.json').write_bytes(runner.regular(root/'backups/hilega-preparation-activation-cvtlkibq/maintenance.json'))
        state['backup'] = str(backup)
        runner.atomic(marker,state)
        state['phase']='REPAIRING_UNITS'; runner.atomic(marker,state)
        for path,text in originals.items():
            need(runner.regular(path).decode() == text, 'UNIT_CHANGED_DURING_RECOVERY')
            role=next(r for r in ROLES if path.name=='hilega-'+r+'.service')
            atomic_text(path,texts[role])
        run(['systemctl','--user','daemon-reload'])
        runner.paused(root); m.clean_database(root)
        need(m.sha(root/'.env') == config['env_sha256'], 'ENV_CHANGED')
        state['phase']='STOPPING_DETACHED_PROCESSES'; runner.atomic(marker,state)
        for role in ('worker','api'): signal.pidfd_send_signal(dict(handles)[role],signal.SIGTERM)
        poller=select.poll()
        for _,fd in handles: poller.register(fd,select.POLLIN)
        waiting={fd for _,fd in handles}; deadline=time.monotonic()+30
        while waiting and time.monotonic()<deadline:
            waiting-={fd for fd,event in poller.poll(500) if event & select.POLLIN}
        need(not waiting,'STOP_TIMEOUT_NO_FORCE_KILL')
        # A competing replacement is a reason to stop, never to kill it.
        for _ in range(3):
            need(not m.inventory(root),'UNEXPECTED_REPLACEMENT_PROCESS')
            time.sleep(1)
        runner.paused(root); m.clean_database(root)
        state['phase']='STARTING_SUPERVISED'; runner.atomic(marker,state)
        for role in ('worker','api','production-source-worker'):
            name='hilega-'+role+'.service'
            run(['systemctl','--user','reset-failed',name])
            run(['systemctl','--user','start',name])
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            try:
                checked=m.paused_check(root); health=m.api_health(); rows=m.inventory(root)
                need(len(rows)==3 and {r['role'] for r in rows}==set(ROLES),'INVENTORY_INVALID')
                for row in rows:
                    name='hilega-'+row['role']+'.service'
                    need(run(['systemctl','--user','is-active',name])=='active','SERVICE_NOT_ACTIVE')
                    need(int(run(['systemctl','--user','show',name,'-p','MainPID','--value']))==row['pid'],'SERVICE_PID_MISMATCH')
                    env=dict(x.split(b'=',1) for x in Path(f"/proc/{row['pid']}/environ").read_bytes().split(b'\0') if b'=' in x)
                    need(all(env.get(k.encode())==v.encode() for k,v in runner.REQUIRED.items()),'PROCESS_CONFIGURATION_MISMATCH')
                m.clean_database(root)
                need(m.sha(root/'.env')==config['env_sha256'],'ENV_CHANGED')
                break
            except Exception: time.sleep(1)
        else: raise RuntimeError('POST_RECOVERY_VERIFICATION_INCOMPLETE')
        run(['systemctl','--user','enable',*['hilega-'+r+'.service' for r in ROLES]])
        state.update(phase='SUPERVISION_ACTIVE_PAUSED_VERIFIED',processes=rows,
                     health=health,bridge_health=checked['bridge_health'],
                     activity_counts=checked['activity_counts'],controller_mode='PAUSED',
                     execution_route='PREPARATION_ONLY',production_execution_enabled=False)
        runner.atomic(marker,state)
        original_state.update(phase=state['phase'],recovery_record=str(marker),processes=rows)
        runner.atomic(state_path,original_state)
        print(json.dumps(state,indent=2))
    except BaseException:
        if marker.exists():
            state['failure_after_phase']=state['phase']
            state['phase']='REQUIRES_REVIEW_NO_AUTOMATIC_RETRY'
            runner.atomic(marker,state)
        raise
    finally:
        for _,fd in handles: os.close(fd)
        lock.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','apply'))
    args=parser.parse_args()
    try: main(args.action=='apply')
    except BaseException as exc:
        print(json.dumps(dict(status='STOPPED_FOR_REVIEW',
            reason=str(exc) if type(exc) is RuntimeError else type(exc).__name__,
            automatic_retry=False,production_execution_enabled=False)))
        raise SystemExit(1)
