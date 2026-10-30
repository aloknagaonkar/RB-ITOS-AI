from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from cancellation_lifecycle_review import review_with_cancellations
from test_signed_lifecycle_review import (
    synthetic_scope, env, bound_env, module, prepared,
    lifecycle, fill_entry, invoke, values,
)
from test_hilega_application_preparation_v1 import append
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import (
    Store, Adapter, FixtureTransport,
)

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


def cancel_entry(lifecycle, *, lost=False):
    prepared, key, entry, contract, event, at = lifecycle
    _, _, execution = prepared
    # Installed fixture adapter creates durable CANCEL evidence.
    # This test does not implement cancellation submission authorization.
    store = Store(execution.path, PIN["scope"], "OFFLINE_FIXTURE")
    transport = FixtureTransport(store)
    transport.cancel_timeout = lost
    adapter = Adapter(store, transport)
    adapter.cancel(key)
    return adapter


def data_for(lifecycle, *, lost=False, sell=False):
    quantity = lifecycle[2]["draft"]["body"]["quantity"] - 1
    fill_entry(lifecycle, quantity)
    adapter = cancel_entry(lifecycle, lost=lost)
    sequences = []
    if sell:
        e = lifecycle[0][0]
        append(e["path"], [EXIT])
        record = verified_records(e["path"])[-1]
        event = accepted(record)[0]
        lifecycle[4].clear()
        lifecycle[4].update(event)
        invoke(lifecycle)
        sequences = [record["sequence"]]
    return values(lifecycle), sequences, adapter, quantity


def assess(lifecycle, data, sequences):
    source, snapshot, key, at = data
    return review_with_cancellations(
        source, snapshot, PIN, entry_id=key, as_of=at,
        journal=lifecycle[0][0]["path"], exit_sequences=sequences,
    )


def cancel_id(source):
    return next(r[0] for r in source["attempts"] if r[2] == "CANCEL")


def test_durable_cancelled_partial_entry(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle)
    before = deepcopy(data)
    result = assess(lifecycle, data, sequences)
    assert result["cancellation_reference_count"] == 1
    assert result["reviewed_remaining_quantity"] == quantity
    assert result["cancellation_ack_is_flat_proof"] is False
    assert data == before


def test_durable_cancel_then_sell(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle, sell=True)
    result = assess(lifecycle, data, sequences)
    assert result["reviewed_remaining_quantity"] == quantity
    assert result["working_sell_present"] is True
    assert result["exit_signal_parent_assessed"] is True


def test_missing_cancel_receipt_blocks(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle)
    del data[0]["receipts"][cancel_id(data[0])]
    with pytest.raises(ValueError, match="DURABLE_CANCEL_RECEIPT_REQUIRED"):
        assess(lifecycle, data, sequences)


def test_tampered_cancel_receipt_blocks(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle)
    key = cancel_id(data[0])
    receipt = json.loads(data[0]["receipts"][key])
    receipt["wire_fingerprint"] = "changed"
    data[0]["receipts"][key] = json.dumps(receipt)
    with pytest.raises(ValueError, match="CANCEL_RECEIPT_PROVENANCE"):
        assess(lifecycle, data, sequences)


def test_wrong_cancel_ack_order_blocks(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle)
    key = cancel_id(data[0])
    receipt = json.loads(data[0]["receipts"][key])
    receipt["body"]["data"]["order_id"] = "OTHER-ORDER"
    data[0]["receipts"][key] = json.dumps(receipt)
    with pytest.raises(ValueError, match="CANCEL_ACK_ORDER_MISMATCH"):
        assess(lifecycle, data, sequences)


def test_lost_cancel_response_remains_blocked_after_recovery(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle, lost=True)
    with patch.object(
        adapter.transport, "send",
        side_effect=AssertionError("Recovery must not send"),
    ):
        adapter.recover()
    refreshed = values(lifecycle)
    with pytest.raises(ValueError, match="DURABLE_CANCEL_RECEIPT_REQUIRED"):
        assess(lifecycle, refreshed, sequences)


def test_confirmed_cancel_recovery_never_sends(lifecycle):
    data, sequences, adapter, quantity = data_for(lifecycle)
    with patch.object(
        adapter.transport, "send",
        side_effect=AssertionError("Recovery must not send"),
    ):
        adapter.recover()
    result = assess(lifecycle, values(lifecycle), sequences)
    assert result["reviewed_remaining_quantity"] == quantity
    assert result["cancellation_reference_count"] == 1
