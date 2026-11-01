from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from unittest.mock import Mock, patch

import pytest

from fixture_third_exit_candidate import (
    execute_third_exit_fixture, record_third_closeout, CLOSEOUTS,
)
from test_fixture_third_execution_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed,
    third, third_ready, run as run_buy,
)
from hilega_application_preparation_fixtures import PIN
from test_hilega_application_preparation_v1 import append
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


def resign(value):
    value.pop("signature", None)
    value["signature"] = sign(value, PIN)
    return value


@pytest.fixture
def third_position(third_ready):
    run_buy(third_ready)
    setup = third_ready["setup"]
    transport = third_ready["mod"].FixtureTransport(setup["execution"])
    parent = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == third_ready["key"])
    transport.fill(
        parent["order_id"], parent["draft"]["body"]["quantity"])
    now = third_ready["now"] + timedelta(minutes=5)
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
        case=third_ready, parent=parent, transport=transport,
        now=now, sequence=len(rows))


def account_snapshot(third_position):
    case = third_position["case"]
    setup = case["setup"]
    now = third_position["now"]
    snapshot = deepcopy(case["captures"]["account"])
    old_ids = {o["order_id"] for o in snapshot["orders"]}
    requests = {
        r["order_id"]: r for r in setup["execution"].requests()
        if r.get("order_id")
    }
    for order in third_position["transport"].orders():
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


def market_snapshot(third_position):
    value = deepcopy(third_position["case"]["captures"]["market"])
    now = third_position["now"]
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


def run_exit(third_position, *, provider=None, clock=None, **kwargs):
    case = third_position["case"]
    setup = case["setup"]
    return execute_third_exit_fixture(
        setup["e"]["store"], setup["execution"], PIN,
        adapter_module=case["mod"], entry_id=case["key"],
        journal=setup["e"]["path"], sequence=third_position["sequence"],
        capture_provider=provider or (lambda: dict(
            account=account_snapshot(third_position),
            market=market_snapshot(third_position))),
        clock=clock or (lambda: third_position["now"]), **kwargs)


def close_position(third_position):
    result = run_exit(third_position)
    setup = third_position["case"]["setup"]
    sell = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == result["exit_id"])
    third_position["transport"].fill(
        sell["order_id"], sell["draft"]["body"]["quantity"])
    return result, sell


def test_third_sell_preserves_first_cycle(third_position):
    setup = third_position["case"]["setup"]
    old = deepcopy(third_position["case"]["old_requests"])
    result = run_exit(third_position)
    sell = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == result["exit_id"])
    assert sell["draft"]["body"]["transaction_type"] == "SELL"
    assert sell["draft"]["body"]["quantity"] == (
        third_position["parent"]["draft"]["body"]["quantity"])
    current = {
        r["request_id"]: r for r in setup["execution"].requests()
    }
    for row in old:
        assert current[row["request_id"]] == row
    assert result["production_execution_enabled"] is False


def run_closeout(third_position, snapshot, **kwargs):
    case = third_position["case"]
    setup = case["setup"]
    return record_third_closeout(
        setup["e"]["store"], setup["execution"], PIN,
        entry_id=case["key"], journal=setup["e"]["path"],
        sequence=third_position["sequence"],
        capture_provider=lambda: deepcopy(snapshot),
        clock=lambda: third_position["now"], **kwargs)


def test_third_sell_reaches_flat_and_records_closeout(third_position):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    assert all(p["quantity"] == 0 for p in snapshot["positions"])
    result = run_closeout(third_position, snapshot)
    assert result["status"] == "THIRD_CLOSEOUT_RECORDED"
    record = result["record"]
    assert record["review"]["remaining_quantity"] == 0
    assert record["review"]["all_orders_terminal"] is True
    assert record["review"]["archived_lifecycle_count"] == 2
    assert record["active_references_retired"] is False
    assert record["reservation_release_permission"] is False
    assert record["production_execution_enabled"] is False
    setup = third_position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        saved = json.loads(db.execute(
            "SELECT data FROM "+CLOSEOUTS+" WHERE id=?",
            (third_position["case"]["key"],)).fetchone()[0])
        assert saved == record
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (third_position["case"]["key"],)).fetchone() is not None


def test_closeout_replay_preserves_one_record(third_position):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    first = run_closeout(third_position, snapshot)
    replay = run_closeout(third_position, snapshot)
    assert replay["status"] == "THIRD_CLOSEOUT_REPLAY"
    assert replay["record"] == first["record"]
    setup = third_position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM "+CLOSEOUTS
        ).fetchone()[0] == 1


def test_delayed_exit_recovery_never_captures_or_sends(third_position):
    first = run_exit(third_position)
    provider = Mock(side_effect=AssertionError("No recovery capture"))
    transport_class = third_position["case"]["mod"].FixtureTransport
    with patch.object(
        transport_class, "send",
        side_effect=AssertionError("No repeated SELL"),
    ):
        recovered = run_exit(
            third_position, provider=provider,
            clock=lambda: third_position["now"]+timedelta(hours=2))
    assert recovered["exit_id"] == first["exit_id"]
    assert recovered["recovery_only"] is True
    assert recovered["new_attempt_created"] is False
    provider.assert_not_called()


@pytest.mark.parametrize("stage", [
    "AFTER_THIRD_CLOSEOUT_INSERT",
    "BEFORE_THIRD_CLOSEOUT_COMMIT",
])
def test_closeout_interruption_rolls_back(third_position, stage):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    def interrupt(current):
        if current == stage:
            raise RuntimeError("synthetic closeout interruption")
    with pytest.raises(RuntimeError, match="synthetic closeout"):
        run_closeout(third_position, snapshot, checkpoint=interrupt)
    setup = third_position["case"]["setup"]
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
            (third_position["case"]["key"],)).fetchone() is not None
    result = run_closeout(third_position, snapshot)
    assert result["status"] == "THIRD_CLOSEOUT_RECORDED"


def test_open_sell_cannot_record_closeout(third_position):
    run_exit(third_position)
    snapshot = account_snapshot(third_position)
    with pytest.raises(
        ValueError, match="REPEAT_POSITION_NOT_TERMINAL_FLAT"
    ):
        run_closeout(third_position, snapshot)
    setup = third_position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (third_position["case"]["key"],)).fetchone() is not None
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name=?", (CLOSEOUTS,)
        ).fetchone()
        if exists:
            assert db.execute(
                "SELECT COUNT(*) FROM "+CLOSEOUTS
            ).fetchone()[0] == 0


def test_tampered_closeout_replay_blocks(third_position):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    run_closeout(third_position, snapshot)
    setup = third_position["case"]["setup"]
    key = third_position["case"]["key"]
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
        run_closeout(third_position, snapshot)


def test_lost_sell_response_never_resubmits(third_position):
    first = run_exit(third_position, timeout_after=True)
    setup = third_position["case"]["setup"]
    exit_id = first["exit_id"]
    saved = next(
        r for r in setup["execution"].requests()
        if r["request_id"] == exit_id)
    assert saved["state"] == "UNKNOWN"
    before = deepcopy(third_position["transport"].orders())
    provider = Mock(side_effect=AssertionError("No recovery capture"))
    transport_class = third_position["case"]["mod"].FixtureTransport
    with patch.object(
        transport_class, "send",
        side_effect=AssertionError("No repeated uncertain SELL"),
    ):
        recovered = run_exit(
            third_position, provider=provider,
            clock=lambda: third_position["now"]+timedelta(hours=2))
    provider.assert_not_called()
    assert recovered["recovery_only"] is True
    assert recovered["new_attempt_created"] is False
    assert recovered["exit_state"] == "UNKNOWN"
    assert third_position["transport"].orders() == before
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT 1 FROM preparation_plans WHERE id=?",
            (third_position["case"]["key"],)).fetchone() is not None
    assert recovered["reservation_release_permission"] is False


def test_exit_claim_interruption_creates_no_sell_attempt(third_position):
    setup = third_position["case"]["setup"]
    before = deepcopy(third_position["transport"].orders())
    def interrupt(stage):
        if stage == "AFTER_THIRD_EXIT_CLAIM":
            raise RuntimeError("synthetic exit claim interruption")
    with pytest.raises(RuntimeError, match="synthetic exit claim"):
        run_exit(third_position, checkpoint=interrupt)
    assert third_position["transport"].orders() == before
    requests = setup["execution"].requests()
    with setup["execution"].tx() as db:
        for row in requests:
            if row["draft"]["body"]["transaction_type"] == "SELL":
                if row["request_id"] not in {
                    r["request_id"] for r in third_position["case"]["old_requests"]
                }:
                    assert db.execute(
                        "SELECT 1 FROM attempts WHERE request_id=?",
                        (row["request_id"],)).fetchone() is None


def test_third_exit_stale_owned_quote_blocks(third_position):
    account = account_snapshot(third_position)
    market = market_snapshot(third_position)
    old = third_position['now']-timedelta(seconds=31)
    market.update(started_at=old.isoformat(), completed_at=old.isoformat())
    resign(market)
    before = deepcopy(third_position['transport'].orders())
    with pytest.raises(ValueError):
        run_exit(third_position, provider=lambda: dict(account=account, market=market))
    assert third_position['transport'].orders() == before


def test_third_closeout_missing_zero_position_blocks(third_position):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    snapshot['positions'] = []
    resign(snapshot)
    with pytest.raises(ValueError, match='MISSING_POSITION_ROW_IS_NOT_FLAT'):
        run_closeout(third_position, snapshot)


def test_third_exit_exact_claim_expiry_creates_no_attempt(third_position):
    now = third_position['now']
    times = iter([now, now+timedelta(seconds=10)])
    before = deepcopy(third_position['transport'].orders())
    with pytest.raises(ValueError, match='EXPIRED'):
        run_exit(third_position, clock=lambda: next(times))
    assert third_position['transport'].orders() == before


def test_third_closeout_expiry_before_commit_rolls_back(third_position):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    setup = third_position['case']['setup']
    times = iter([third_position['now'], third_position['now']+timedelta(seconds=31)])
    with pytest.raises(ValueError):
        record_third_closeout(
            setup['e']['store'], setup['execution'], PIN,
            entry_id=third_position['case']['key'], journal=setup['e']['path'],
            sequence=third_position['sequence'],
            capture_provider=lambda: deepcopy(snapshot), clock=lambda: next(times))
    with setup['e']['store'].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (CLOSEOUTS,)).fetchone()
        if exists:
            assert db.execute('SELECT COUNT(*) FROM '+CLOSEOUTS).fetchone()[0] == 0
        assert db.execute('SELECT 1 FROM preparation_plans WHERE id=?',
                          (third_position['case']['key'],)).fetchone() is not None


def test_concurrent_third_exit_callers_submit_once(third_position):
    captures = dict(account=account_snapshot(third_position),
                    market=market_snapshot(third_position))
    provider = Mock(side_effect=lambda: deepcopy(captures))
    before = len(third_position['transport'].orders())
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(run_exit, third_position, provider=provider)
                   for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results[0]['exit_id'] == results[1]['exit_id']
    assert sorted(r['recovery_only'] for r in results) == [False, True]
    assert provider.call_count == 1
    assert len(third_position['transport'].orders()) == before+1
    with third_position['case']['setup']['execution'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts WHERE request_id=?',
                          (results[0]['exit_id'],)).fetchone()[0] == 1


def test_partial_third_entry_retains_hold_without_sell(third_position):
    setup = third_position['case']['setup']
    oid = third_position['parent']['order_id']
    # Synthetic-only rewind to exercise the unsupported partial-entry branch.
    with setup['execution'].tx() as db:
        row = json.loads(db.execute(
            'SELECT data FROM fixture_orders WHERE id=?', (oid,)).fetchone()[0])
        row.update(filled=row['quantity']-1, status='PARTIAL')
        db.execute('UPDATE fixture_orders SET data=? WHERE id=?',
                   (json.dumps(row), oid))
    before = deepcopy(third_position['transport'].orders())
    with pytest.raises(ValueError, match='FULL_CURRENT_ENTRY_FILL_REQUIRED'):
        run_exit(third_position)
    assert third_position['transport'].orders() == before
    with setup['e']['store'].db() as db:
        assert db.execute('SELECT 1 FROM preparation_cash_reservations WHERE id=?',
                          (third_position['case']['key'],)).fetchone() is not None


@pytest.mark.parametrize('operation', ['exit', 'closeout'])
def test_third_live_scope_rejected_before_files(operation):
    def unavailable():
        raise AssertionError('Capture or clock accessed for live scope')
    kwargs = dict(entry_id='blocked', journal='/must-not-open.jsonl', sequence=1,
                  capture_provider=unavailable, clock=unavailable)
    if operation == 'exit':
        with pytest.raises(ValueError, match='FIXTURE_THIRD_EXIT_ONLY'):
            execute_third_exit_fixture(
                None, None, dict(PIN, scope='UPSTOX:'+'a'*64),
                adapter_module=None, **kwargs)
    else:
        with pytest.raises(ValueError, match='FIXTURE_THIRD_CLOSEOUT_ONLY'):
            record_third_closeout(None, None, dict(PIN, scope='UPSTOX:'+'a'*64), **kwargs)

