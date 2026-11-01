"""Ownership-bound SELL constraints. No live execution clearance."""
from datetime import timedelta
import hmac
import json
import uuid

from production_entry_authorization_candidate import validate_authority, TABLE
from fixture_execution_authorization import signature
from cancellation_lifecycle_review import review_with_cancellations
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, validate_price

MODEL = "HILEGA_PRODUCTION_EXIT_AUTHORIZATION_CANDIDATE_V1"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def exit_context(
    source, snapshot, pin, *, entry_id, request_id,
    wire, journal, exit_sequence, as_of,
):
    need(source["mode"] == "LIVE_CLOSED"
         and source["scope"] == pin["scope"], "LIVE_CLOSED_CONTEXT_REQUIRED")
    rows = {key: (fp, json.loads(raw))
            for key, fp, raw in source["requests"]}
    need(len(rows) == len(source["requests"])
         and set(rows) == {entry_id, request_id}
         and entry_id != request_id,
         "SINGLE_ENTRY_AND_PREPARED_EXIT_REQUIRED")
    fp, request = rows[request_id]
    stable = {k: request[k] for k in (
        "request_id", "draft", "signal_id", "signal_at",
        "direction", "reservation_reference",
    )}
    need(sha(stable) == fp, "EXIT_REQUEST_FINGERPRINT_CHANGED")
    draft = request["draft"]
    body = draft["body"]
    need(request["state"] == "PREPARED" and request.get("order_id") is None,
         "UNSUBMITTED_EXIT_REQUIRED")
    need(draft["request_id"] == request_id
         and sha(body) == draft["fingerprint"]
         and all(draft.get(k) is False for k in (
             "submission_enabled", "entry_permission", "orders_sent",
         )), "DISABLED_EXIT_DRAFT_REQUIRED")
    need(not any(r[1] == request_id for r in source["attempts"]),
         "EXISTING_EXIT_REQUIRES_RECOVERY")
    need(wire == dict(
        method="POST", host="api-hft.upstox.com",
        path="/v3/order/place", body=body,
    ) and body["transaction_type"] == "SELL"
      and body["order_type"] == "LIMIT",
      "EXACT_SELL_LIMIT_WIRE_REQUIRED")

    records = verified_records(journal)
    need(type(exit_sequence) is int and 1 <= exit_sequence <= len(records),
         "EXIT_SEQUENCE_INVALID")
    record = records[exit_sequence-1]
    events = accepted(record)
    need(len(events) == 1 and events[0]["role"] == "EXIT",
         "SINGLE_CONFIRMED_EXIT_REQUIRED")
    event = events[0]
    parent = rows[entry_id][1]
    need(event["id"] == request["signal_id"]
         and event["direction"] == request["direction"] == parent["direction"]
         and aware(event["event_at"]) == aware(request["signal_at"])
         and event.get("entry_reference_at") is not None
         and aware(event["entry_reference_at"]) == aware(parent["signal_at"])
         and request["reservation_reference"] == parent["reservation_reference"],
         "EXIT_SIGNAL_PARENT_MISMATCH")
    now = aware(as_of)
    need(0 <= (now-aware(event["event_at"])).total_seconds() <= 60
         and 0 <= (now-aware(draft["created_at"])).total_seconds() <= 10,
         "EXIT_SIGNAL_OR_DRAFT_STALE")

    # The target exit has no attempt/order yet. Review the acknowledged
    # parent independently, without pretending this request has an ACK.
    projected = dict(
        source, requests=[r for r in source["requests"] if r[0] != request_id],
    )
    reviewed = review_with_cancellations(
        projected, snapshot, pin, entry_id=entry_id, as_of=as_of,
        journal=journal, exit_sequences=[],
    )
    contract = source["plans"][entry_id]["evidence"]["contract"]
    quantity = body["quantity"]
    lot = contract["lot_size"]
    need(not isinstance(lot, bool) and int(lot) == lot,
         "INTEGRAL_CONTRACT_LOT_REQUIRED")
    need(type(quantity) is int and quantity > 0
         and quantity == int(lot)
         == parent["draft"]["body"]["quantity"]
         == reviewed["reviewed_remaining_quantity"],
         "FULL_LOT_OWNED_EXIT_REQUIRED")
    need(body["instrument_token"] == contract["instrument_key"]
         == parent["draft"]["body"]["instrument_token"]
         and body["product"] == parent["draft"]["body"]["product"],
         "EXIT_CONTRACT_IDENTITY_MISMATCH")
    validate_price(contract, body["price"], profile=PROFILE)
    return sha(dict(
        source=source, snapshot=snapshot,
        exit_sequence=exit_sequence, exit_record_hash=record["record_hash"],
    ))


def issue_exit_candidate(
    authority, pin, source, snapshot, *,
    entry_id, request_id, wire, journal, exit_sequence, at,
):
    validate_authority(authority, pin)
    context_fp = exit_context(
        source, snapshot, pin, entry_id=entry_id, request_id=request_id,
        wire=wire, journal=journal, exit_sequence=exit_sequence, as_of=at,
    )
    now = aware(at)
    grant = dict(
        model=MODEL, authorization_id=uuid.uuid4().hex,
        authority_id=authority["authority_id"], account_scope=pin["scope"],
        entry_id=entry_id, request_id=request_id, operation="PLACE",
        wire_fingerprint=sha(wire), context_fingerprint=context_fp,
        issued_at=now.isoformat(),
        expires_at=(now+timedelta(seconds=10)).isoformat(),
        live_clearance_granted=False, production_execution_enabled=False,
    )
    grant["signature"] = signature(grant, authority)
    return grant


def claim_exit_candidate(
    db, grant, authority, pin, source, snapshot, *,
    entry_id, request_id, wire, journal, exit_sequence, attempt_id, at,
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
         and value.get("entry_id") == entry_id
         and value.get("request_id") == request_id
         and value.get("operation") == "PLACE"
         and value.get("wire_fingerprint") == sha(wire)
         and value.get("live_clearance_granted") is False
         and value.get("production_execution_enabled") is False,
         "EXIT_AUTHORIZATION_BINDING_MISMATCH")
    start, end, now = map(aware, (
        value["issued_at"], value["expires_at"], at))
    need(0 < (end-start).total_seconds() <= 10 and start <= now < end,
         "AUTHORIZATION_EXPIRED_OR_FUTURE")
    context_fp = exit_context(
        source, snapshot, pin, entry_id=entry_id, request_id=request_id,
        wire=wire, journal=journal, exit_sequence=exit_sequence, as_of=at)
    need(context_fp == value["context_fingerprint"], "EXIT_CONTEXT_CHANGED")
    need(isinstance(attempt_id, str) and bool(attempt_id), "ATTEMPT_ID_REQUIRED")
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
