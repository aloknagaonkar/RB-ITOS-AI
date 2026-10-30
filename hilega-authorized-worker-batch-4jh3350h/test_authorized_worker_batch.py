
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
