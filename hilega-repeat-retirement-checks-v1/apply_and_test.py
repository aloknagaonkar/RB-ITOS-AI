"""Install one additive test file and run the fixture regression on the VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    package = Path(__file__).resolve().parent
    name = 'test_fixture_repeat_retirement_hardening.py'
    manifest = json.loads((package/'MANIFEST.json').read_text())
    raw = (package/name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['files'][name]:
        raise SystemExit('STOP: packaged test checksum changed')
    compile(raw, name, 'exec')
    home = Path.home()
    baseline = [
        'test_closed_history_baseline_candidate.py',
        'test_fixture_reference_retirement_candidate.py',
        'test_repeat_entry_cash_candidate.py',
        'test_repeat_entry_preparation_candidate.py',
        'test_fixture_repeat_execution_candidate.py',
        'test_fixture_repeat_exit_candidate.py',
        'test_fixture_repeat_retirement_candidate.py',
    ]
    for required in baseline + ['fixture_repeat_retirement_candidate.py']:
        path = home/required
        if path.is_symlink() or not path.is_file():
            raise SystemExit('STOP: existing regular source required: '+str(path))
    if not (repo/'backend/market_lab').is_dir():
        raise SystemExit('STOP: --repo must identify the RB-ITOS-AI checkout')
    target = home/name
    if target.is_symlink():
        raise SystemExit('STOP: test target is a symlink')
    if target.exists():
        if not target.is_file() or target.read_bytes() != raw:
            raise SystemExit('STOP: differing test target exists; no overwrite')
    else:
        with target.open('xb') as output:
            output.write(raw)
    print('Additive test file ready: '+str(target), flush=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(map(str, [
        home, repo/'backend', repo/'tests', repo,
    ]))
    command = [sys.executable, '-m', 'pytest']
    command += [str(home/file) for file in baseline + [name]]
    command += ['-q']
    code = subprocess.run(command, cwd=repo, env=env).returncode
    print('Installed runtime unchanged; production execution not enabled.', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
