from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from unittest.mock import Mock, patch

import pytest

from fixture_repeat_exit_candidate import (
    execute_repeat_exit_fixture, record_repeat_closeout, CLOSEOUTS,
)
from test_fixture_repeat_execution_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, run as run_buy,
)
from hilega_application_preparation_fixtures import PIN
from test_hilega_application_preparation_v1 import append
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    sign,
)


def resign(value):
    value.pop("signature", None)
    value["signature"] = sign(value, PIN)
    return value


@pytest.fixture
def position(ready):
    run_buy(ready)
    setup = ready["setup"]
    transport = ready["mod"].FixtureTransport(setup["execution"])
    parent = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == ready["key"])
    transport.fill(
        parent["order_id"], parent["draft"]["body"]["quantity"])
    now = setup["now"] + timedelta(minutes=5)
    setup["e"]["clock"][0] = now
    name = (
        "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"
        if parent["direction"] == "BULLISH"
        else "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21")
    path = setup["e"]["path"]
    append(path, [name], at=now.isoformat())
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    row = rows[-1]
    row["payload"]["event_details"][0]["entry_time"] = parent["signal_at"]
    row.pop("record_hash")
    row["record_hash"] = hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode()).hexdigest()
    path.write_text("\n".join(json.dumps(r) for r in rows)+"\n")
    return dict(
        case=ready, parent=parent, transport=transport,
        now=now, sequence=len(rows))


def account_snapshot(position):
    case = position["case"]
    setup = case["setup"]
    now = position["now"]
    snapshot = deepcopy(case["captures"]["account"])
    old_ids = {o["order_id"] for o in snapshot["orders"]}
    requests = {
        r["order_id"]: r for r in setup["execution"].requests()
        if r.get("order_id")
    }
    for order in position["transport"].orders():
        oid = order["order_id"]
        if oid in old_ids:
            continue
        request = requests.get(oid)
        if request is None:
            raise AssertionError("Unbound fixture order")
        pending = (
            order["quantity"]-order["filled"]
            if order["status"] in {"OPEN", "PARTIAL"} else 0)
        snapshot["orders"].append(dict(
            order_id=oid, instrument=order["instrument"],
            product=order["product"], side=order["side"],
            quantity=order["quantity"], filled=order["filled"],
            pending=pending, status=order["status"],
            source_status=order["status"].lower(),
            placed_at=request["signal_at"]))
        if order["filled"]:
            snapshot["trades"].append(dict(
                order_id=oid, trade_id="synthetic-"+oid,
                instrument=order["instrument"],
                product=order["product"], side=order["side"],
                quantity=order["filled"],
                price=str(request["draft"]["body"]["price"]),
                filled_at=now.isoformat()))
    quantities = {
        (p["instrument"], p["product"]): 0
        for p in snapshot["positions"]
    }
    for trade in snapshot["trades"]:
        key = (trade["instrument"], trade["product"])
        quantities[key] = quantities.get(key, 0) + (
            trade["quantity"] if trade["side"] == "BUY"
            else -trade["quantity"])
    snapshot["positions"] = [
        dict(instrument=k[0], product=k[1], quantity=q)
        for k, q in quantities.items()
    ]
    snapshot.update(
        generated_at=now.isoformat(), completed_at=now.isoformat(),
        session_date=now.date().isoformat(),
        snapshot_id="synthetic-repeat-exit-"+str(
            len(snapshot["trades"])))
    return resign(snapshot)


def market_snapshot(position):
    value = deepcopy(position["case"]["captures"]["market"])
    now = position["now"]
    value.update(
        started_at=now.isoformat(), completed_at=now.isoformat(),
        session_date=now.date().isoformat())
    for quote in value["quotes"].values():
        for field in ("timestamp", "last_trade_time"):
            if field in quote:
                quote[field] = (
                    int(now.timestamp()*1000)
                    if isinstance(quote[field], (int, float))
                    else now.isoformat())
    return resign(value)


def run_exit(position, *, provider=None, clock=None, **kwargs):
    case = position["case"]
    setup = case["setup"]
    return execute_repeat_exit_fixture(
        setup["e"]["store"], setup["execution"], PIN,
        adapter_module=case["mod"], entry_id=case["key"],
        journal=setup["e"]["path"], sequence=position["sequence"],
        capture_provider=provider or (lambda: dict(
            account=account_snapshot(position),
            market=market_snapshot(position))),
        clock=clock or (lambda: position["now"]), **kwargs)


def close_position(position):
    result = run_exit(position)
    setup = position["case"]["setup"]
    sell = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == result["exit_id"])
    position["transport"].fill(
        sell["order_id"], sell["draft"]["body"]["quantity"])
    return result, sell


def test_second_sell_preserves_first_cycle(position):
    setup = position["case"]["setup"]
    old = deepcopy(setup["old_requests"])
    result = run_exit(position)
    sell = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == result["exit_id"])
    assert sell["draft"]["body"]["transaction_type"] == "SELL"
    assert sell["draft"]["body"]["quantity"] == (
        position["parent"]["draft"]["body"]["quantity"])
    current = {
        r["request_id"]: r for r in setup["execution"].requests()
    }
    for row in old:
        assert current[row["request_id"]] == row
    assert result["production_execution_enabled"] is False


def run_closeout(position, snapshot, **kwargs):
    case = position["case"]
    setup = case["setup"]
    return record_repeat_closeout(
        setup["e"]["store"], setup["execution"], PIN,
        entry_id=case["key"], journal=setup["e"]["path"],
        sequence=position["sequence"],
        capture_provider=lambda: deepcopy(snapshot),
        clock=lambda: position["now"], **kwargs)


def test_second_sell_reaches_flat_and_records_closeout(position):
    close_position(position)
    snapshot = account_snapshot(position)
    assert all(p["quantity"] == 0 for p in snapshot["positions"])
    result = run_closeout(position, snapshot)
    assert result["status"] == "REPEAT_CLOSEOUT_RECORDED"
    record = result["record"]
    assert record["review"]["remaining_quantity"] == 0
    assert record["review"]["all_orders_terminal"] is True
    assert record["review"]["archived_lifecycle_count"] == 1
    assert record["active_references_retired"] is False
    assert record["reservation_release_permission"] is False
    assert record["production_execution_enabled"] is False
    setup = position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        saved = json.loads(db.execute(
            "SELECT data FROM "+CLOSEOUTS+" WHERE id=?",
            (position["case"]["key"],)).fetchone()[0])
        assert saved == record
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (position["case"]["key"],)).fetchone() is not None


def test_closeout_replay_preserves_one_record(position):
    close_position(position)
    snapshot = account_snapshot(position)
    first = run_closeout(position, snapshot)
    replay = run_closeout(position, snapshot)
    assert replay["status"] == "REPEAT_CLOSEOUT_REPLAY"
    assert replay["record"] == first["record"]
    setup = position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM "+CLOSEOUTS
        ).fetchone()[0] == 1


def test_delayed_exit_recovery_never_captures_or_sends(position):
    first = run_exit(position)
    provider = Mock(side_effect=AssertionError("No recovery capture"))
    transport_class = position["case"]["mod"].FixtureTransport
    with patch.object(
        transport_class, "send",
        side_effect=AssertionError("No repeated SELL"),
    ):
        recovered = run_exit(
            position, provider=provider,
            clock=lambda: position["now"]+timedelta(hours=2))
    assert recovered["exit_id"] == first["exit_id"]
    assert recovered["recovery_only"] is True
    assert recovered["new_attempt_created"] is False
    provider.assert_not_called()


@pytest.mark.parametrize("stage", [
    "AFTER_REPEAT_CLOSEOUT_INSERT",
    "BEFORE_REPEAT_CLOSEOUT_COMMIT",
])
def test_closeout_interruption_rolls_back(position, stage):
    close_position(position)
    snapshot = account_snapshot(position)
    def interrupt(current):
        if current == stage:
            raise RuntimeError("synthetic closeout interruption")
    with pytest.raises(RuntimeError, match="synthetic closeout"):
        run_closeout(position, snapshot, checkpoint=interrupt)
    setup = position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name=?", (CLOSEOUTS,)
        ).fetchone()
        if exists:
            assert db.execute(
                "SELECT COUNT(*) FROM "+CLOSEOUTS
            ).fetchone()[0] == 0
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (position["case"]["key"],)).fetchone() is not None
    result = run_closeout(position, snapshot)
    assert result["status"] == "REPEAT_CLOSEOUT_RECORDED"


def test_open_sell_cannot_record_closeout(position):
    run_exit(position)
    snapshot = account_snapshot(position)
    with pytest.raises(
        ValueError, match="REPEAT_POSITION_NOT_TERMINAL_FLAT"
    ):
        run_closeout(position, snapshot)
    setup = position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (position["case"]["key"],)).fetchone() is not None
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name=?", (CLOSEOUTS,)
        ).fetchone()
        if exists:
            assert db.execute(
                "SELECT COUNT(*) FROM "+CLOSEOUTS
            ).fetchone()[0] == 0


def test_tampered_closeout_replay_blocks(position):
    close_position(position)
    snapshot = account_snapshot(position)
    run_closeout(position, snapshot)
    setup = position["case"]["setup"]
    key = position["case"]["key"]
    with setup["e"]["store"].db() as db:
        saved = json.loads(db.execute(
            "SELECT data FROM "+CLOSEOUTS+" WHERE id=?",
            (key,)).fetchone()[0])
        saved["reservation_release_permission"] = True
        db.execute(
            "UPDATE "+CLOSEOUTS+" SET data=? WHERE id=?",
            (json.dumps(saved), key))
    with pytest.raises(
        ValueError, match="REPEAT_CLOSEOUT_SIGNATURE_INVALID"
    ):
        run_closeout(position, snapshot)


def test_lost_sell_response_never_resubmits(position):
    first = run_exit(position, timeout_after=True)
    setup = position["case"]["setup"]
    exit_id = first["exit_id"]
    saved = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == exit_id)
    assert saved["state"] == "UNKNOWN"
    before = deepcopy(position["transport"].orders())
    provider = Mock(side_effect=AssertionError("No recovery capture"))
    transport_class = position["case"]["mod"].FixtureTransport
    with patch.object(
        transport_class, "send",
        side_effect=AssertionError("No repeated uncertain SELL"),
    ):
        recovered = run_exit(
            position, provider=provider,
            clock=lambda: position["now"]+timedelta(hours=2))
    provider.assert_not_called()
    assert recovered["recovery_only"] is True
    assert recovered["new_attempt_created"] is False
    assert recovered["exit_state"] == "UNKNOWN"
    assert position["transport"].orders() == before
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (position["case"]["key"],)).fetchone() is not None
    assert recovered["reservation_release_permission"] is False


def test_exit_claim_interruption_creates_no_sell_attempt(position):
    setup = position["case"]["setup"]
    before = deepcopy(position["transport"].orders())
    def interrupt(stage):
        if stage == "AFTER_REPEAT_EXIT_CLAIM":
            raise RuntimeError("synthetic exit claim interruption")
    with pytest.raises(RuntimeError, match="synthetic exit claim"):
        run_exit(position, checkpoint=interrupt)
    assert position["transport"].orders() == before
    requests = setup["execution"].requests()
    with setup["execution"].tx() as db:
        for row in requests:
            if row["draft"]["body"]["transaction_type"] == "SELL":
                if row["request_id"] not in {
                    r["request_id"] for r in setup["old_requests"]
                }:
                    assert db.execute(
                        "SELECT 1 FROM attempts WHERE request_id=?",
                        (row["request_id"],)).fetchone() is None

