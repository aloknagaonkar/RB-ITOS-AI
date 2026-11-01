"""Signed BUY authorization constraints. Hard production gate remains closed."""
from datetime import timedelta
import hmac
import re
import uuid

from dispatch_precondition_review import review
from fixture_execution_authorization import signature
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    verify, aware,
)

TABLE = "production_candidate_authorization_claims"
MODEL = "HILEGA_PRODUCTION_ENTRY_AUTHORIZATION_CANDIDATE_V1"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def validate_authority(authority, pin):
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "UPSTOX_ACCOUNT_SCOPE_REQUIRED")
    need(authority.get("account_scope") == pin["scope"]
         and isinstance(authority.get("authority_id"), str)
         and bool(authority["authority_id"]),
         "AUTHORITY_ACCOUNT_BINDING_REQUIRED")
    key = authority.get("key")
    need(isinstance(key, str)
         and re.fullmatch(r"[0-9a-f]{64}", key) is not None
         and key != pin["key"],
         "INDEPENDENT_AUTHORITY_KEY_REQUIRED")


def entry_context(source, snapshot, pin, *, request_id, wire, as_of):
    need(source["mode"] == "LIVE_CLOSED"
         and source["scope"] == pin["scope"], "LIVE_CLOSED_CONTEXT_REQUIRED")
    checked = review(source, pin, as_of=as_of)
    need(checked["reference_checks_passed"],
         "FRESH_ENTRY_REFERENCE_CHECKS_REQUIRED")
    verify(snapshot, pin, as_of=as_of)
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True
         and snapshot.get("source_atomic") is False
         and snapshot.get("position_fill_linkage_verified") is False
         and snapshot.get("live_pnl") is None,
         "COMPLETE_READ_ONLY_ACCOUNT_CAPTURE_REQUIRED")
    orders, positions = validate_account_rows(snapshot)
    need(not orders and not snapshot["trades"] and not any(positions.values()),
         "EMPTY_ACCOUNT_BASELINE_REQUIRED")
    need(len(source["requests"]) == 1
         and source["requests"][0][0] == request_id,
         "EXACT_PREPARED_REQUEST_REQUIRED")
    import json
    request = json.loads(source["requests"][0][2])
    body = request["draft"]["body"]
    need(wire == dict(
        method="POST", host="api-hft.upstox.com",
        path="/v3/order/place", body=body,
    ) and body["transaction_type"] == "BUY"
      and body["order_type"] == "LIMIT",
      "EXACT_BUY_LIMIT_WIRE_REQUIRED")
    return sha(dict(source=source, snapshot=snapshot))


def issue_candidate(
    authority, pin, source, snapshot, *, request_id, wire, at,
):
    validate_authority(authority, pin)
    context_fp = entry_context(
        source, snapshot, pin, request_id=request_id, wire=wire, as_of=at)
    now = aware(at)
    grant = dict(
        model=MODEL, authorization_id=uuid.uuid4().hex,
        authority_id=authority["authority_id"],
        account_scope=pin["scope"], request_id=request_id,
        operation="PLACE", wire_fingerprint=sha(wire),
        context_fingerprint=context_fp,
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=10)).isoformat(),
        production_execution_enabled=False,
        live_clearance_granted=False,
    )
    grant["signature"] = signature(grant, authority)
    return grant


def claim_candidate(
    db, grant, authority, pin, source, snapshot, *,
    request_id, wire, attempt_id, at,
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
         and value.get("operation") == "PLACE"
         and value.get("wire_fingerprint") == sha(wire)
         and value.get("production_execution_enabled") is False
         and value.get("live_clearance_granted") is False,
         "AUTHORIZATION_REQUEST_OR_WIRE_MISMATCH")
    start, end, now = map(aware, (
        value["issued_at"], value["expires_at"], at))
    need(0 < (end-start).total_seconds() <= 10 and start <= now < end,
         "AUTHORIZATION_EXPIRED_OR_FUTURE")
    context_fp = entry_context(
        source, snapshot, pin, request_id=request_id, wire=wire, as_of=at)
    need(context_fp == value["context_fingerprint"],
         "AUTHORIZATION_CONTEXT_CHANGED")
    need(isinstance(attempt_id, str) and bool(attempt_id),
         "ATTEMPT_ID_REQUIRED")
    db.execute(
        "CREATE TABLE IF NOT EXISTS " + TABLE + "("
        "id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,"
        "attempt_id TEXT UNIQUE NOT NULL)"
    )
    need(db.execute(
        "SELECT 1 FROM " + TABLE + " WHERE id=? OR request_id=?",
        (value["authorization_id"], request_id),
    ).fetchone() is None, "AUTHORIZATION_ALREADY_CONSUMED")
    db.execute(
        "INSERT INTO " + TABLE + " VALUES(?,?,?)",
        (value["authorization_id"], request_id, attempt_id),
    )
    return dict(
        authorization_claimed=True, context_revalidated=True,
        account_scope=pin["scope"], request_id=request_id,
        attempt_id=attempt_id, wire_fingerprint=sha(wire),
        production_execution_enabled=False,
    )
