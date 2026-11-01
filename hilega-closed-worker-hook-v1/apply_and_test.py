"""Fast closed-hook checks by default; explicit full regression at release gates."""
import argparse
import ast
import hashlib
import importlib.util
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
    parser.add_argument('--full', action='store_true', help='Run all 171 cases instead of the targeted 13')
    args = parser.parse_args()
    repo, folder, home = args.repo.resolve(), Path(__file__).resolve().parent, Path.home()
    need((repo/'backend/market_lab').is_dir(), '--repo must identify RB-ITOS-AI')
    manifest = json.loads((folder/'MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        path = folder/name
        need(path.is_file() and not path.is_symlink()
             and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
             'package file changed: '+name)
    for name in manifest['baseline_sources']:
        path = home/name
        need(path.is_file() and not path.is_symlink(), 'regular baseline source required: '+name)
        need(ast.dump(ast.parse(path.read_bytes()))
             == ast.dump(ast.parse((folder/'baseline'/name).read_bytes())),
             'passing baseline implementation differs: '+name)
    previous_path = repo/'hilega-reversal-partial-fixture-v1/VM-VALIDATION.json'
    need(previous_path.is_file() and not previous_path.is_symlink(), 'prior 163-case report required')
    previous_raw = previous_path.read_bytes()
    previous = json.loads(previous_raw)
    need(previous.get('status') == 'PASS' and previous.get('collected_cases') == 163
         and previous.get('failed') == previous.get('skipped') == 0
         and previous.get('production_execution_enabled') is False,
         'prior passing fixture checkpoint required')
    writes = []
    for name in manifest['install_files']:
        raw = (folder/name).read_bytes()
        compile(raw, name, 'exec')
        target = home/name
        need(not target.is_symlink(), 'target symlink refused: '+name)
        if target.exists():
            need(target.is_file() and target.read_bytes() == raw,
                 'differing target exists; no overwrite: '+name)
        else:
            writes.append((target, raw))
    for path, raw in writes:
        with path.open('xb') as output:
            output.write(raw)
    full = [
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
        'test_closed_worker_hook.py',
    ]
    quick = [
        'test_closed_worker_hook.py',
        'test_fixture_reversal_partial.py::test_reversal_closes_first_and_requires_fresh_post_resume_entry',
        'test_fixture_reversal_partial.py::test_partial_sell_progress_survives_long_wait_and_restart',
        'test_fixture_cycle_journal.py::test_lost_entry_cursor_recovers_without_capture_or_resend',
        'test_fixture_cycle_journal.py::test_exit_closeout_and_retirement_restart_without_resend',
    ]
    selected = full if args.full else quick
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(map(str, [home, repo/'backend', repo/'tests', repo]))
    print(('Full 171-case regression' if args.full else 'Quick 13-case validation')
          +' ready; baseline sources unchanged.', flush=True)
    with tempfile.TemporaryDirectory(prefix='hilega-closed-hook-tests-') as scratch:
        junit = Path(scratch)/'junit.xml'
        code = subprocess.run([
            sys.executable, '-m', 'pytest', *[str(home/name) for name in selected],
            '-q', '--junitxml='+str(junit),
        ], cwd=repo, env=env).returncode
        cases = list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed = sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped = sum(c.find('skipped') is not None for c in cases)
        expected = 171 if args.full else 13
        passed = code == 0 and len(cases) == expected and failed == skipped == 0
        report = dict(
            status='PASS_FULL' if passed and args.full else 'PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
            scope='CLOSED_WORKER_BOUNDARY_AND_FIXTURE_INJECTION',
            pytest_exit_code=code, collected_cases=len(cases), failed=failed, skipped=skipped,
            full_regression_reexecuted=args.full,
            prior_full_cases_passed=163,
            prior_report_sha256=hashlib.sha256(previous_raw).hexdigest(),
            unchanged_baseline_sources=len(manifest['baseline_sources']),
            service_installed=False, service_started=False,
            production_execution_enabled=False, runtime_deployed=False, production_ready=False)
    if passed:
        try:
            spec = importlib.util.spec_from_file_location('_closed_stage', folder/'stage_closed_worker.py')
            staging = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(staging)
            stage = staging.stage_worker(repo, python=sys.executable,
                                         source=folder/'fixture_closed_worker.py', verify_unit=True)
            stage_path = Path(stage['stage'])
            script, health = stage_path/'fixture_closed_worker.py', stage_path/'health/health.json'
            run_ids = []
            for options, ticks in [(['--watch', '--interval', '1', '--max-ticks', '2'], 2),
                                   (['--once'], 1)]:
                result = subprocess.run([sys.executable, str(script), *options,
                                         '--health-file', str(health)],
                                        text=True, capture_output=True, timeout=15)
                need(result.returncode == 0, 'bounded closed-worker probe failed')
                value = json.loads(health.read_text())
                need(value['worker_state'] == 'COMPLETED' and value['ticks'] == ticks
                     and all(value.get(k) is False for k in (
                         'production_execution_enabled', 'orders_sent_to_upstox',
                         'entry_permission', 'application_database_opened', 'token_loaded')),
                     'closed-worker probe authority or state changed')
                run_ids.append(value['run_id'])
            need(len(set(run_ids)) == 2, 'closed worker restart identity unchanged')
            report.update(staged_unit=stage['stage']+'/'+staging.UNIT,
                          stage=stage['stage'], systemd_unit_verified=True,
                          bounded_closed_startup_and_restart_verified=True,
                          managed_service_control_commands_issued=False)
        except (Exception, SystemExit) as exc:
            report.update(status='FAIL_STAGE_OR_PROBE', staging_error_type=type(exc).__name__,
                          staging_error_reason=str(exc)[:300])
            passed = False
    name = 'FULL-VALIDATION.json' if args.full else 'QUICK-VALIDATION.json'
    path = folder/name
    path.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    print('Report: '+str(path))
    return 0 if passed else code or 1


if __name__ == '__main__':
    raise SystemExit(main())
