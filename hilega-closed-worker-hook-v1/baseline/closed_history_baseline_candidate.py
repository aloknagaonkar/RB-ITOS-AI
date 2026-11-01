"""Fixture closed-history attribution. Never rewrites signed account evidence."""
from decimal import Decimal
import hmac
import json

from cancellation_lifecycle_review import review_with_cancellations
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    sign, verify, aware,
)

TABLE = "fixture_closed_lifecycle_history"
MODEL = "HILEGA_FIXTURE_CLOSED_HISTORY_V1"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def authenticate(row, pin):
    payload = dict(row)
    signed = payload.pop("signature", None)
    need(isinstance(signed, str)
         and hmac.compare_digest(sign(payload, pin), signed),
         "CLOSED_HISTORY_SIGNATURE_INVALID")
    need(row["model"] == MODEL and row["account_scope"] == pin["scope"]
         and row["entry_permission"] is False
         and row["reservation_release_permission"] is False
         and row["production_execution_enabled"] is False,
         "CLOSED_HISTORY_SCOPE_OR_AUTHORITY_INVALID")
    need(sha(row["source"]) == row["source_fingerprint"]
         and sha(row["snapshot"]) == row["snapshot_fingerprint"],
         "CLOSED_HISTORY_EVIDENCE_CHANGED")
    verify(row["snapshot"], pin, as_of=row["assessed_at"])
    orders, positions = validate_account_rows(row["snapshot"])
    need(row["review"]["reviewed_remaining_quantity"] == 0
         and all(q == 0 for q in positions.values())
         and all(o["status"] in {"FILLED", "CANCELLED", "REJECTED"}
                 and o["pending"] == 0 for o in orders.values()),
         "CLOSED_HISTORY_NOT_TERMINAL_FLAT")
    return row


def seal_history(
    db, source, snapshot, pin, *, entry_id, journal, exit_sequences, as_of,
):
    need(pin["scope"].startswith("FIXTURE:")
         and source["mode"] == "OFFLINE_FIXTURE", "FIXTURE_HISTORY_ONLY")
    need(db.in_transaction, "CALLER_TRANSACTION_REQUIRED")
    reviewed = review_with_cancellations(
        source, snapshot, pin, entry_id=entry_id, as_of=as_of,
        journal=journal, exit_sequences=exit_sequences,
    )
    need(reviewed["reviewed_remaining_quantity"] == 0,
         "FLAT_LIFECYCLE_REQUIRED")
    orders, positions = validate_account_rows(snapshot)
    need(all(o["status"] in {"FILLED", "CANCELLED", "REJECTED"}
             and o["pending"] == 0 for o in orders.values()),
         "TERMINAL_ORDERS_REQUIRED")
    fingerprint = sha(dict(source=source, snapshot=snapshot))
    db.execute(
        "CREATE TABLE IF NOT EXISTS " + TABLE +
        "(id TEXT PRIMARY KEY,data TEXT NOT NULL)")
    old = db.execute(
        "SELECT data FROM " + TABLE + " WHERE id=?", (entry_id,)
    ).fetchone()
    if old:
        row = authenticate(json.loads(old[0]), pin)
        need(row["input_fingerprint"] == fingerprint,
             "IMMUTABLE_CLOSED_HISTORY_CONFLICT")
        return dict(record=row, idempotent_replay=True)
    row = dict(
        model=MODEL, account_scope=pin["scope"], entry_id=entry_id,
        assessed_at=as_of, input_fingerprint=fingerprint,
        source_fingerprint=sha(source), snapshot_fingerprint=sha(snapshot),
        source=source, snapshot=snapshot, review=reviewed,
        entry_permission=False, reservation_release_permission=False,
        production_execution_enabled=False,
    )
    row["signature"] = sign(row, pin)
    authenticate(row, pin)
    db.execute(
        "INSERT INTO " + TABLE + " VALUES(?,?)",
        (entry_id, json.dumps(row, sort_keys=True)))
    return dict(record=row, idempotent_replay=False)


def order_identity(row):
    return (
        row["order_id"], row["instrument"], row["product"], row["side"],
        row["quantity"], row["filled"], row["pending"], row["status"],
        aware(row["placed_at"]),
    )


def trade_identity(row):
    return (
        row["order_id"], row["trade_id"], row["instrument"],
        row["product"], row["side"], row["quantity"],
        Decimal(str(row["price"])), aware(row["filled_at"]),
    )


def review_reentry_history(snapshot, archives, pin, *, as_of):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_HISTORY_ONLY")
    verify(snapshot, pin, as_of=as_of)
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True,
         "COMPLETE_PINNED_CAPTURE_REQUIRED")
    current_orders, current_positions = validate_account_rows(snapshot)
    expected_orders, expected_trades, expected_position_keys = {}, {}, set()
    seen_entries = set()
    for archived in archives:
        row = authenticate(archived, pin)
        need(row["entry_id"] not in seen_entries, "DUPLICATE_CLOSED_LIFECYCLE")
        seen_entries.add(row["entry_id"])
        need(aware(row["snapshot"]["completed_at"])
             <= aware(snapshot["generated_at"]),
             "CURRENT_CAPTURE_PRECEDES_CLOSED_HISTORY")
        old_orders, old_positions = validate_account_rows(row["snapshot"])
        expected_position_keys.update(old_positions)
        for oid, order in old_orders.items():
            need(oid not in expected_orders, "ORDER_OWNED_BY_MULTIPLE_ARCHIVES")
            expected_orders[oid] = order_identity(order)
        for trade in row["snapshot"]["trades"]:
            key = trade["order_id"], trade["trade_id"]
            need(key not in expected_trades, "TRADE_OWNED_BY_MULTIPLE_ARCHIVES")
            expected_trades[key] = trade_identity(trade)

    need(set(current_orders) == set(expected_orders),
         "UNATTRIBUTED_OR_MISSING_ACCOUNT_ORDER")
    need(all(order_identity(order) == expected_orders[oid]
             for oid, order in current_orders.items()),
         "CLOSED_ORDER_EVIDENCE_CHANGED")
    current_trades = {
        (t["order_id"], t["trade_id"]): trade_identity(t)
        for t in snapshot["trades"]
    }
    need(current_trades == expected_trades, "CLOSED_TRADE_EVIDENCE_CHANGED")
    need(expected_position_keys <= set(current_positions),
         "MISSING_POSITION_ROW_IS_NOT_FLAT")
    need(not any(current_positions.values()), "ACCOUNT_NOT_FLAT")
    return dict(
        status="CLOSED_HISTORY_ATTRIBUTED_READ_ONLY",
        matched_closed_lifecycle_count=len(archives),
        matched_order_count=len(current_orders),
        matched_trade_count=len(current_trades),
        original_capture_fingerprint=sha(snapshot),
        signed_snapshot_modified=False,
        current_cash_assessed=False,
        entry_permission=False,
        reservation_release_permission=False,
        production_execution_enabled=False,
    )

