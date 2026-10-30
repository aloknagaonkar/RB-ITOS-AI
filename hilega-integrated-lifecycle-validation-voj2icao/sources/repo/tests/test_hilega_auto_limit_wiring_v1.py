import json
from datetime import timedelta

import pytest

from test_hilega_application_preparation_v1 import env, process, counts
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1 import source as source_module
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked
from market_lab.hilega_preparation_runtime_v1.limit_candidate import stage
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
from market_lab.hilega_production_foundation.core import Store, SimBroker, Service
from market_lab.hilega_preparation_runtime_v1.source import Source


def outbox(env):
    with env["store"].db() as db:
        return json.loads(db.execute(
            "SELECT data FROM preparation_outbox"
        ).fetchone()[0])


def test_confirmed_signal_automatically_persists_disabled_candidate(env):
    process(env)
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    row = outbox(env)
    candidate = row["disabled_request_candidate"]
    assert candidate["preparation_id"] == row["id"]
    assert candidate["reservation_reference"] == row["reservation_reference"]
    assert candidate["draft"]["body"]["order_type"] == "LIMIT"
    assert candidate["draft"]["body"]["quantity"] == 65
    assert candidate["draft"]["body"]["price"] == 100
    assert candidate["draft"]["submission_enabled"] is False
    assert candidate["policy_approved_for_production"] is False
    assert candidate["real_funds_reservation_verified"] is False
    assert candidate["production_execution_enabled"] is False
    assert row["request_body"] is None
    assert env["store"].control()["mode"] == "PAUSED"


@pytest.mark.parametrize("point", ["AFTER_PLAN_INSERT", "BEFORE_COMMIT"])
def test_interruption_rolls_back_plan_hold_outbox_and_candidate(env, point):
    class Interrupted(BaseException):
        pass

    def interrupt(at):
        if at == point:
            raise Interrupted()

    env["source"].checkpoint = interrupt
    with pytest.raises(Interrupted):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    with env["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM preparation_evidence"
        ).fetchone()[0] == 0


def test_candidate_failure_rolls_back_and_pauses(env, monkeypatch):
    def fail(*args, **kwargs):
        raise Blocked("INJECTED_CANDIDATE_FAILURE")

    monkeypatch.setattr(source_module, "build_candidate", fail)
    with pytest.raises(Blocked, match="INJECTED_CANDIDATE_FAILURE"):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert env["store"].control()["mode"] == "PAUSED"
    calls = len(env["calls"])
    env["source"].run_source_once(env["path"])
    assert len(env["calls"]) == calls
    assert counts(env) == (0, 0, 0, 0, 0, 0)


def test_quote_expiry_at_final_commit_rolls_back_and_pauses(env):
    def delay(at):
        if at == "BEFORE_COMMIT":
            env["clock"][0] += timedelta(seconds=11)

    env["source"].checkpoint = delay
    with pytest.raises(Blocked):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert env["store"].control()["mode"] == "PAUSED"


def test_lost_commit_response_restart_preserves_exact_candidate(env):
    class LostResponse(BaseException):
        pass

    def lose(at):
        if at == "AFTER_COMMIT":
            raise LostResponse()

    env["source"].checkpoint = lose
    with pytest.raises(LostResponse):
        process(env)
    original = outbox(env)

    def no_provider():
        pytest.fail("Committed signal must not collect evidence again")

    store = Store(env["store"].path)
    service = Service(store, SimBroker(store), lambda: env["clock"][0])
    restarted = Source(
        service, run_id="synthetic-lease", provider=no_provider,
    )
    restarted.run_source_once(env["path"])
    assert outbox(env) == original
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    assert store.control()["mode"] == "PAUSED"


def test_manual_stager_remains_compatible_with_original_unsent_rows(env):
    process(env)
    row = outbox(env)
    row.pop("disabled_request_candidate")
    with env["store"].db() as db:
        db.execute("UPDATE preparation_outbox SET data=?", (json.dumps(row),))
    result = stage(
        env["s"], row["id"], PIN,
        fee_buffer_cents=10000, profile=PROFILE,
    )
    assert result["idempotent_replay"] is False
    assert result["draft"]["submission_enabled"] is False
    assert counts(env) == (1, 1, 1, 0, 0, 0)
