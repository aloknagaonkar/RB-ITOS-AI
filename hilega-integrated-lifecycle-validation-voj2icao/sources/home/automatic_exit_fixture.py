"""Confirmed synthetic EXIT -> separate fixture SELL. No live transport."""
from market_lab.hilega_execution_port_v1.adapter import (
    Store, Adapter, FixtureTransport, sha,
)
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_preparation_runtime_v1.evidence import aware, day
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, normalized_tick


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def run_exit_fixture(
    execution_store, pin, *, entry_id, exit_event, contract,
    as_of, limit_price="101", timeout_after=False,
):
    need(pin["scope"].startswith("FIXTURE:"), "SYNTHETIC_ACCOUNT_REQUIRED")
    need(type(execution_store) is Store
         and execution_store.mode == "OFFLINE_FIXTURE"
         and execution_store.scope == pin["scope"],
         "EXACT_FIXTURE_STORE_REQUIRED")
    now, signal = aware(as_of), aware(exit_event["event_at"])
    need(day(now) == day(signal)
         and 0 <= (now - signal).total_seconds() <= 60,
         "FRESH_EXIT_EVENT_REQUIRED")
    need(exit_event["role"] == "EXIT", "CONFIRMED_EXIT_EVENT_REQUIRED")

    transport = FixtureTransport(execution_store)
    adapter = Adapter(execution_store, transport)
    adapter.recover()
    entries = [
        r for r in execution_store.requests()
        if r["request_id"] == entry_id
    ]
    need(len(entries) == 1, "EXACT_ENTRY_REQUEST_REQUIRED")
    entry = entries[0]
    body = entry["draft"]["body"]
    need(body["transaction_type"] == "BUY"
         and entry["direction"] == exit_event["direction"],
         "EXIT_ENTRY_DIRECTION_MISMATCH")
    need(entry["order_id"] is not None, "ACKNOWLEDGED_ENTRY_REQUIRED")
    need(entry["state"] not in {
        "UNKNOWN", "CANCEL_OUTCOME_UNKNOWN", "CANCEL_IN_FLIGHT",
    }, "ENTRY_OUTCOME_UNRESOLVED")

    matched = [
        o for o in transport.orders()
        if o["order_id"] == entry["order_id"]
    ]
    need(len(matched) == 1, "EXACT_ENTRY_ORDER_REQUIRED")
    order = matched[0]
    need(order["side"] == "BUY"
         and order["instrument"] == body["instrument_token"]
         and order["product"] == body["product"]
         and order["quantity"] == body["quantity"],
         "ENTRY_ORDER_IDENTITY_MISMATCH")
    need(
        (order["status"] == "FILLED"
         and order["filled"] == body["quantity"])
        or (order["status"] == "CANCELLED"
            and type(order["filled"]) is int
            and 0 < order["filled"] <= body["quantity"]),
        "FULL_ENTRY_FILL_REQUIRED",
    )

    selected = dict(contract)
    for field in ("lot_size", "minimum_lot", "freeze_quantity"):
        value = selected[field]
        need(not isinstance(value, bool) and int(value) == value,
             "INTEGRAL_CONTRACT_QUANTITY_REQUIRED")
        selected[field] = int(value)
    need(selected["instrument_key"] == body["instrument_token"]
         and selected["lot_size"] == body["quantity"],
         "EXIT_CONTRACT_MISMATCH")

    exit_id = sha(["SYNTHETIC_STRATEGY_EXIT", entry_id, exit_event["id"]])
    # One exit request per entry in this deliberately limited prototype.
    other_exits = [
        r for r in execution_store.requests()
        if r["draft"]["body"]["transaction_type"] == "SELL"
        and r["request_id"] != exit_id
    ]
    need(not other_exits, "OTHER_EXIT_REQUIRES_RECONCILIATION")

    request = draft(
        selected, request_id=exit_id, side="SELL", lots=1,
        as_of=signal.isoformat(), order_type="LIMIT",
        limit_price=limit_price,
        normalized_tick_rupees=normalized_tick(selected, profile=PROFILE),
    )
    # Synthetic partial-fill quantity only. Live lot/quantity policy
    # must be independently validated before production submission.
    request["body"]["quantity"] = order["filled"]
    request["fingerprint"] = sha(request["body"])
    adapter.prepare(
        request, signal_id=exit_event["id"],
        signal_at=signal.isoformat(), direction=exit_event["direction"],
        reservation_reference=entry["reservation_reference"], as_of=as_of,
    )
    transport.timeout_after = timeout_after
    adapter.submit(exit_id)
    saved = next(
        r for r in execution_store.requests() if r["request_id"] == exit_id)
    exits = [
        o for o in transport.orders()
        if saved["order_id"] is not None
        and o["order_id"] == saved["order_id"]
    ]
    remaining = None
    if exits:
        need(exits[0]["side"] == "SELL"
             and exits[0]["quantity"] == order["filled"],
             "EXIT_ORDER_IDENTITY_MISMATCH")
        remaining = order["filled"] - exits[0]["filled"]
        need(remaining >= 0, "EXIT_EXCEEDS_ENTRY_FILL")

    return dict(
        exit_request_id=exit_id,
        exit_state=saved["state"],
        fixture_remaining_quantity=remaining,
        fixture_flat_reference=(remaining == 0),
        fixture_order_count=len(transport.orders()),
        production_runtime_integrated=False,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )