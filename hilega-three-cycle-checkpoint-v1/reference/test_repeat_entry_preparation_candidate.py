from copy import deepcopy
from datetime import datetime, timedelta
import json
import pytest

from repeat_entry_preparation_candidate import prepare_repeat_fixture
from fixture_reference_retirement_candidate import retire_fixture_references, ACTIVE
from test_repeat_entry_cash_candidate import (
    synthetic_scope, env, bound_env, module, prepared,
    lifecycle, closed, history, reentry,
)
from test_hilega_application_preparation_v1 import append, BULL
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.source import pending
from market_lab.hilega_production_simulator_bridge_v1 import verified_records
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

BEAR = "ENTRY_BEARISH_ROUTE_B_STRUCTURAL"


def resign(value):
    value.pop("signature", None)
    value["signature"] = sign(value, PIN)


@pytest.fixture
def second(closed, reentry):
    life, data, sequence, fees = closed
    e, mod, execution = life[0]
    retire_fixture_references(
        e["store"], execution.path, data[1], PIN,
        entry_id=data[2], journal=e["path"], exit_sequences=[sequence],
        clock=lambda: datetime.fromisoformat(data[3]))
    account, cash, archived, at = deepcopy(reentry)
    old_now = datetime.fromisoformat(at)
    now = (old_now + timedelta(
        minutes=5-old_now.minute % 5)).replace(second=0, microsecond=0)
    account.update(
        generated_at=now.isoformat(), completed_at=now.isoformat(),
        session_date=now.date().isoformat())
    cash.update(
        started_at=now.isoformat(), completed_at=now.isoformat(),
        session_date=now.date().isoformat())
    if "generated_at" in cash:
        cash["generated_at"] = now.isoformat()
    resign(account)
    resign(cash)
    old_source = archived["source"]
    old_id = archived["entry_id"]
    market = json.loads(old_source["evidence"][
        old_source["bindings"][old_id]["bundle_fingerprint"]])
    market["started_at"] = now.isoformat()
    market["completed_at"] = now.isoformat()
    for quote in market["quotes"].values():
        for field in ("timestamp", "last_trade_time"):
            if field in quote:
                old = quote[field]
                quote[field] = (
                    int(now.timestamp()*1000)
                    if isinstance(old, (int, float)) else now.isoformat())
    resign(market)
    e["clock"][0] = now
    with e["store"].db() as db:
        control = json.loads(db.execute(
            "SELECT data FROM control WHERE id=1").fetchone()[0])
        control.update(
            mode="ARMED", version=control["version"]+1, reconciled=True,
            resumed_at=(now-timedelta(seconds=1)).isoformat(),
            last_reconciled_at=now.isoformat())
        db.execute("UPDATE control SET data=? WHERE id=1",
                   (json.dumps(control),))
        health = json.loads(db.execute(
            "SELECT data FROM sim_bridge_health WHERE id=1").fetchone()[0])
        # Refresh synthetic health while preserving its original age/intervals.
        delta = now-old_now
        def shifted(value):
            if isinstance(value, dict):
                return {k: shifted(v) for k, v in value.items()}
            if isinstance(value, list):
                return [shifted(v) for v in value]
            if isinstance(value, str):
                try:
                    stamp = datetime.fromisoformat(value)
                    if stamp.tzinfo is not None:
                        return (stamp+delta).isoformat()
                except ValueError:
                    pass
            return value
        health = shifted(health)
        db.execute("UPDATE sim_bridge_health SET data=? WHERE id=1",
                   (json.dumps(health),))
    return dict(
        e=e, execution=execution, account=account, cash=cash, market=market,
        now=now, version=control["version"], run_id=health["run_id"],
        sequence=None, old_requests=deepcopy(execution.requests()))



def run(case, *, bearish=False, clock=None, checkpoint=lambda stage: None):
    if case["sequence"] is None:
        append(
            case["e"]["path"], [BEAR if bearish else BULL],
            at=case["now"].isoformat())
        case["sequence"] = verified_records(
            case["e"]["path"])[-1]["sequence"]
    return prepare_repeat_fixture(
        case["e"]["store"], case["execution"].path, PIN,
        journal=case["e"]["path"], sequence=case["sequence"],
        account_capture=case["account"], cash_capture=case["cash"],
        market_bundle=case["market"], expected_version=case["version"],
        bridge_run_id=case["run_id"], fee_buffer_paise=10000,
        clock=clock or (lambda: case["now"]), checkpoint=checkpoint)


def active_counts(case):
    with case["e"]["store"].db() as db:
        return {
            table: db.execute(
                "SELECT COUNT(*) FROM "+table).fetchone()[0]
            for table in ACTIVE
        }


@pytest.mark.parametrize("bearish", [False, True])
def test_second_entry_prepared_with_history_preserved(second, bearish):
    result = run(second, bearish=bearish)
    assert result["status"] == "FIXTURE_SECOND_ENTRY_PREPARED_DISABLED"
    assert result["direction"] == ("BEARISH" if bearish else "BULLISH")
    assert result["budget_paise"] <= result["half_cash_cap_paise"]
    assert all(n == 1 for n in active_counts(second).values())
    saved = second["execution"].requests()
    assert len(saved) == len(second["old_requests"]) + 1
    for old in second["old_requests"]:
        assert old in saved
    assert second["e"]["store"].control()["mode"] == "PAUSED"
    assert pending(second["e"]["store"])
    new = next(
        r for r in saved if r["request_id"] == result["request_id"])
    assert new["state"] == "PREPARED"
    assert new["order_id"] is None
    assert result["orders_sent"] is False


def test_repeat_preparation_replay_is_idempotent(second):
    run(second)
    again = run(second)
    assert again["idempotent_replay"] is True
    assert len(second["execution"].requests()) == len(second["old_requests"]) + 1


@pytest.mark.parametrize("stage", [
    "AFTER_ACTIVE_REFERENCES",
    "AFTER_DISABLED_REQUEST_INSERT",
    "BEFORE_REPEAT_COMMIT",
])
def test_interruption_rolls_back_both_databases(second, stage):
    def interrupt(current):
        if current == stage:
            raise RuntimeError("SYNTHETIC_REPEAT_INTERRUPTION")
    with pytest.raises(RuntimeError):
        run(second, checkpoint=interrupt)
    assert all(n == 0 for n in active_counts(second).values())
    assert second["execution"].requests() == second["old_requests"]
    assert second["e"]["store"].control()["mode"] == "ARMED"



def test_insufficient_fresh_cash_blocks(second):
    for field in ("funds_before", "funds_after"):
        second["cash"][field]["cash_available_to_trade"] = "1"
    resign(second["cash"])
    with pytest.raises(ValueError, match="REPEAT_ENTRY_CASH_BLOCKED"):
        run(second)
    assert all(n == 0 for n in active_counts(second).values())


def test_paused_controller_blocks(second):
    with second["e"]["store"].db() as db:
        control = json.loads(db.execute(
            "SELECT data FROM control WHERE id=1").fetchone()[0])
        control["mode"] = "PAUSED"
        db.execute("UPDATE control SET data=? WHERE id=1",
                   (json.dumps(control),))
    with pytest.raises(ValueError, match="CONTROL_RESUME_OR_STOP"):
        run(second)


def test_stale_market_blocks(second):
    second["market"]["started_at"] = (
        second["now"]-timedelta(seconds=31)).isoformat()
    resign(second["market"])
    with pytest.raises(ValueError):
        run(second)
    assert second["execution"].requests() == second["old_requests"]


def test_expiry_before_commit_rolls_back(second):
    times = iter([
        second["now"], second["now"]+timedelta(minutes=5),
    ])
    with pytest.raises(ValueError):
        run(second, clock=lambda: next(times))
    assert all(n == 0 for n in active_counts(second).values())
    assert second["execution"].requests() == second["old_requests"]

