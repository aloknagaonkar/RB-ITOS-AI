"""Consolidated authorized-worker validation. Synthetic execution only."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path.cwd().resolve()
HOME = Path.home()
PINS = {
    "scripts/hilega_production_simulator_bridge.py":
        "9fd8bc6b22af63229f59743722cfb156b12feb0ca279bc2117a103d02670de98",
    "hilega-worker-handoff-stage-51fc37nx/hilega_production_simulator_bridge.py":
        "24a2d5b3ded4c929016c9dcc55933e19141dd19371dd44ce654d61a8ef2fa16c",
    "hilega-authorized-attempt-stage-xzqykzdz/adapter.py":
        "82c7606a4c4aad8b540b59db35766a736982dac18e9501f26179d9e8fe24b4a4",
    "backend/market_lab/hilega_preparation_runtime_v1/source.py":
        "dbfce30057763b93e8f7f8332e86e2145890bd29c72d18016b3ad944125e6150",
    "hilega-ownership-producer-tools-v1/manifest.json":
        "b27b573928bf485db585ce59183e0a74c6b15de50d933e990c5443d8f14426fe",
}

def digest(path):
    if (not path.is_file() or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise SystemExit("STOP: regular source required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

for name, expected in PINS.items():
    if digest(ROOT / name) != expected:
        raise SystemExit("STOP: source changed: " + name)

folder = Path(tempfile.mkdtemp(
    prefix="hilega-authorized-worker-batch-", dir=ROOT))
test = folder / "test_authorized_worker_batch.py"
test.write_text(r'''
from datetime import timedelta
from unittest.mock import patch
import pytest

from test_worker_handoff import worker
from test_authorized_attempt import module
from test_automatic_entry_fixture import synthetic_scope, env, bound_env
from test_hilega_application_preparation_v1 import append, BULL
from hilega_application_preparation_fixtures import PIN
from authorized_prepared_entry import execute_prepared_fixture


@pytest.fixture
def setup(bound_env, module, tmp_path):
    e = bound_env
    execution = module.Store(
        tmp_path / "worker-authorized.sqlite",
        PIN["scope"], "OFFLINE_FIXTURE")
    append(e["path"], [BULL])
    return e, module, execution


def handoff(setup, clock=None):
    e, module, execution = setup
    return lambda: execute_prepared_fixture(
        e["store"], e["adapter_store"].path, execution, PIN,
        adapter_module=module,
        clock=clock or (lambda: e["clock"][0]),
    )


def counts(setup):
    e, module, execution = setup
    with execution.tx() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE name='fixture_authorization_claims'"
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM fixture_authorization_claims"
        ).fetchone()[0] if exists else 0
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    return claims, attempts


def test_worker_signal_creates_one_authorized_fake_attempt(worker, setup):
    e, module, execution = setup
    result = worker.preparation_tick(
        e["source"], e["path"], test_handoff=handoff(setup))
    assert result["execution_handoff"]["status"] == (
        "AUTHORIZED_FIXTURE_ATTEMPT_COMMITTED")
    assert counts(setup) == (1, 1)
    assert len(module.FixtureTransport(execution).orders()) == 1
    assert e["store"].control()["mode"] == "PAUSED"


def test_repeated_worker_tick_recovers_without_another_attempt(worker, setup):
    e, module, execution = setup
    worker.preparation_tick(
        e["source"], e["path"], test_handoff=handoff(setup))
    later = e["clock"][0] + timedelta(minutes=5)
    result = worker.preparation_tick(
        e["source"], e["path"],
        test_handoff=handoff(setup, clock=lambda: later))
    assert result["execution_handoff"]["recovery_only"] is True
    assert counts(setup) == (1, 1)
    assert len(module.FixtureTransport(execution).orders()) == 1


def test_expiry_at_attempt_creation_blocks_worker_execution(worker, setup):
    e, module, execution = setup
    times = iter([
        e["clock"][0],
        e["clock"][0] + timedelta(minutes=5),
    ])
    with pytest.raises(
        ValueError, match="^ENTRY_EVIDENCE_EXPIRED_BEFORE_ATTEMPT$"
    ):
        worker.preparation_tick(
            e["source"], e["path"],
            test_handoff=handoff(setup, clock=lambda: next(times)))
    assert counts(setup) == (0, 0)
    assert module.FixtureTransport(execution).orders() == []


def test_lost_worker_result_restarts_without_duplicate(worker, setup):
    e, module, execution = setup
    original_handoff = handoff(setup)

    class LostResult(BaseException):
        pass

    def interrupted_handoff():
        original_handoff()
        raise LostResult()

    with pytest.raises(LostResult):
        worker.preparation_tick(
            e["source"], e["path"], test_handoff=interrupted_handoff)

    later = e["clock"][0] + timedelta(minutes=5)
    with patch.object(
        module.FixtureTransport, "send",
        side_effect=AssertionError("Recovery must not resubmit"),
    ):
        result = worker.preparation_tick(
            e["source"], e["path"],
            test_handoff=handoff(setup, clock=lambda: later))
    assert result["execution_handoff"]["recovery_only"] is True
    assert counts(setup) == (1, 1)
    assert len(module.FixtureTransport(execution).orders()) == 1
''')

names = [
    "test_automatic_entry_fixture.py",
    "test_automatic_exit_fixture.py",
    "test_automatic_exit_entry_quantity.py",
    "test_fixture_event_dispatcher.py",
    "test_fixture_journal_consumer.py",
    "test_fixture_consumer_integrity.py",
    "test_delayed_fixture_recovery.py",
    "test_fixture_recovery_boundaries.py",
    "test_worker_handoff.py",
    "test_worker_main_routes.py",
    "test_fixture_execution_authorization.py",
    "test_authorized_attempt.py",
    "test_authorized_attempt_recovery.py",
    "test_authorized_prepared_entry.py",
    "test_application_entry_handoff.py",
    "test_worker_application_adapter.py",
]
paths = [HOME / name for name in names]
for path in paths:
    digest(path)
sources = [
    HOME / name for name in (
        "authorized_prepared_entry.py",
        "fixture_execution_authorization.py",
        "application_entry_handoff.py",
        "dispatch_precondition_review.py",
        "automatic_entry_fixture.py",
        "automatic_exit_fixture.py",
        "fixture_event_dispatcher.py",
        "fixture_journal_consumer.py",
        "fixture_attempt_recovery.py",
    )
]
before = {str(p): digest(p) for p in paths + sources}

environment = dict(os.environ)
environment["PYTHONPATH"] = os.pathsep.join(map(str, (
    HOME, ROOT / "backend", ROOT / "tests", ROOT,
)))
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *map(str, paths), str(test)],
    cwd=ROOT, env=environment, check=False,
)

for name, expected in PINS.items():
    if digest(ROOT / name) != expected:
        raise SystemExit("STOP: pinned source changed during validation")
for name, expected in before.items():
    if digest(Path(name)) != expected:
        raise SystemExit("STOP: component changed during validation")

report = dict(
    status="PASS" if result.returncode == 0 else "FAILED_REVIEW_REQUIRED",
    assessed_at=datetime.now(timezone.utc).isoformat(),
    pytest_exit_code=result.returncode,
    scope="SYNTHETIC_TEMPORARY_DATABASES_ONLY",
    tested_component_sha256=before,
    installed_and_staged_pins=PINS,
    worker_integration="INJECTED_AUTHORIZED_FIXTURE_HANDOFF",
    running_service_hook_installed=False,
    production_authorization_available=False,
    services_restarted=False,
    orders_sent_to_upstox=False,
    production_execution_enabled=False,
    production_ready=False,
)
output = folder / "VALIDATION.json"
output.write_text(json.dumps(report, indent=2))
print(json.dumps({
    "status": report["status"],
    "pytest_exit_code": result.returncode,
    "report": str(output),
    "production_execution_enabled": False,
    "runtime_deployed": False,
}, indent=2))
raise SystemExit(result.returncode)