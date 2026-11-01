from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from production_execution_coordinator_candidate import ExecutionCoordinatorCandidate
from test_production_entry_authorization_candidate import (
    synthetic_scope, env, bound_env, live_case, context,
)
from test_production_authorizer_hook import candidate
from test_production_cancel_candidate import execution as cancel_execution
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


@pytest.fixture
def flow(context, live_case, candidate):
    e, key, at, source, empty, wire, authority, grant = context
    store = candidate.Store(
        e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    adapter = candidate.Adapter(store, candidate.HttpTransport(token))
    state = {"snapshot": deepcopy(empty), "clock": at}

    def prepare_exit(current, event):
        contract = deepcopy(current["plans"][key]["evidence"]["contract"])
        for name in ("lot_size", "minimum_lot", "freeze_quantity"):
            contract[name] = int(contract[name])
        exit_id = sha(["COORDINATOR_TEST_EXIT", key, event["id"]])
        request = draft(
            contract, request_id=exit_id, side="SELL", lots=1,
            as_of=event["event_at"], order_type="LIMIT",
            limit_price="101", normalized_tick_rupees="0.05",
        )
        adapter.prepare(
            request, signal_id=event["id"], signal_at=event["event_at"],
            direction=event["direction"],
            reservation_reference=source["cash_reservations"][key]["id"],
            as_of=state["clock"].isoformat(),
        )

    coordinator = ExecutionCoordinatorCandidate(
        e["store"], adapter, PIN, authority,
        adapter_module=candidate, journal=e["path"],
        capture_provider=lambda: deepcopy(state["snapshot"]),
        clock=lambda: state["clock"], exit_preparer=prepare_exit,
    )
    records = verified_records(e["path"])
    entry_sequence = next(
        r["sequence"] for r in records
        if any(ev["id"] == source["plans"][key].get(
            "signal_id", source["requests"] and
            __import__("json").loads(source["requests"][0][2])["signal_id"])
            for ev in accepted(r))
    )
    return e, candidate, adapter, token, state, coordinator, entry_sequence, live_case


def send_receipt(flow, aid, wire):
    mod = flow[1]
    side = wire["body"]["transaction_type"]
    oid = (
        "SYNTHETIC-LIVE-BRANCH-ORDER" if side == "BUY"
        else "SYNTHETIC-COORDINATOR-SELL"
    )
    return dict(
        attempt_id=aid, wire_fingerprint=mod.sha(wire),
        origin="LOCAL_HTTP_TRANSPORT", http_status=200,
        body=dict(status="success", data=dict(order_ids=[oid])),
    )


def test_coordinator_preserves_real_gate(flow):
    e, mod, adapter, token, state, coordinator, sequence, original = flow
    provider = Mock(side_effect=AssertionError("No capture behind gate"))
    coordinator.capture = provider
    result = coordinator.dispatch(sequence)
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    provider.assert_not_called()
    token.assert_not_called()


def test_complete_buy_fill_sell_and_delayed_replay(flow):
    e, mod, adapter, token, state, coordinator, sequence, original = flow
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ) as send:
        coordinator.dispatch(sequence)
        state["snapshot"] = deepcopy(original[2])
        append(e["path"], [EXIT])
        exit_sequence = verified_records(e["path"])[-1]["sequence"]
        result = coordinator.dispatch(exit_sequence)
    assert result["status"] == "CANDIDATE_EXIT_ATTEMPT_RECORDED"
    assert send.call_count == 2
    state["clock"] += timedelta(hours=2)
    coordinator.capture = Mock(side_effect=AssertionError("No replay capture"))
    with patch.object(
        adapter.transport, "send", side_effect=AssertionError("No repeated SELL"),
    ):
        recovered = coordinator.dispatch(exit_sequence)
    assert recovered["status"] == "EXISTING_EXIT_RECOVERED_NO_SUBMISSION"
    token.assert_not_called()


def test_missing_exit_preparer_stops_without_sell(flow):
    e, mod, adapter, token, state, coordinator, sequence, original = flow
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ):
        coordinator.dispatch(sequence)
    state["snapshot"] = deepcopy(original[2])
    append(e["path"], [EXIT])
    coordinator.exit_preparer = None
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send", side_effect=AssertionError("No guessed exit"),
    ):
        result = coordinator.dispatch(verified_records(e["path"])[-1]["sequence"])
    assert result["status"] == "EXIT_PREPARATION_REQUIRED"


def test_invalid_sequence_cannot_submit(flow):
    with pytest.raises(ValueError, match="JOURNAL_SEQUENCE_INVALID"):
        flow[5].dispatch(0)


def test_cancel_routes_through_authorized_transaction(cancel_execution):
    e, key, snapshot, at, sequence, adapter, mod, authority, token = cancel_execution
    coordinator = ExecutionCoordinatorCandidate(
        e["store"], adapter, PIN, authority,
        adapter_module=mod, journal=e["path"],
        capture_provider=lambda: deepcopy(snapshot), clock=lambda: at,
    )
    def receipt(aid, wire):
        return dict(
            attempt_id=aid, wire_fingerprint=mod.sha(wire),
            http_status=200, origin="LOCAL_HTTP_TRANSPORT",
            body=dict(status="success", data=dict(
                order_id=wire["query"]["order_id"])),
        )
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send", side_effect=receipt,
    ) as send:
        result = coordinator.cancel_entry_remainder(sequence)
    assert result["status"] == "CANDIDATE_CANCEL_ATTEMPT_RECORDED"
    send.assert_called_once()
    token.assert_not_called()
