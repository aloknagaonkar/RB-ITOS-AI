"""Add isolated third-entry fixture candidates; run regression on the user's VM."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def need(ok, reason):
    if not ok:
        raise SystemExit('STOP: '+reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    folder = Path(__file__).resolve().parent
    home = Path.home()
    manifest = json.loads((folder/'MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        path = folder/name
        need(path.is_file() and not path.is_symlink(), 'regular packaged file required: '+name)
        need(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
             'package checksum changed: '+name)
    need((repo/'backend/market_lab').is_dir(), '--repo must be the RB-ITOS-AI checkout')
    for name in manifest['baseline_sources']:
        installed = home/name
        need(installed.is_file() and not installed.is_symlink(), 'regular baseline required: '+name)
        # Permit whitespace/comments only; reject any changed Python statement.
        expected = ast.dump(ast.parse((folder/'baseline'/name).read_text()))
        current = ast.dump(ast.parse(installed.read_text()))
        need(current == expected, 'baseline implementation differs: '+name)
    suites = [
        'test_closed_history_baseline_candidate.py',
        'test_fixture_reference_retirement_candidate.py',
        'test_repeat_entry_cash_candidate.py',
        'test_repeat_entry_preparation_candidate.py',
        'test_fixture_repeat_execution_candidate.py',
        'test_fixture_repeat_exit_candidate.py',
        'test_fixture_repeat_retirement_candidate.py',
        'test_fixture_repeat_retirement_hardening.py',
        'test_third_entry_preparation_candidate.py',
    ]
    for name in suites[:-1] + ['fixture_repeat_retirement_candidate.py']:
        path = home/name
        need(path.is_file() and not path.is_symlink(), 'regular existing source required: '+name)
    writes = []
    for name in manifest['install_files']:
        raw = (folder/name).read_bytes()
        compile(raw, name, 'exec')
        target = home/name
        need(not target.is_symlink(), 'symlink target refused: '+name)
        if target.exists():
            need(target.is_file() and target.read_bytes() == raw,
                 'differing target exists; no overwrite: '+name)
        else:
            writes.append((target, raw))
    for target, raw in writes:
        with target.open('xb') as output:
            output.write(raw)
    print('Isolated third-entry candidate files ready; existing sources unchanged.', flush=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(map(str, [home, repo/'backend', repo/'tests', repo]))
    with tempfile.TemporaryDirectory(prefix='hilega-third-entry-results-') as scratch:
        junit = Path(scratch)/'junit.xml'
        command = [sys.executable, '-m', 'pytest']
        command += [str(home/name) for name in suites]
        command += ['-q', '--junitxml='+str(junit)]
        code = subprocess.run(command, cwd=repo, env=env).returncode
        counts = {}
        if junit.is_file():
            root = ET.parse(junit).getroot()
            cases = list(root.iter('testcase'))
            counts = dict(
                collected_cases=len(cases),
                failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases),
                skipped=sum(c.find('skipped') is not None for c in cases))
        report = dict(
            status='PASS' if code == 0 else 'FAIL', pytest_exit_code=code,
            scope='SYNTHETIC_FIXTURE_DISABLED_THIRD_ENTRY_PREPARATION',
            third_buy_submission_implemented=False,
            production_execution_enabled=False, runtime_deployed=False,
            production_ready=False, **counts)
        path = folder/'VM-VALIDATION.json'
        path.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
        print('Report: '+str(path))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
