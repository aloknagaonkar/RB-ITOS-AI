from copy import deepcopy
import json
from unittest.mock import Mock, patch

import pytest

from priced_execution_coordinator_candidate import PricedExecutionCoordinatorCandidate
from test_production_execution_coordinator_candidate import (
    synthetic_scope, env, bound_env, live_case, context, candidate,
    flow, send_receipt,
)
from test_production_cancel_candidate import execution as cancel_execution
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_simulator_bridge_v1 import verified_records
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


def market_bundle(e, store):
    source = read_sources(e["store"].path, store.path, PIN["scope"])
    key = next(iter(source["bindings"]))
    return json.loads(source["evidence"][source["bindings"][key]["bundle_fingerprint"]])


def test_buy_fill_then_bid_priced_sell(flow):
    e, mod, adapter, token, state, old, sequence, original = flow
    market = Mock(return_value=market_bundle(e, adapter.store))
    coordinator = PricedExecutionCoordinatorCandidate(
        e["store"], adapter, PIN, old.authority,
        adapter_module=mod, journal=e["path"],
        capture_provider=lambda: deepcopy(state["snapshot"]),
        market_capture_provider=market, clock=lambda: state["clock"],
    )
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ) as send:
        coordinator.dispatch(sequence)
        state["snapshot"] = deepcopy(original[2])
        append(e["path"], [EXIT])
        result = coordinator.dispatch(verified_records(e["path"])[-1]["sequence"])
    assert result["status"] == "CANDIDATE_EXIT_ATTEMPT_RECORDED"
    assert send.call_count == 2
    assert market.call_count == 2
    token.assert_not_called()


def cancellation_flow(case, *, mode):
    e, key, original, at, sequence, adapter, mod, authority, token = case
    state = {"snapshot": deepcopy(original)}
    if mode == "zero":
        order = state["snapshot"]["orders"][0]
        order.update(status="OPEN", filled=0, pending=order["quantity"])
        state["snapshot"].update(trades=[], positions=[])
        state["snapshot"].pop("signature", None)
        state["snapshot"]["signature"] = sign(state["snapshot"], PIN)
    market = Mock(return_value=market_bundle(e, adapter.store))
    coordinator = PricedExecutionCoordinatorCandidate(
        e["store"], adapter, PIN, authority,
        adapter_module=mod, journal=e["path"],
        capture_provider=lambda: deepcopy(state["snapshot"]),
        market_capture_provider=market, clock=lambda: at,
    )

    def send(aid, wire):
        if wire["method"] == "DELETE":
            if mode == "unknown":
                raise TimeoutError("Synthetic cancel response lost")
            snapshot = state["snapshot"]
            order = snapshot["orders"][0]
            if mode == "full":
                order.update(status="FILLED", filled=order["quantity"], pending=0)
                snapshot["trades"][0]["quantity"] = order["quantity"]
                snapshot["positions"][0]["quantity"] = order["quantity"]
            elif mode != "working":
                order.update(status="CANCELLED", pending=0)
            snapshot.pop("signature", None)
            snapshot["signature"] = sign(snapshot, PIN)
            body = dict(status="success", data=dict(
                order_id=wire["query"]["order_id"]))
        else:
            body = dict(status="success", data=dict(
                order_ids=["SYNTHETIC-SEQUENCED-SELL"]))
        return dict(
            attempt_id=aid, wire_fingerprint=mod.sha(wire),
            origin="LOCAL_HTTP_TRANSPORT", http_status=200, body=body)
    return coordinator, market, send


@pytest.mark.parametrize("mode,expected", [
    ("partial", "PRODUCTION_PARTIAL_QUANTITY_POLICY_PENDING"),
    ("unknown", "CANCEL_RECONCILIATION_REQUIRED"),
    ("working", "ENTRY_TERMINAL_RECONCILIATION_REQUIRED"),
    ("zero", "ENTRY_CANCELLED_WITHOUT_FILL"),
])
def test_cancel_requires_reconciled_quantity(cancel_execution, mode, expected):
    coordinator, market, response = cancellation_flow(cancel_execution, mode=mode)
    adapter = cancel_execution[5]
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send", side_effect=response,
    ) as send:
        result = coordinator.dispatch(cancel_execution[4])
    assert result["status"] == expected
    assert send.call_count == 1
    assert send.call_args.args[1]["method"] == "DELETE"
    market.assert_not_called()


def test_fill_during_cancel_reconciles_before_priced_sell(cancel_execution):
    coordinator, market, response = cancellation_flow(cancel_execution, mode="full")
    adapter = cancel_execution[5]
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send", side_effect=response,
    ) as send:
        result = coordinator.dispatch(cancel_execution[4])
    assert result["status"] == "CANDIDATE_EXIT_ATTEMPT_RECORDED"
    assert [c.args[1]["method"] for c in send.call_args_list] == ["DELETE", "POST"]
    assert market.call_count == 2
