import json
from datetime import datetime, timedelta

import pytest

from test_hilega_atomic_disabled_binding_v1 import (
    bound_env, requests, binding_count,
)
from test_hilega_application_preparation_v1 import env, append, BULL, counts, command
from hilega_application_preparation_fixtures import T, ts, resign_cash


def advance(env, *, fresh_health=True):
    data = env["data"]
    def shifted(value):
        return (datetime.fromisoformat(value) + timedelta(minutes=5)).isoformat()

    for name in ("started_at", "completed_at"):
        data[name] = shifted(data[name])
        data["cash_capture"][name] = shifted(data["cash_capture"][name])
    for quote in data["quotes"].values():
        for name in ("timestamp", "last_trade_time"):
            if name in quote:
                quote[name] = shifted(quote[name])
    resign_cash(data)
    env["clock"][0] = T + timedelta(seconds=303)
    if fresh_health:
        with env["store"].db() as db:
            health = json.loads(db.execute(
                "SELECT data FROM sim_bridge_health WHERE id=1"
            ).fetchone()[0])
            health.update(heartbeat_at=ts(302), source_at=ts(300))
            db.execute(
                "UPDATE sim_bridge_health SET data=? WHERE id=1",
                (json.dumps(health),),
            )


def signal(env):
    append(env["path"], [BULL], at=ts(300))
    return env["source"].run_source_once(env["path"])


def assert_blocked(env):
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert requests(env) == []
    assert binding_count(env) == 0
    assert env["store"].control()["mode"] == "PAUSED"


def test_fresh_signal_after_five_minute_wait_can_prepare(bound_env):
    env = bound_env
    advance(env)
    original = env["store"].control()
    assert (
        env["clock"][0] - datetime.fromisoformat(original["last_reconciled_at"])
    ).total_seconds() > 30
    signal(env)
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    assert len(requests(env)) == binding_count(env) == 1
    control = env["store"].control()
    assert control["mode"] == "PAUSED"
    assert control["resumed_at"] == original["resumed_at"]
    assert control["last_reconciled_at"] == ts(303)
    assert requests(env)[0]["state"] == "PREPARED"
    assert requests(env)[0]["order_id"] is None
    assert requests(env)[0]["reservation_verified"] is False


def test_wait_does_not_bypass_zero_cash(bound_env):
    env = bound_env
    advance(env)
    data = env["data"]
    for funds in (
        data["cash_before_market"], data["cash_after_market"],
        data["cash_capture"]["funds_before"],
        data["cash_capture"]["funds_after"],
    ):
        funds["cash_available_to_trade"] = "0"
    resign_cash(data)
    signal(env)
    assert_blocked(env)


def test_wait_does_not_bypass_stale_source_health(bound_env):
    env = bound_env
    advance(env, fresh_health=False)
    signal(env)
    assert_blocked(env)


def test_wait_does_not_bypass_stale_quotes(bound_env):
    env = bound_env
    advance(env)
    for quote in env["data"]["quotes"].values():
        quote["timestamp"] = ts()
    resign_cash(env["data"])
    signal(env)
    assert_blocked(env)


@pytest.mark.parametrize("case", ["future", "missing", "unreconciled"])
def test_invalid_baseline_is_not_automatically_repaired(bound_env, case):
    env = bound_env
    advance(env)
    with env["store"].db() as db:
        control = json.loads(db.execute(
            "SELECT data FROM control WHERE id=1"
        ).fetchone()[0])
        if case == "future":
            control["last_reconciled_at"] = ts(400)
        elif case == "missing":
            control["last_reconciled_at"] = None
        else:
            control["reconciled"] = False
        db.execute(
            "UPDATE control SET data=? WHERE id=1", (json.dumps(control),),
        )
    signal(env)
    assert_blocked(env)


def test_operator_pause_during_wait_prevents_admission(bound_env):
    env = bound_env
    advance(env)
    command(env["s"], "pause")
    calls = len(env["calls"])
    signal(env)
    assert_blocked(env)
    assert len(env["calls"]) == calls
