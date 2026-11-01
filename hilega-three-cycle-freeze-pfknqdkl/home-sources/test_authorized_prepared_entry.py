from datetime import timedelta

import pytest

from authorized_prepared_entry import execute_prepared_fixture
from test_authorized_attempt import module
from test_automatic_entry_fixture import synthetic_scope, env, bound_env
from test_hilega_application_preparation_v1 import process
from hilega_application_preparation_fixtures import PIN


@pytest.fixture
def prepared(bound_env, module, tmp_path):
    e = bound_env
    process(e)
    execution = module.Store(
        tmp_path / "authorized-execution.sqlite", PIN["scope"], "OFFLINE_FIXTURE")
    return e, module, execution


def run(prepared, clock=None):
    e, module, execution = prepared
    return execute_prepared_fixture(
        e["store"], e["adapter_store"].path, execution, PIN,
        adapter_module=module,
        clock=clock or (lambda: e["clock"][0]),
    )


def counts(prepared):
    _, _, execution = prepared
    with execution.tx() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='fixture_authorization_claims'"
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM fixture_authorization_claims"
        ).fetchone()[0] if exists else 0
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    return claims, attempts


def test_preparation_authorization_and_attempt_connect(prepared):
    e, module, execution = prepared
    before = e["store"].path.read_bytes()
    result = run(prepared)
    assert result["status"] == "AUTHORIZED_FIXTURE_ATTEMPT_COMMITTED"
    assert counts(prepared) == (1, 1)
    assert len(module.FixtureTransport(execution).orders()) == 1
    assert e["store"].path.read_bytes() == before


def test_stale_preparation_creates_no_attempt(prepared):
    e, _, _ = prepared
    with pytest.raises(ValueError, match="^FRESH_ENTRY_PRECONDITIONS_REQUIRED$"):
        run(prepared, clock=lambda: e["clock"][0] + timedelta(minutes=5))
    assert counts(prepared) == (0, 0)


def test_expiry_before_attempt_rolls_back_authorization(prepared):
    e, _, _ = prepared
    times = iter([e["clock"][0], e["clock"][0] + timedelta(minutes=5)])
    with pytest.raises(
        ValueError, match="^ENTRY_EVIDENCE_EXPIRED_BEFORE_ATTEMPT$"
    ):
        run(prepared, clock=lambda: next(times))
    assert counts(prepared) == (0, 0)


def test_delayed_replay_recovers_without_another_attempt(prepared):
    e, module, execution = prepared
    run(prepared)
    result = run(
        prepared, clock=lambda: e["clock"][0] + timedelta(minutes=5))
    assert result["recovery_only"] is True
    assert result["new_attempt_created"] is False
    assert counts(prepared) == (1, 1)
    assert len(module.FixtureTransport(execution).orders()) == 1