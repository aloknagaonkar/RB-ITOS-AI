"""Read-only account observations; no ownership or release authority."""
from market_lab.hilega_production_account_adapter_v1 import (
    AdapterBlocked, canonical, normalise, verify,
)


def review(capture, pin, *, as_of):
    verify(capture, pin, as_of=as_of)
    if capture.get("profile_verified_before_and_after") is not True:
        raise AdapterBlocked("PROFILE_SWEEP_VERIFICATION_REQUIRED")
    if capture.get("account_position_rows_complete") is not True:
        raise AdapterBlocked("COMPLETE_POSITION_ROWS_REQUIRED")
    if capture.get("source_atomic") is not False:
        raise AdapterBlocked("UNSUPPORTED_ATOMIC_CAPTURE_CLAIM")

    names = ("orders", "trades", "positions")
    if any(
        not isinstance(capture.get(name), list)
        or any(not isinstance(row, dict) for row in capture[name])
        for name in names
    ):
        raise AdapterBlocked("NORMALIZED_CAPTURE_SCHEMA_INVALID")

    # Reuse the account adapter's quantity, identity, timestamp and status
    # validation. Round-trip equality also rejects altered normalized fields
    # and duplicate rows silently collapsed by normalization.
    try:
        orders = [
            dict(
                order_id=o["order_id"], instrument_token=o["instrument"],
                product=o["product"], transaction_type=o["side"],
                quantity=o["quantity"], filled_quantity=o["filled"],
                pending_quantity=o["pending"], status=o["source_status"],
                order_timestamp=o["placed_at"],
            )
            for o in capture["orders"]
        ]
        trades = [
            dict(
                order_id=t["order_id"], trade_id=t["trade_id"],
                instrument_token=t["instrument"], product=t["product"],
                transaction_type=t["side"], quantity=t["quantity"],
                average_price=t["price"], exchange_timestamp=t["filled_at"],
            )
            for t in capture["trades"]
        ]
        positions = [
            dict(
                instrument_token=p["instrument"], product=p["product"],
                quantity=p["quantity"],
            )
            for p in capture["positions"]
        ]
        checked = normalise(
            {"data": orders}, {"data": trades}, {"data": positions},
            observed_at=capture["completed_at"],
        )
        if any(
            canonical(checked[name]) != canonical(capture[name])
            for name in names
        ):
            raise AdapterBlocked("NORMALIZED_CAPTURE_CONTENT_MISMATCH")
    except (KeyError, TypeError):
        raise AdapterBlocked("NORMALIZED_CAPTURE_SCHEMA_INVALID") from None

    reasons = set()
    terminal = {"FILLED", "CANCELLED", "REJECTED"}
    if any(o["status"] not in terminal for o in checked["orders"]):
        reasons.add("NON_TERMINAL_ORDERS")

    issues = checked["diagnostics"]["issues"]
    if "ORDER_TRADE_FILL_TOTAL_MISMATCH" in issues:
        reasons.add("ORDER_TRADE_FILL_TOTAL_MISMATCH")

    net = {}
    for trade in checked["trades"]:
        key = (trade["instrument"], trade["product"])
        sign = 1 if trade["side"] == "BUY" else -1
        net[key] = net.get(key, 0) + sign * trade["quantity"]
    if any(net.values()):
        reasons.add("TRADE_NET_NOT_FLAT")
    if any(p["quantity"] != 0 for p in checked["positions"]):
        reasons.add("POSITION_NOT_FLAT")

    if reasons:
        status = "RECONCILIATION_REQUIRED"
    elif checked["orders"] or checked["trades"]:
        status = "TERMINAL_FLAT_ACCOUNT_OBSERVATION"
    else:
        status = "EMPTY_ACCOUNT_OBSERVATION"

    return dict(
        model="HILEGA_BROKER_TERMINAL_REVIEW_V1",
        status=status,
        reasons=sorted(reasons),
        assessed_at=as_of,
        snapshot_id=capture.get("snapshot_id"),
        order_count=len(checked["orders"]),
        trade_count=len(checked["trades"]),
        position_row_count=len(checked["positions"]),
        source_atomic=False,
        strategy_ownership_verified=False,
        real_funds_reservation_verified=False,
        reservation_release_permission=False,
        entry_permission=False,
        production_execution_enabled=False,
        production_ready=False,
        orders_sent=False,
    )
