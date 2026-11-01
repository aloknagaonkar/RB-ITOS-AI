from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

import fixture_closed_worker as worker
from stage_closed_worker import stage_worker, remove_stage, UNIT
from test_fixture_reversal_partial import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed,
    third, third_ready, third_position, third_completed, cycle_base,
    harness_v1, harness_v2, queue_entry,
)


def test_default_worker_tick_is_closed_without_fixture_imports():
    result = worker.worker_tick()
    assert result['status'] == 'EXECUTION_HANDOFF_CLOSED_IN_CODE'
    for key in ('production_execution_enabled', 'orders_sent_to_upstox',
                'application_database_opened', 'token_loaded', 'entry_permission'):
        assert result[key] is False


def test_worker_hook_runs_exact_fixture_consumer(harness_v2):
    h = harness_v2
    queue_entry(h)
    result = worker.worker_tick(fixture_consumer=h.consumer)
    assert result['status'] == 'ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED'
    assert result['fixture_consumer_used'] is True
    assert result['production_execution_enabled'] is False


def test_arbitrary_worker_consumer_is_rejected():
    class Arbitrary:
        def poll(self):
            raise AssertionError('Unapproved consumer invoked')
    with pytest.raises(ValueError, match='EXACT_FIXTURE_WORKER_CONSUMER_REQUIRED'):
        worker.worker_tick(fixture_consumer=Arbitrary())


def test_cli_once_ignores_execution_environment(tmp_path):
    env = dict(os.environ, HILEGA_PRODUCTION_WORKSPACE_MODE='LIVE',
               HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',
               HILEGA_PRODUCTION_BROKER_READ_TOKEN='DO_NOT_READ_THIS_TEST_TOKEN')
    result = subprocess.run([sys.executable, worker.__file__, '--once'],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    value = json.loads(result.stdout)
    assert value['production_execution_enabled'] is False
    assert value['application_database_opened'] is False
    assert value['token_loaded'] is False
    assert 'DO_NOT_READ_THIS_TEST_TOKEN' not in result.stdout+result.stderr
    assert not list(tmp_path.glob('*.sqlite'))


def test_watch_heartbeat_stop_and_restart(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path/'health.json'
    runs = []
    for _ in range(2):
        process = subprocess.Popen([
            sys.executable, worker.__file__, '--watch', '--interval', '1',
            '--health-file', str(path),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic()+5
            while time.monotonic() < until:
                if process.poll() is not None:
                    raise AssertionError('Closed worker exited before heartbeat')
                if path.exists():
                    value = json.loads(path.read_text())
                    if value.get('worker_state') == 'RUNNING' and value.get('run_id') not in runs:
                        break
                time.sleep(0.05)
            else:
                raise AssertionError('Closed worker heartbeat not observed')
            checked = worker.validate_health(path)
            assert checked['status'] == 'CLOSED_WORKER_HEALTH_PASS'
            runs.append(checked['run_id'])
            process.terminate()
            process.communicate(timeout=5)
            assert process.returncode == 0
            assert json.loads(path.read_text())['worker_state'] == 'STOPPED'
            with pytest.raises(ValueError, match='CLOSED_WORKER_NOT_RUNNING'):
                worker.validate_health(path)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    assert len(set(runs)) == 2


def test_health_stale_and_authority_changes_are_rejected(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path/'health.json'
    at = worker.now()
    value = dict(worker.worker_tick(), model=worker.MODEL, run_id='synthetic',
                 ticks=1, worker_state='RUNNING', heartbeat_at=at.isoformat(),
                 worker_sha256=hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest())
    worker.write_health(path, value)
    with pytest.raises(ValueError, match='STALE_OR_FUTURE'):
        worker.validate_health(path, as_of=at+timedelta(seconds=31))
    worker.write_health(path, dict(value, production_execution_enabled=True))
    with pytest.raises(ValueError, match='AUTHORITY_CHANGED'):
        worker.validate_health(path, as_of=at)


def test_health_symlink_and_other_target_are_refused(tmp_path):
    tmp_path.chmod(0o700)
    target = tmp_path/'existing.json'
    target.write_text('{"private":"preserve"}')
    target.chmod(0o600)
    link = tmp_path/'health.json'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='HEALTH_SYMLINK_REFUSED'):
        worker.write_health(link, {})
    with pytest.raises(ValueError, match='HEALTH_TARGET_MODEL_MISMATCH'):
        worker.write_health(target, {})
    assert target.read_text() == '{"private":"preserve"}'


def test_stage_and_rollback_preserve_unrelated_files(tmp_path):
    sentinel = tmp_path/'existing-application.txt'
    sentinel.write_text('unchanged')
    result = stage_worker(tmp_path, source=worker.__file__, verify_unit=False)
    folder = Path(result['stage'])
    unit = (folder/UNIT).read_text()
    assert 'WorkingDirectory='+str(tmp_path)+'\n' in unit
    assert 'WorkingDirectory="' not in unit
    assert '--watch' in unit and '--health-file' in unit
    assert 'EnvironmentFile' not in unit
    assert result['service_installed'] is False
    assert remove_stage(folder)['status'] == 'CLOSED_STAGE_REMOVED'
    assert sentinel.read_text() == 'unchanged'
