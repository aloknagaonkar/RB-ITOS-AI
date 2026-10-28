"""Preparation admission tests: temporary DBs and synthetic evidence only."""
import json
from datetime import timedelta

from test_hilega_application_preparation_v1 import (
    env, process, counts, command,
)
from hilega_application_preparation_fixtures import (
    bundle, resign_cash, T,
)


def zero_cash(value):
    for funds in (
        value["cash_before_market"],
        value["cash_after_market"],
        value["cash_capture"]["funds_before"],
        value["cash_capture"]["funds_after"],
    ):
        funds["cash_available_to_trade"] = "0"
    resign_cash(value)


def assert_no_activity(env):
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    with env["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM sim_allocation_reservations"
        ).fetchone()[0] == 0


def audit_counts(env):
    with env["store"].db() as db:
        return (
            db.execute(
                "SELECT COUNT(*) FROM preparation_consumed"
            ).fetchone()[0],
            db.execute(
                "SELECT COUNT(*) FROM preparation_events"
            ).fetchone()[0],
        )


def test_paused_signal_never_calls_evidence_provider(env):
    command(env["s"], "pause")
    process(env)

    assert env["calls"] == []
    assert_no_activity(env)
    assert env["store"].control()["mode"] == "PAUSED"


def test_zero_cash_blocks_plan_hold_and_outbox(env):
    zero_cash(env["data"])
    process(env)

    assert len(env["calls"]) == 1
    assert_no_activity(env)
    assert env["store"].control()["mode"] == "PAUSED"

    with env["store"].db() as db:
        outcome = json.loads(db.execute(
            "SELECT data FROM preparation_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0])
    assert outcome["status"] == "BLOCKED"
    assert "NO_CASH_CAPACITY" in outcome["reasons"]
    assert "HALF_CASH_CAP_EXCEEDED" in outcome["reasons"]


def test_blocked_event_replay_does_not_repeat_provider_or_audit(env):
    zero_cash(env["data"])
    process(env)
    before = audit_counts(env)
    assert before[0] == 1

    # Appends the same event identity in another valid journal record.
    process(env)

    assert len(env["calls"]) == 1
    assert audit_counts(env) == before
    assert_no_activity(env)


def test_restoring_synthetic_cash_and_resuming_does_not_revive_old_event(env):
    zero_cash(env["data"])
    process(env)
    before = audit_counts(env)

    # Restore only this fixture's synthetic evidence.
    env["data"].clear()
    env["data"].update(bundle())
    env["clock"][0] = T + timedelta(seconds=4)
    command(env["s"], "reconcile")
    command(env["s"], "resume")
    assert env["store"].control()["mode"] == "ARMED"

    # The previously blocked identity must remain consumed.
    process(env)

    assert len(env["calls"]) == 1
    assert audit_counts(env) == before
    assert_no_activity(env)