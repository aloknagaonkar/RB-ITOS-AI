"""Read-only lifecycle quantity references. No execution or ownership grant."""
import json

from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import (
    authenticate_preparation_bundles, validate_account_rows,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import (
    _check, sha,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    verify, aware, day,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.reservation_checks import (
    verify_row,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.ownership_review import (
    authenticate_historical_cash,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def review_lifecycle(source, snapshot, pin, *, entry_id, as_of):
    mode = source["mode"]
    need(mode in {"LIVE_CLOSED", "OFFLINE_FIXTURE"},
         "EVIDENCE_MODE_INVALID")
    need(source["scope"] == pin["scope"], "ACCOUNT_SCOPE_MISMATCH")
    if mode == "OFFLINE_FIXTURE":
        need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_SCOPE_REQUIRED")
    else:
        import re
        need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
             "LIVE_PIN_SCOPE_REQUIRED")

    verify(snapshot, pin, as_of=as_of)
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True
         and snapshot.get("source_atomic") is False
         and snapshot.get("position_fill_linkage_verified") is False
         and snapshot.get("live_pnl") is None,
         "COMPLETE_READ_ONLY_CAPTURE_REQUIRED")
    need(source["control"].get("mode") == "PAUSED"
         and source["control"].get("production_execution_enabled") is False,
         "CLOSED_CONTROLLER_REQUIRED")
    stop = source.get("stop_state")
    need(isinstance(stop, list) and len(stop) == 2
         and all(type(x) is int and x >= 0 for x in stop)
         and stop[0] == stop[1], "UNHANDLED_STOP_STATE")
    need(not any(source["counts"][k] for k in (
        "intents", "sim_orders", "sim_fills", "sim_allocation_reservations"
    )), "SIMULATOR_ACTIVITY_NOT_OWNERSHIP")

    orders, positions = validate_account_rows(snapshot)
    historical = _check(
        mode, source["requests"], source["attempts"], source["receipts"])
    need(historical["unbound_request_count"] == 0,
         "UNBOUND_REQUEST_OUTCOME")
    request_rows = source["requests"]
    requests = {key: json.loads(raw) for key, fp, raw in request_rows}
    need(len(requests) == len(request_rows), "DUPLICATE_REQUEST_ID")
    fingerprints = {key: fp for key, fp, raw in request_rows}
    links = {r["request_id"]: r for r in historical["bindings"]}
    need(set(links) == set(requests), "ACKNOWLEDGEMENT_SET_MISMATCH")
    need(set(source["bindings"]) == {entry_id}
         and set(source["plans"]) == {entry_id}
         and set(source["holds"]) == {entry_id}
         and set(source["outbox"]) == {entry_id}
         and set(source["cash_reservations"]) == {entry_id},
         "SINGLE_BOUND_APPLICATION_ENTRY_REQUIRED")
    need(entry_id in links, "ACKNOWLEDGED_ENTRY_REQUIRED")

    binding = source["bindings"][entry_id]
    entry = requests[entry_id]
    parent = links[entry_id]
    need(parent["side"] == "BUY"
         and fingerprints[entry_id] == binding["request_fingerprint"],
         "APPLICATION_ENTRY_BINDING_MISMATCH")
    reservation = source["cash_reservations"][entry_id]
    verify_row(reservation, pin)
    need(reservation["state"] == "RESERVED_DISABLED_REQUEST",
         "UNKNOWN_OUTCOME_HOLD_RETAINED")
    need(reservation["id"] == entry_id
         and reservation["request_fingerprint"] == fingerprints[entry_id]
         and reservation["plan_fingerprint"] == sha(source["plans"][entry_id])
         and reservation["shadow_hold_fingerprint"] == sha(source["holds"][entry_id])
         and reservation["outbox_fingerprint"] == sha(source["outbox"][entry_id]),
         "SIGNED_RESERVATION_BINDING_MISMATCH")
    authenticate_preparation_bundles(source, pin, as_of=as_of)
    bundle = json.loads(source["evidence"][binding["bundle_fingerprint"]])
    need(sha(bundle) == binding["bundle_fingerprint"],
         "PREPARATION_BUNDLE_DIGEST_MISMATCH")
    cap = authenticate_historical_cash(bundle, pin)
    need(cap == binding["cash_cap_cents"] == reservation["cash_cap_cents"],
         "HISTORICAL_HALF_CASH_CAP_MISMATCH")

    need(all(r[2] == "PLACE" for r in source["attempts"])
         and len(source["attempts"]) == len(requests)
         and len(source["receipts"]) == len(requests),
         "CANCEL_OR_ADDITIONAL_ATTEMPT_REQUIRES_REVIEW")
    need(set(orders) == {link["order_id"] for link in links.values()},
         "UNLINKED_OR_MISSING_ACCOUNT_ORDER")

    parent_at = aware(entry["signal_at"])
    for key, link in links.items():
        request = requests[key]
        need(request["state"] not in {
            "UNKNOWN", "IN_FLIGHT", "CANCEL_IN_FLIGHT",
            "CANCEL_OUTCOME_UNKNOWN",
        }, "REQUEST_OUTCOME_UNRESOLVED")
        need(day(aware(request["signal_at"])) == snapshot["session_date"],
             "PRIOR_SESSION_LIFECYCLE_UNSUPPORTED")
        order = orders[link["order_id"]]
        need(all(order[k] == link[k] for k in (
            "instrument", "product", "side", "quantity"
        )), "BOUND_ORDER_CONTRACT_MISMATCH")
        need(aware(order["placed_at"]) >= aware(request["signal_at"]),
             "ORDER_PRECEDES_SIGNAL")
        if key != entry_id:
            need(link["side"] == "SELL"
                 and request["reservation_reference"] == entry["reservation_reference"]
                 and request["direction"] == entry["direction"]
                 and link["instrument"] == parent["instrument"]
                 and link["product"] == parent["product"]
                 and aware(request["signal_at"]) >= parent_at,
                 "EXIT_PARENT_REFERENCE_MISMATCH")

    buy = orders[parent["order_id"]]
    need(buy["status"] in {"FILLED", "CANCELLED"}
         and type(buy["filled"]) is int and buy["filled"] > 0,
         "TERMINAL_FILLED_ENTRY_REQUIRED")
    sellers = [orders[v["order_id"]] for k, v in links.items()
               if k != entry_id]
    # One SELL request only until replacement/cancellation policy is reviewed.
    need(len(sellers) <= 1, "MULTIPLE_EXIT_REQUESTS_UNSUPPORTED")
    need(all(o["quantity"] <= buy["filled"] for o in sellers),
         "EXIT_REQUEST_EXCEEDS_ENTRY_FILLS")
    sold = sum(o["filled"] for o in sellers)
    remaining = buy["filled"] - sold
    need(remaining >= 0, "SELL_FILLS_EXCEED_ENTRY_FILLS")
    key = parent["instrument"], parent["product"]
    need(key in positions, "MISSING_POSITION_ROW_IS_NOT_FLAT")
    need(positions[key] == remaining, "REMAINING_POSITION_MISMATCH")
    need(not any(q != 0 for k, q in positions.items() if k != key),
         "UNLINKED_POSITION_EXPOSURE")

    return dict(
        model="HILEGA_LIFECYCLE_QUANTITY_REFERENCE_REVIEW_V1",
        status="LIFECYCLE_REFERENCE_QUANTITIES_MATCH",
        entry_request_id=entry_id,
        reviewed_buy_fill_quantity=buy["filled"],
        reviewed_sell_fill_quantity=sold,
        reviewed_remaining_quantity=remaining,
        working_sell_present=any(o["status"] in {"OPEN", "PARTIAL"}
                                 for o in sellers),
        scope="SIGNED_CAPTURE_AND_DURABLE_ACK_QUANTITY_REFERENCES_ONLY",
        exit_signal_parent_assessed=False,
        order_modification_history_assessed=False,
        evidence_sources_atomic=False,
        strategy_ownership_verified=False,
        risk_gate_input_ready=False,
        database_modified=False,
        fees_complete=False,
        entry_permission=False,
        exit_submission_permission=False,
        reservation_release_permission=False,
        orders_sent=False,
        production_execution_enabled=False,
        production_ready=False,
    )
