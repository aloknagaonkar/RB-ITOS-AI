"""Guarded correction to the third-entry synthetic cash fixture only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    folder = Path(__file__).resolve().parent
    fix = json.loads((folder/'FIX.json').read_text())
    name = fix['file']
    raw = (folder/name).read_bytes()
    if digest(raw) != fix['updated_sha256']:
        raise SystemExit('STOP: correction checksum changed')
    compile(raw, name, 'exec')
    target = Path.home()/name
    if target.is_symlink() or not target.is_file():
        raise SystemExit('STOP: existing regular test source required')
    if digest(target.read_bytes()) not in {
        fix['previous_sha256'], fix['updated_sha256'],
    }:
        raise SystemExit('STOP: local test differs from the delivered versions')
    original = repo/'hilega-third-entry-admission-v1'
    # Keep the original runner usable after the correction when it is present.
    manifest_path = original/'MANIFEST.json'
    packaged_test = original/name
    manifest = None
    if original.exists():
        if original.is_symlink() or manifest_path.is_symlink() or packaged_test.is_symlink():
            raise SystemExit('STOP: symlink package refused')
        manifest = json.loads(manifest_path.read_text())
        if digest(packaged_test.read_bytes()) not in {
            fix['previous_sha256'], fix['updated_sha256'],
        } or manifest['files'].get(name) not in {
            fix['previous_sha256'], fix['updated_sha256'],
        }:
            raise SystemExit('STOP: original package test or checksum changed')
    target.write_bytes(raw)
    if manifest is not None:
        packaged_test.write_bytes(raw)
        manifest['files'][name] = fix['updated_sha256']
        manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    print('Synthetic cash diagnostics preserved; candidate runtime code unchanged.', flush=True)
    if manifest is not None:
        return subprocess.run([
            sys.executable, str(original/'apply_and_test.py'), '--repo', str(repo),
        ], cwd=repo).returncode
    suites = [
        'test_closed_history_baseline_candidate.py',
        'test_fixture_reference_retirement_candidate.py',
        'test_repeat_entry_cash_candidate.py',
        'test_repeat_entry_preparation_candidate.py',
        'test_fixture_repeat_execution_candidate.py',
        'test_fixture_repeat_exit_candidate.py',
        'test_fixture_repeat_retirement_candidate.py',
        'test_fixture_repeat_retirement_hardening.py', name,
    ]
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(map(str, [
        Path.home(), repo/'backend', repo/'tests', repo,
    ]))
    return subprocess.run([
        sys.executable, '-m', 'pytest',
        *[str(Path.home()/n) for n in suites], '-q',
    ], cwd=repo, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
