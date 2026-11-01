from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import json

import pytest

import authorized_exit_fixture as exits
from test_authorized_prepared_entry import (
    synthetic_scope, env, bound_env, module, prepared, run, counts,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)


@pytest.fixture
def lifecycle(prepared):
    e, mod, store = prepared
    run(prepared)
    source = read_sources(
        e["store"].path, e["adapter_store"].path, PIN["scope"])
    key = source["requests"][0][0]
    entry = next(r for r in store.requests() if r["request_id"] == key)
    contract = deepcopy(source["plans"][key]["evidence"]["contract"])
    at = e["clock"][0] + timedelta(seconds=1)
    event = dict(
        id="authorized-synthetic-exit", role="EXIT",
        direction=entry["direction"], event_at=at.isoformat(),
    )
    return prepared, key, entry, contract, event, at


def invoke(lifecycle, *, clock=None, timeout_after=False):
    prepared, key, entry, contract, event, at = lifecycle
    e, mod, store = prepared
    return exits.execute_authorized_exit(
        store, PIN, adapter_module=mod, entry_id=key,
        exit_event=event, contract=contract,
        clock=clock or (lambda: at),
        timeout_after=timeout_after,
    )


def fill_entry(lifecycle, quantity=None, cancel=False):
    prepared, key, entry, contract, event, at = lifecycle
    _, mod, store = prepared
    transport = mod.FixtureTransport(store)
    quantity = (
        entry["draft"]["body"]["quantity"]
        if quantity is None else quantity
    )
    if quantity:
        transport.fill(entry["order_id"], quantity)
    if cancel:
        # Explicit fake-broker setup, not an authorized cancel implementation.
        adapter = mod.Adapter(store, transport)
        receipt = transport.send(
            "synthetic-external-cancel",
            adapter._wire(entry, "CANCEL"),
        )
        assert receipt["http_status"] == 200
    return quantity


def sell_orders(lifecycle):
    prepared = lifecycle[0]
    _, mod, store = prepared
    return [
        r for r in mod.FixtureTransport(store).orders()
        if r["side"] == "SELL"
    ]


def test_full_fill_authorizes_one_sell_and_reaches_flat(lifecycle):
    quantity = fill_entry(lifecycle)
    result = invoke(lifecycle)
    assert result["new_attempt_created"] is True
    assert counts(lifecycle[0]) == (2, 2)
    orders = sell_orders(lifecycle)
    assert len(orders) == 1
    assert orders[0]["quantity"] == quantity
    _, mod, store = lifecycle[0]
    mod.FixtureTransport(store).fill(orders[0]["order_id"], quantity)
    assert sell_orders(lifecycle)[0]["filled"] == quantity


def test_cancelled_partial_sells_only_filled_quantity(lifecycle):
    requested = lifecycle[2]["draft"]["body"]["quantity"]
    quantity = requested - 1
    assert quantity > 0
    fill_entry(lifecycle, quantity, cancel=True)
    invoke(lifecycle)
    assert sell_orders(lifecycle)[0]["quantity"] == quantity
    assert counts(lifecycle[0]) == (2, 2)


def test_open_partial_entry_cannot_sell(lifecycle):
    requested = lifecycle[2]["draft"]["body"]["quantity"]
    fill_entry(lifecycle, requested - 1)
    with pytest.raises(ValueError, match="TERMINAL_ENTRY_FILL_REQUIRED"):
        invoke(lifecycle)
    assert counts(lifecycle[0]) == (1, 1)
    assert sell_orders(lifecycle) == []


def test_partial_sell_preserves_remaining_quantity(lifecycle):
    requested = lifecycle[2]["draft"]["body"]["quantity"]
    quantity = requested - 1
    fill_entry(lifecycle, quantity, cancel=True)
    invoke(lifecycle)
    _, mod, store = lifecycle[0]
    order = sell_orders(lifecycle)[0]
    mod.FixtureTransport(store).fill(order["order_id"], 1)
    saved = sell_orders(lifecycle)[0]
    assert saved["status"] == "PARTIAL"
    assert quantity - saved["filled"] == quantity - 1


def test_delayed_partial_exit_recovery_never_sends(lifecycle):
    requested = lifecycle[2]["draft"]["body"]["quantity"]
    fill_entry(lifecycle, requested - 1, cancel=True)
    invoke(lifecycle)
    _, mod, store = lifecycle[0]
    with patch.object(
        mod.FixtureTransport, "send",
        side_effect=AssertionError("Recovery must not send"),
    ):
        result = invoke(
            lifecycle,
            clock=lambda: lifecycle[5] + timedelta(hours=2),
        )
    assert result["recovery_only"] is True
    assert result["new_attempt_created"] is False
    assert counts(lifecycle[0]) == (2, 2)
    assert len(sell_orders(lifecycle)) == 1


def test_lost_sell_response_stays_unknown_without_resubmit(lifecycle):
    fill_entry(lifecycle)
    invoke(lifecycle, timeout_after=True)
    _, mod, store = lifecycle[0]
    with patch.object(
        mod.FixtureTransport, "send",
        side_effect=AssertionError("Unknown outcome must not resubmit"),
    ):
        result = invoke(
            lifecycle,
            clock=lambda: lifecycle[5] + timedelta(minutes=5),
        )
    assert result["recovery_only"] is True
    sellers = [
        r for r in store.requests()
        if r["draft"]["body"]["transaction_type"] == "SELL"
    ]
    assert len(sellers) == 1
    assert sellers[0]["state"] == "UNKNOWN"
    assert counts(lifecycle[0]) == (2, 2)
    assert len(sell_orders(lifecycle)) == 1


def test_expiry_before_sell_attempt_creates_no_claim_or_attempt(lifecycle):
    fill_entry(lifecycle)
    at = lifecycle[5]
    times = iter([at, at + timedelta(seconds=10)])
    with pytest.raises(ValueError, match="AUTHORIZATION_EXPIRED_OR_FUTURE"):
        invoke(lifecycle, clock=lambda: next(times))
    assert counts(lifecycle[0]) == (1, 1)
    assert sell_orders(lifecycle) == []


def test_failure_after_sell_claim_rolls_back_claim_and_attempt(lifecycle):
    fill_entry(lifecycle)
    original = exits.claim_exit

    def fail_after_claim(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC_SELL_CLAIM_INTERRUPTION")

    with patch.object(exits, "claim_exit", side_effect=fail_after_claim):
        with pytest.raises(RuntimeError, match="SELL_CLAIM_INTERRUPTION"):
            invoke(lifecycle)
    assert counts(lifecycle[0]) == (1, 1)
    assert sell_orders(lifecycle) == []


def test_concurrent_exit_callers_submit_once(lifecycle):
    fill_entry(lifecycle)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, lifecycle) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    assert counts(lifecycle[0]) == (2, 2)
    assert len(sell_orders(lifecycle)) == 1


def test_unknown_cancel_blocks_exit(lifecycle):
    requested = lifecycle[2]["draft"]["body"]["quantity"]
    fill_entry(lifecycle, requested - 1, cancel=True)
    _, _, store = lifecycle[0]
    with store.tx() as db:
        row = json.loads(db.execute(
            "SELECT data FROM requests WHERE id=?", (lifecycle[1],)
        ).fetchone()[0])
        row["state"] = "CANCEL_OUTCOME_UNKNOWN"
        db.execute(
            "UPDATE requests SET data=? WHERE id=?",
            (json.dumps(row), lifecycle[1]),
        )
    with pytest.raises(ValueError, match="ENTRY_OUTCOME_UNRESOLVED"):
        invoke(lifecycle)
    assert counts(lifecycle[0]) == (1, 1)
    assert sell_orders(lifecycle) == []
