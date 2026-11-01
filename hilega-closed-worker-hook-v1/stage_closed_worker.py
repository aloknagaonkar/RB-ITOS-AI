"""Stage/verify a closed worker unit; never install or control a service."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

UNIT = 'hilega-execution-closed-candidate.service'
MARKER = 'HILEGA_CLOSED_WORKER_STAGE_V1'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def quote(value):
    return '"'+str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')+'"'


def stage_worker(repo, *, python=None, source=None, verify_unit=False):
    repo = Path(repo).resolve()
    interpreter = Path(python or sys.executable).absolute()
    source = Path(source or Path(__file__).with_name('fixture_closed_worker.py'))
    need(repo.is_dir() and not any(c.isspace() for c in str(repo)),
         'EXISTING_STAGE_REPO_WITHOUT_WHITESPACE_REQUIRED')
    need(source.is_file() and not source.is_symlink() and interpreter.is_file(),
         'REGULAR_WORKER_SOURCE_AND_PYTHON_REQUIRED')
    raw = source.read_bytes()
    compile(raw, str(source), 'exec')
    folder = Path(tempfile.mkdtemp(prefix='hilega-closed-worker-stage-', dir=repo))
    script = folder/'fixture_closed_worker.py'
    script.write_bytes(raw)
    health = folder/'health'
    health.mkdir(mode=0o700)
    args = [interpreter, script, '--watch', '--interval', '5',
            '--health-file', health/'health.json']
    unit = ('[Unit]\nDescription=Hilega closed execution candidate heartbeat\n\n'
            '[Service]\nType=simple\nWorkingDirectory='+str(repo).replace('%', '%%')+'\n'
            'ExecStart='+' '.join(map(quote, args))+'\n'
            'Restart=on-failure\nRestartSec=5\nUMask=0077\nNoNewPrivileges=yes\n'
            'StandardOutput=journal\nStandardError=journal\n\n'
            '[Install]\nWantedBy=default.target\n')
    (folder/UNIT).write_text(unit)
    report = dict(
        model=MARKER, stage=str(folder), repo=str(repo),
        worker_sha256=hashlib.sha256(raw).hexdigest(),
        unit_sha256=hashlib.sha256(unit.encode()).hexdigest(),
        systemd_unit_verified=False, service_installed=False,
        service_started=False, production_execution_enabled=False)
    (folder/'STAGE.json').write_text(json.dumps(report, indent=2)+'\n')
    if verify_unit:
        binary = shutil.which('systemd-analyze')
        need(binary is not None, 'SYSTEMD_ANALYZE_REQUIRED_FOR_UNIT_VERIFY')
        checked = subprocess.run([binary, '--user', 'verify', str(folder/UNIT)],
                                 text=True, capture_output=True, timeout=30)
        report['unit_verification_returncode'] = checked.returncode
        if checked.returncode:
            report['unit_verification_excerpt'] = checked.stderr[:1500]
            (folder/'STAGE.json').write_text(json.dumps(report, indent=2)+'\n')
        need(checked.returncode == 0, 'CLOSED_UNIT_VERIFICATION_FAILED')
        report['systemd_unit_verified'] = True
    (folder/'STAGE.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def remove_stage(folder):
    folder = Path(folder)
    need(folder.is_dir() and not folder.is_symlink()
         and folder.name.startswith('hilega-closed-worker-stage-'),
         'EXACT_CLOSED_STAGE_DIRECTORY_REQUIRED')
    marker = folder/'STAGE.json'
    need(marker.is_file() and not marker.is_symlink(), 'REGULAR_STAGE_MARKER_REQUIRED')
    row = json.loads(marker.read_text())
    need(row['model'] == MARKER and row['stage'] == str(folder.resolve())
         and row['service_installed'] is False and row['service_started'] is False,
         'CLOSED_STAGE_MARKER_CHANGED')
    allowed = {'fixture_closed_worker.py', UNIT, 'STAGE.json', 'health'}
    need({p.name for p in folder.iterdir()} == allowed,
         'CLOSED_STAGE_UNKNOWN_FILES_REFUSED')
    for name, expected in [('fixture_closed_worker.py', row['worker_sha256']),
                           (UNIT, row['unit_sha256'])]:
        path = folder/name
        need(path.is_file() and not path.is_symlink()
             and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
             'CLOSED_STAGE_SOURCE_CHANGED')
    health = folder/'health'
    need(health.is_dir() and not health.is_symlink(), 'REGULAR_STAGE_HEALTH_DIRECTORY_REQUIRED')
    entries = list(health.iterdir())
    need(all(p.name == 'health.json' and p.is_file() and not p.is_symlink()
             for p in entries), 'UNKNOWN_STAGE_HEALTH_FILES_REFUSED')
    for path in entries:
        value = json.loads(path.read_text())
        need(value.get('model') == 'HILEGA_CLOSED_EXECUTION_WORKER_HEALTH_V1'
             and value.get('worker_state') in {'STOPPED', 'COMPLETED', 'FAILED'}
             and value.get('production_execution_enabled') is False,
             'STOPPED_CLOSED_WORKER_HEALTH_REQUIRED')
    for path in entries:
        path.unlink()
    health.rmdir()
    for name in ('fixture_closed_worker.py', UNIT, 'STAGE.json'):
        (folder/name).unlink()
    folder.rmdir()
    return dict(status='CLOSED_STAGE_REMOVED', service_changed=False,
                production_execution_enabled=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--remove-stage', type=Path)
    args = parser.parse_args()
    result = (remove_stage(args.remove_stage) if args.remove_stage else
              stage_worker(args.repo, verify_unit=True))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
