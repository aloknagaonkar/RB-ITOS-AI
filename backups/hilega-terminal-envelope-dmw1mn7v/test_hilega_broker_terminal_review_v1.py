from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from market_lab.domain import IST
from market_lab import hilega_production_account_adapter_v1 as account
from market_lab.hilega_execution_port_v1.adapter import (
    Adapter, Blocked, GateClosed, HttpTransport, Store,
)
from market_lab.hilega_execution_port_v1.terminal import review

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=IST)
PIN = {"key": "11" * 32, "scope": "UPSTOX:" + "22" * 32}


def signed(value):
    value.pop("signature", None)
    value["signature"] = account.sign(value, PIN)
    return value


def capture():
    orders, trades = [], []
    for i, side in enumerate(("BUY", "SELL")):
        at = NOW - timedelta(minutes=20 - i * 5)
        orders.append(dict(
            order_id=str(i), instrument_token="NSE_FO|TEST",
            product="I", transaction_type=side, quantity=65,
            filled_quantity=65, pending_quantity=0, status="complete",
            order_timestamp=at.isoformat(),
        ))
        trades.append(dict(
            order_id=str(i), trade_id="t" + str(i),
            instrument_token="NSE_FO|TEST", product="I",
            transaction_type=side, quantity=65, average_price=100,
            exchange_timestamp=(at + timedelta(seconds=1)).isoformat(),
        ))
    normalized = account.normalise(
        {"data": orders}, {"data": trades},
        {"data": [dict(
            instrument_token="NSE_FO|TEST", product="I", quantity=0,
        )]},
        observed_at=NOW.isoformat(),
    )
    return signed(dict(
        model=account.MODEL, evidence_mode=account.LIVE,
        generated_at=(NOW - timedelta(seconds=1)).isoformat(),
        completed_at=NOW.isoformat(), session_date="2026-10-28",
        account_scope=PIN["scope"], snapshot_id="synthetic-test",
        status="READ_ONLY_CAPTURED", account_identity_verified=True,
        profile_verified_before_and_after=True, source_atomic=False,
        orders_sent=False, entry_permission=False,
        production_execution_enabled=False, **normalized,
    ))


def test_terminal_flat_observation_has_no_execution_authority():
    value = capture()
    before = deepcopy(value)
    result = review(value, PIN, as_of=NOW.isoformat())
    assert result["status"] == "TERMINAL_FLAT_ACCOUNT_OBSERVATION"
    assert result["reasons"] == []
    for name in (
        "strategy_ownership_verified", "real_funds_reservation_verified",
        "reservation_release_permission", "entry_permission",
        "production_execution_enabled", "production_ready", "orders_sent",
    ):
        assert result[name] is False
    assert value == before


@pytest.mark.parametrize("case,reason", [
    ("position", "POSITION_NOT_FLAT"),
    ("missing_trade", "ORDER_TRADE_FILL_TOTAL_MISMATCH"),
    ("partial_cancel", "TRADE_NET_NOT_FLAT"),
    ("open", "NON_TERMINAL_ORDERS"),
])
def test_unresolved_account_retains_review(case, reason):
    value = capture()
    if case == "position":
        value["positions"][0]["quantity"] = 65
    elif case == "missing_trade":
        value["trades"].pop()
    elif case == "partial_cancel":
        value["orders"][0].update(
            status="CANCELLED", source_status="cancelled", filled=64,
        )
        value["trades"][0]["quantity"] = 64
    else:
        value["orders"][0].update(
            status="PARTIAL", source_status="open", filled=64, pending=1,
        )
        value["trades"][0]["quantity"] = 64
    result = review(signed(value), PIN, as_of=NOW.isoformat())
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert reason in result["reasons"]
    assert result["reservation_release_permission"] is False


@pytest.mark.parametrize("case", [
    "duplicate_order", "duplicate_trade", "duplicate_position",
    "status", "boolean_quantity", "incomplete_positions", "atomic_claim",
])
def test_invalid_signed_content_is_rejected(case):
    value = capture()
    if case.startswith("duplicate"):
        name = {
            "duplicate_order": "orders", "duplicate_trade": "trades",
            "duplicate_position": "positions",
        }[case]
        value[name].append(deepcopy(value[name][0]))
    elif case == "status":
        value["orders"][0]["status"] = "CANCELLED"
    elif case == "boolean_quantity":
        value["orders"][0]["quantity"] = True
    elif case == "incomplete_positions":
        value["account_position_rows_complete"] = False
    else:
        value["source_atomic"] = True
    with pytest.raises(account.AdapterBlocked):
        review(signed(value), PIN, as_of=NOW.isoformat())


def test_signature_freshness_and_scope_checks_remain_required():
    value = capture()
    value["positions"][0]["quantity"] = 1
    with pytest.raises(account.AdapterBlocked, match="SIGNATURE"):
        review(value, PIN, as_of=NOW.isoformat())
    with pytest.raises(account.AdapterBlocked, match="STALE_OR_FUTURE"):
        review(
            capture(), PIN,
            as_of=(NOW + timedelta(seconds=31)).isoformat(),
        )
    wrong_pin = {**PIN, "scope": "UPSTOX:" + "33" * 32}
    with pytest.raises(account.AdapterBlocked, match="SCOPE"):
        review(capture(), wrong_pin, as_of=NOW.isoformat())


def dump(store):
    with store.tx() as db:
        return list(db.iterdump())


def test_adapter_adds_observation_without_writes_or_adopting_orders(tmp_path):
    store = Store(tmp_path / "adapter.sqlite", PIN["scope"], "LIVE_CLOSED")
    transport = HttpTransport(
        lambda: pytest.fail("Token must not be accessed")
    )
    adapter = Adapter(store, transport)
    before = dump(store)
    result = adapter.reconcile_read_only(
        capture(), PIN, as_of=NOW.isoformat(),
    )
    assert result["status"] == "READ_ONLY_OWNERSHIP_REVIEW"
    assert result["matched_known_order_count"] == 0
    assert result["ownership_verified"] is False
    assert result["terminal_account_review"]["status"] == (
        "TERMINAL_FLAT_ACCOUNT_OBSERVATION"
    )
    with pytest.raises(GateClosed):
        transport.check()
    with pytest.raises(Blocked):
        adapter.release_reservation()
    assert dump(store) == before


def test_unacknowledged_request_is_not_an_empty_baseline(tmp_path):
    store = Store(tmp_path / "adapter.sqlite", PIN["scope"], "LIVE_CLOSED")
    with store.tx() as db:
        db.execute(
            "INSERT INTO requests VALUES(?,?,?)",
            ("pending", "synthetic", json.dumps({
                "request_id": "pending", "state": "UNKNOWN",
            })),
        )
    value = capture()
    value.update(orders=[], trades=[], positions=[])
    adapter = Adapter(store, HttpTransport(
        lambda: pytest.fail("Token must not be accessed")
    ))
    before = dump(store)
    result = adapter.reconcile_read_only(
        signed(value), PIN, as_of=NOW.isoformat(),
    )
    assert result["status"] == "READ_ONLY_OWNERSHIP_REVIEW"
    assert result["ownership_verified"] is False
    assert dump(store) == before
