"""Working-entry cancellation constraints. No live clearance or flat proof."""
from datetime import timedelta
import hmac
import json
import uuid

from production_entry_authorization_candidate import validate_authority
from fixture_execution_authorization import signature
from market_lab.hilega_execution_port_v1.adapter import cancel_draft
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.ownership_checks.ownership_review import reconcile_entry
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check, sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware

TABLE = "production_candidate_cancel_claims"
MODEL = "HILEGA_PRODUCTION_CANCEL_AUTHORIZATION_CANDIDATE_V1"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def cancel_context(
    source, snapshot, pin, *, request_id, wire,
    journal, exit_sequence, as_of,
):
    need(source["mode"] == "LIVE_CLOSED"
         and source["scope"] == pin["scope"], "LIVE_CLOSED_CONTEXT_REQUIRED")
    # Reuse authenticated preparation, reservation, receipt and capture checks.
    # A working entry is expected to fail only these entry-completion checks.
    reviewed = reconcile_entry(source, snapshot, pin, as_of=as_of)
    orders, positions = validate_account_rows(snapshot)
    historical = _check(
        source["mode"], source["requests"], source["attempts"], source["receipts"])
    need(len(source["requests"]) == 1
         and source["requests"][0][0] == request_id
         and len(historical["bindings"]) == 1,
         "SINGLE_ACKNOWLEDGED_ENTRY_REQUIRED")
    request = json.loads(source["requests"][0][2])
    link = historical["bindings"][0]
    need(link["request_id"] == request_id and link["side"] == "BUY"
         and set(orders) == {link["order_id"]},
         "EXACT_ACKNOWLEDGED_BUY_ORDER_REQUIRED")
    order = orders[link["order_id"]]
    need(order["status"] in {"OPEN", "PARTIAL"}
         and order["filled"] < order["quantity"]
         and order["pending"] == order["quantity"] - order["filled"],
         "SIGNED_WORKING_ENTRY_REMAINDER_REQUIRED")
    allowed = {
        "FULLY_FILLED_ENTRY_REQUIRED",
        "NONTERMINAL_BOUND_ORDER_REQUIRES_RECONCILIATION",
    }
    if order["filled"] == 0:
        allowed.update({
            "NO_ACTUAL_ENTRY_FILLS", "MISSING_POSITION_ROW_IS_NOT_FLAT",
        })
    need(reviewed["authenticated_reservation_count"] == 1
         and set(reviewed["reasons"]) <= allowed,
         "CANCEL_ENTRY_REFERENCE_GAPS")
    draft = cancel_draft(link["order_id"])
    need(wire == dict(
        method="DELETE", host=draft["documented_host"],
        path=draft["documented_path"], query=draft["query"],
    ), "EXACT_CANCEL_WIRE_REQUIRED")

    records = verified_records(journal)
    need(type(exit_sequence) is int and 1 <= exit_sequence <= len(records),
         "EXIT_SEQUENCE_INVALID")
    record = records[exit_sequence-1]
    events = accepted(record)
    need(len(events) == 1 and events[0]["role"] == "EXIT",
         "SINGLE_CONFIRMED_EXIT_REQUIRED")
    event = events[0]
    need(event["direction"] == request["direction"]
         and event.get("entry_reference_at") is not None
         and aware(event["entry_reference_at"]) == aware(request["signal_at"]),
         "CANCEL_EXIT_PARENT_MISMATCH")
    need(0 <= (aware(as_of)-aware(event["event_at"])).total_seconds() <= 60,
         "FRESH_CANCEL_EXIT_SIGNAL_REQUIRED")
    return sha(dict(
        source=source, snapshot=snapshot,
        exit_sequence=exit_sequence, exit_record_hash=record["record_hash"],
    ))


def issue_candidate(
    authority, pin, source, snapshot, *,
    request_id, wire, journal, exit_sequence, at,
):
    validate_authority(authority, pin)
    context_fp = cancel_context(
        source, snapshot, pin, request_id=request_id, wire=wire,
        journal=journal, exit_sequence=exit_sequence, as_of=at)
    now = aware(at)
    grant = dict(
        model=MODEL, authorization_id=uuid.uuid4().hex,
        authority_id=authority["authority_id"], account_scope=pin["scope"],
        request_id=request_id, operation="CANCEL",
        wire_fingerprint=sha(wire), context_fingerprint=context_fp,
        issued_at=now.isoformat(),
        expires_at=(now+timedelta(seconds=10)).isoformat(),
        live_clearance_granted=False, production_execution_enabled=False,
    )
    grant["signature"] = signature(grant, authority)
    return grant


def claim_candidate(
    db, grant, authority, pin, source, snapshot, *,
    request_id, wire, journal, exit_sequence, attempt_id, at,
):
    need(db.in_transaction, "CALLER_TRANSACTION_REQUIRED")
    validate_authority(authority, pin)
    value = dict(grant)
    signed = value.pop("signature", None)
    need(isinstance(signed, str)
         and hmac.compare_digest(signature(value, authority), signed),
         "AUTHORIZATION_SIGNATURE_INVALID")
    need(value.get("model") == MODEL
         and value.get("authority_id") == authority["authority_id"]
         and value.get("account_scope") == pin["scope"]
         and value.get("request_id") == request_id
         and value.get("operation") == "CANCEL"
         and value.get("wire_fingerprint") == sha(wire)
         and value.get("production_execution_enabled") is False
         and value.get("live_clearance_granted") is False,
         "CANCEL_AUTHORIZATION_BINDING_MISMATCH")
    start, end, now = map(aware, (
        value["issued_at"], value["expires_at"], at))
    need(0 < (end-start).total_seconds() <= 10 and start <= now < end,
         "AUTHORIZATION_EXPIRED_OR_FUTURE")
    current = cancel_context(
        source, snapshot, pin, request_id=request_id, wire=wire,
        journal=journal, exit_sequence=exit_sequence, as_of=at)
    need(current == value["context_fingerprint"], "CANCEL_CONTEXT_CHANGED")
    need(isinstance(attempt_id, str) and bool(attempt_id), "ATTEMPT_ID_REQUIRED")
    # Separate operation ledger: a prior BUY claim must not consume CANCEL.
    db.execute(
        "CREATE TABLE IF NOT EXISTS " + TABLE + "("
        "id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,"
        "attempt_id TEXT UNIQUE NOT NULL)")
    need(db.execute(
        "SELECT 1 FROM " + TABLE + " WHERE id=? OR request_id=?",
        (value["authorization_id"], request_id),
    ).fetchone() is None, "AUTHORIZATION_ALREADY_CONSUMED")
    db.execute("INSERT INTO " + TABLE + " VALUES(?,?,?)",
               (value["authorization_id"], request_id, attempt_id))
    return dict(
        authorization_claimed=True, context_revalidated=True,
        account_scope=pin["scope"], request_id=request_id,
        attempt_id=attempt_id, wire_fingerprint=sha(wire),
        production_execution_enabled=False,
    )
