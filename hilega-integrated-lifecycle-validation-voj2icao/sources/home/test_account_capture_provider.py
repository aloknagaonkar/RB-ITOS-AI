from copy import deepcopy
import sqlite3

import pytest

from account_capture_provider import make_capture_provider
from worker_lifecycle_handoff import capture_and_record
from application_lifecycle_state import read_current
from test_live_closed_lifecycle_candidate import (
    synthetic_scope, env, bound_env, live_case,
)
from test_worker_handoff import worker
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_account_adapter_v1 import Client


def responses(case):
    snapshot = case[2]
    profile = dict(status="success", data=dict(
        broker="UPSTOX", is_active=True, user_id="SYNTHETIC_PROVIDER_TEST"))
    orders = []
    for row in snapshot["orders"]:
        orders.append(dict(
            order_id=row["order_id"],
            instrument_token=row["instrument"], product=row["product"],
            transaction_type=row["side"],
            quantity=row["quantity"], filled_quantity=row["filled"],
            pending_quantity=row["pending"],
            status={"FILLED": "complete", "CANCELLED": "cancelled",
                    "OPEN": "open", "PARTIAL": "open"}[row["status"]],
            order_timestamp=row["placed_at"],
        ))
    trades = [dict(
        order_id=row["order_id"], trade_id=row["trade_id"],
        instrument_token=row["instrument"], product=row["product"],
        transaction_type=row["side"], quantity=row["quantity"],
        average_price=row["price"], exchange_timestamp=row["filled_at"],
    ) for row in snapshot["trades"]]
    positions = [dict(
        instrument_token=row["instrument"],
        product=row["product"], quantity=row["quantity"],
    ) for row in snapshot["positions"]]
    return dict(
        profile=profile,
        orders=dict(status="success", data=orders),
        trades=dict(status="success", data=trades),
        positions=dict(status="success", data=positions),
    )


def provider(case, monkeypatch, *, transform=None):
    raw = responses(case)
    calls = []

    def get(self, endpoint):
        calls.append(endpoint)
        if transform:
            return transform(endpoint, deepcopy(raw[endpoint]))
        return deepcopy(raw[endpoint])

    monkeypatch.setattr(Client, "get", get)
    # No constructor, credentials or network initialization in these tests.
    client = object.__new__(Client)
    return make_capture_provider(
        client, PIN, clock=lambda: case[3]), calls


def run(case, capture_provider):
    e, key, snapshot, at = case
    return capture_and_record(
        e["store"].path, e["adapter_store"].path, PIN,
        journal=e["path"], exit_sequences=[],
        capture_provider=capture_provider,
        clock=lambda: at, mode="LIVE_CLOSED",
    )


def test_installed_capture_runs_through_worker(worker, live_case, monkeypatch):
    capture_provider, calls = provider(live_case, monkeypatch)
    e = live_case[0]
    before = e["adapter_store"].path.read_bytes()
    result = worker.preparation_tick(
        e["source"], e["path"],
        test_handoff=lambda: run(live_case, capture_provider),
    )
    assert calls == ["profile", "orders", "trades", "positions", "profile"]
    handoff = result["execution_handoff"]
    assert handoff["status"] == "APPLICATION_LIFECYCLE_REVIEW_COMMITTED"
    assert handoff["current"]["report"]["reviewed_remaining_quantity"] > 0
    assert handoff["production_execution_enabled"] is False
    assert e["adapter_store"].path.read_bytes() == before


def test_wrong_profile_blocks_before_order_reads(live_case, monkeypatch):
    def change(endpoint, value):
        if endpoint == "profile":
            value["data"]["user_id"] = "OTHER_SYNTHETIC_ACCOUNT"
        return value
    capture_provider, calls = provider(live_case, monkeypatch, transform=change)
    with pytest.raises(ValueError):
        run(live_case, capture_provider)
    assert calls == ["profile"]
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None


def test_profile_change_after_sweep_blocks(live_case, monkeypatch):
    seen = []

    def change(endpoint, value):
        if endpoint == "profile":
            seen.append(1)
            if len(seen) == 2:
                value["data"]["user_id"] = "OTHER_SYNTHETIC_ACCOUNT"
        return value
    capture_provider, calls = provider(live_case, monkeypatch, transform=change)
    with pytest.raises(ValueError):
        run(live_case, capture_provider)
    assert calls == ["profile", "orders", "trades", "positions", "profile"]
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None


def test_get_failure_does_not_reuse_previous_capture(live_case, monkeypatch):
    def fail(endpoint, value):
        if endpoint == "trades":
            raise RuntimeError("SYNTHETIC_GET_FAILURE")
        return value
    capture_provider, calls = provider(live_case, monkeypatch, transform=fail)
    with pytest.raises(ValueError):
        run(live_case, capture_provider)
    assert calls == ["profile", "orders", "trades"]
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None


def test_arbitrary_client_rejected():
    with pytest.raises(ValueError, match="FIXED_GET_ONLY_CLIENT_REQUIRED"):
        make_capture_provider(object(), PIN, clock=lambda: None)
