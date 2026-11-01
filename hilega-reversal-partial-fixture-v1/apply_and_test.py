"""Add explicit fixture reversal and partial-exit tracking; run regression on the user's VM."""
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
        'test_fixture_third_execution_candidate.py',
        'test_fixture_third_exit_candidate.py',
        'test_fixture_third_retirement_candidate.py',
        'test_reusable_fixture_cycle.py',
        'test_fixture_cycle_journal.py',
        'test_fixture_reversal_partial.py',
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
    print('Exit-first reversal and partial-exit fixture candidate ready; existing sources unchanged.', flush=True)
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
        required = {
            'test_same_api_completes_ten_total_cycles',
            'test_journal_drives_two_cycles_with_restart_and_next_entry',
            'test_reversal_closes_first_and_requires_fresh_post_resume_entry',
            'test_reversal_retirement_cursor_restart_never_buys_opposite',
            'test_partial_sell_progress_survives_long_wait_and_restart',
            'test_fill_regression_blocks_without_resubmission',
            'test_unknown_reversal_sell_blocks_opposite_and_retry',
        }
        outcomes = {}
        if junit.is_file():
            for case in ET.parse(junit).getroot().iter('testcase'):
                if case.get('name') in required:
                    outcomes[case.get('name')] = all(case.find(tag) is None
                        for tag in ('failure', 'error', 'skipped'))
        key_cases_verified = set(outcomes) == required and all(outcomes.values())
        complete = (code == 0 and counts.get('collected_cases') == 163
                    and counts.get('failed') == 0 and counts.get('skipped') == 0
                    and key_cases_verified)
        report = dict(
            status='PASS' if complete else 'FAIL_OR_INCOMPLETE',
            pytest_exit_code=code,
            scope='SYNTHETIC_EXIT_FIRST_REVERSAL_AND_PARTIAL_EXIT_PROGRESS',
            exit_first_reversal_policy_implemented=True,
            working_partial_exit_tracking_implemented=True,
            key_policy_and_recovery_cases_verified=key_cases_verified,
            immediate_opposite_buy_enabled=False,
            automatic_residual_resubmission_enabled=False,
            broker_cancel_reprice_enabled=False,
            running_service_hook_installed=False,
            production_execution_enabled=False, runtime_deployed=False,
            production_ready=False, **counts)
        if code == 0 and not complete:
            code = 1
        path = folder/'VM-VALIDATION.json'
        path.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
        print('Report: '+str(path))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
