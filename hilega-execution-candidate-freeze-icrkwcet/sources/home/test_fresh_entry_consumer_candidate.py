from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

import pytest

from production_journal_consumer_candidate import ProductionJournalConsumerCandidate
from priced_execution_coordinator_candidate import PricedExecutionCoordinatorCandidate
from test_automatic_entry_fixture import synthetic_scope, env, bound_env
from test_production_authorizer_hook import candidate
from test_worker_handoff import worker
from test_hilega_application_preparation_v1 import append, BULL
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_account_adapter_v1 import account_scope, day
from market_lab.hilega_production_simulator_bridge_v1 import verified_records
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    MODEL, LIVE, sign,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from cancellation_lifecycle_review import review_with_cancellations

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


def snapshot(f):
    at = f.e["clock"][0]
    orders, trades, positions = [], [], {}
    for request in f.adapter.store.requests():
        if not request.get("order_id"):
            continue
        body = request["draft"]["body"]
        side = body["transaction_type"]
        quantity = body["quantity"]
        filled = quantity if (
            f.buy_filled if side == "BUY" else f.sell_filled
        ) else 0
        order = dict(
            order_id=request["order_id"],
            instrument=body["instrument_token"], product=body["product"],
            side=side, quantity=quantity, filled=filled,
            pending=quantity-filled, status="FILLED" if filled else "OPEN",
            placed_at=request["signal_at"],
        )
        orders.append(order)
        if filled:
            trades.append(dict(
                order_id=order["order_id"],
                trade_id="synthetic-" + order["order_id"],
                instrument=order["instrument"], product=order["product"],
                side=side, quantity=filled, price=str(body["price"]),
                filled_at=at.isoformat(),
            ))
        key = order["instrument"], order["product"]
        positions[key] = positions.get(key, 0) + (
            filled if side == "BUY" else -filled)
    value = dict(
        model=MODEL, evidence_mode=LIVE, account_scope=PIN["scope"],
        snapshot_id=uuid.uuid4().hex, session_date=day(at),
        generated_at=at.isoformat(), completed_at=at.isoformat(),
        status="READ_ONLY_CAPTURED", account_identity_verified=True,
        profile_verified_before_and_after=True,
        account_position_rows_complete=True,
        source_atomic=False, position_fill_linkage_verified=False,
        live_pnl=None, orders_sent=False, entry_permission=False,
        production_execution_enabled=False, diagnostics={},
        orders=orders, trades=trades,
        positions=[dict(instrument=k[0], product=k[1], quantity=q)
                   for k, q in positions.items()],
    )
    value["signature"] = sign(value, PIN)
    return value


@pytest.fixture
def fresh(synthetic_scope, monkeypatch, request, candidate):
    monkeypatch.setitem(
        PIN, "scope", account_scope(PIN["key"], "SYNTHETIC_PROVIDER_TEST"))
    e = request.getfixturevalue("bound_env")
    store = candidate.Store(
        e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    adapter = candidate.Adapter(store, candidate.HttpTransport(token))
    f = SimpleNamespace(
        e=e, mod=candidate, adapter=adapter, token=token,
        buy_filled=False, sell_filled=False,
    )
    f.capture = Mock(side_effect=lambda: snapshot(f))

    def market():
        source = read_sources(e["store"].path, store.path, PIN["scope"])
        key = next(iter(source["bindings"]))
        return json.loads(source["evidence"][
            source["bindings"][key]["bundle_fingerprint"]])

    f.market = Mock(side_effect=market)
    authority = dict(
        authority_id="SYNTHETIC-FRESH-ENTRY-AUTHORITY",
        account_scope=PIN["scope"], key="77"*32)
    f.coordinator = PricedExecutionCoordinatorCandidate(
        e["store"], adapter, PIN, authority,
        adapter_module=candidate, journal=e["path"],
        capture_provider=f.capture, market_capture_provider=f.market,
        clock=lambda: e["clock"][0],
    )
    f.consumer = ProductionJournalConsumerCandidate(f.coordinator)
    baseline = f.consumer.poll()
    assert baseline["status"] == "BASELINED_WAIT_NEXT_FRESH_SIGNAL"
    assert not store.requests()
    f.baseline = baseline["cursor_sequence"]
    return f


def prepare(worker, f):
    append(f.e["path"], [BULL])
    worker.preparation_tick(f.e["source"], f.e["path"])
    assert len(f.adapter.store.requests()) == 1
    assert f.e["store"].control()["mode"] == "PAUSED"


def receipt(f, aid, wire):
    side = wire["body"]["transaction_type"]
    return dict(
        attempt_id=aid, wire_fingerprint=f.mod.sha(wire),
        origin="LOCAL_HTTP_TRANSPORT", http_status=200,
        body=dict(status="success", data=dict(
            order_ids=["SYNTHETIC-FRESH-" + side])),
    )


def attempt_count(f):
    with f.adapter.store.tx() as db:
        return db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]


def test_fresh_entry_through_worker_and_durable_consumer(worker, fresh):
    f = fresh
    prepare(worker, f)
    with patch.object(f.adapter.transport, "check", return_value=None), patch.object(
        f.adapter.transport, "send",
        side_effect=lambda aid, wire: receipt(f, aid, wire),
    ) as send:
        result = f.consumer.poll()
    assert result["processed_record_count"] == 1
    assert result["cursor_sequence"] == f.baseline + 1
    assert attempt_count(f) == 1
    send.assert_called_once()
    f.market.assert_not_called()
    f.token.assert_not_called()


def test_closed_gate_holds_new_entry_cursor(worker, fresh):
    f = fresh
    prepare(worker, f)
    result = f.consumer.poll()
    assert result["status"] == "CURSOR_HELD_FOR_RECONCILIATION"
    assert result["cursor_sequence"] == f.baseline
    assert attempt_count(f) == 0
    f.capture.assert_not_called()
    f.token.assert_not_called()


def test_lost_entry_cursor_recovers_without_another_buy(worker, fresh):
    f = fresh
    prepare(worker, f)

    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_FRESH_ENTRY_CURSOR_LOST")

    with patch.object(f.adapter.transport, "check", return_value=None), patch.object(
        f.adapter.transport, "send",
        side_effect=lambda aid, wire: receipt(f, aid, wire),
    ):
        with pytest.raises(RuntimeError, match="FRESH_ENTRY_CURSOR_LOST"):
            f.consumer.poll(checkpoint=interrupt)
    capture_count = f.capture.call_count
    f.e["clock"][0] += timedelta(hours=2)
    reopened = ProductionJournalConsumerCandidate(f.coordinator)
    with patch.object(
        f.adapter.transport, "send",
        side_effect=AssertionError("No repeated BUY"),
    ):
        result = reopened.poll()
    assert result["processed_record_count"] == 1
    assert f.capture.call_count == capture_count
    assert attempt_count(f) == 1


def test_unknown_buy_holds_cursor_without_resubmission(worker, fresh):
    f = fresh
    prepare(worker, f)
    with patch.object(f.adapter.transport, "check", return_value=None), patch.object(
        f.adapter.transport, "send", side_effect=TimeoutError("Synthetic response lost"),
    ):
        result = f.consumer.poll()
    assert result["status"] == "CURSOR_HELD_FOR_RECONCILIATION"
    capture_count = f.capture.call_count
    f.e["clock"][0] += timedelta(hours=2)
    with patch.object(
        f.adapter.transport, "send",
        side_effect=AssertionError("No unknown-outcome retry"),
    ):
        result = f.consumer.poll()
    assert result["cursor_sequence"] == f.baseline
    assert result["status"] == "CURSOR_HELD_FOR_RECONCILIATION"
    assert f.capture.call_count == capture_count
    assert attempt_count(f) == 1


def test_concurrent_consumers_submit_fresh_buy_once(worker, fresh):
    f = fresh
    prepare(worker, f)
    second = ProductionJournalConsumerCandidate(f.coordinator)
    with patch.object(f.adapter.transport, "check", return_value=None), patch.object(
        f.adapter.transport, "send",
        side_effect=lambda aid, wire: receipt(f, aid, wire),
    ) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda c: c.poll(), [f.consumer, second]))
    assert sum(r["processed_record_count"] for r in results) == 1
    assert attempt_count(f) == 1
    send.assert_called_once()


def test_fresh_entry_fill_priced_exit_and_signed_flat(worker, fresh):
    f = fresh
    prepare(worker, f)
    with patch.object(f.adapter.transport, "check", return_value=None), patch.object(
        f.adapter.transport, "send",
        side_effect=lambda aid, wire: receipt(f, aid, wire),
    ) as send:
        assert f.consumer.poll()["processed_record_count"] == 1
        f.buy_filled = True
        append(f.e["path"], [EXIT])
        worker.preparation_tick(f.e["source"], f.e["path"])
        exit_sequence = verified_records(f.e["path"])[-1]["sequence"]
        assert f.consumer.poll()["processed_record_count"] == 1
    assert send.call_count == 2
    assert attempt_count(f) == 2
    f.sell_filled = True
    source = read_sources(
        f.e["store"].path, f.adapter.store.path, PIN["scope"])
    entry_id = next(iter(source["bindings"]))
    report = review_with_cancellations(
        source, snapshot(f), PIN, entry_id=entry_id,
        as_of=f.e["clock"][0].isoformat(),
        journal=f.e["path"], exit_sequences=[exit_sequence],
    )
    assert report["reviewed_remaining_quantity"] == 0
    assert report["exit_submission_permission"] is False
    assert f.consumer.poll()["processed_record_count"] == 0
    f.token.assert_not_called()
