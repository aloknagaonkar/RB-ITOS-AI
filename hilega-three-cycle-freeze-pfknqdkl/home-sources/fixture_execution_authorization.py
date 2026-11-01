"""Synthetic authorization contract. Never production execution permission."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import json
import uuid


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def signature(value, pin):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hmac.new(bytes.fromhex(pin["key"]), raw.encode(),
                    hashlib.sha256).hexdigest()


def aware(value):
    at = datetime.fromisoformat(value)
    need(at.tzinfo is not None and at.utcoffset() is not None,
         "AWARE_AUTHORIZATION_TIME_REQUIRED")
    return at


def issue(pin, *, request_id, wire, budget_paise, fee_buffer_paise, at):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_ACCOUNT_REQUIRED")
    need(isinstance(request_id, str) and bool(request_id),
         "REQUEST_ID_REQUIRED")
    need(type(budget_paise) is int and budget_paise > 0
         and type(fee_buffer_paise) is int and fee_buffer_paise > 0,
         "INTEGER_BUDGET_AND_BUFFER_REQUIRED")
    body = wire["body"]
    need(wire["method"] == "POST"
         and wire["host"] == "api-hft.upstox.com"
         and wire["path"] == "/v3/order/place"
         and body["transaction_type"] == "BUY"
         and body["order_type"] == "LIMIT",
         "ENTRY_BUY_LIMIT_WIRE_REQUIRED")
    quantity = body["quantity"]
    need(type(quantity) is int and quantity > 0,
         "POSITIVE_INTEGER_QUANTITY_REQUIRED")
    need(not isinstance(body["price"], bool), "PRICE_INVALID")
    price = Decimal(str(body["price"]))
    need(price.is_finite() and price > 0, "PRICE_INVALID")
    numerator, denominator = price.as_integer_ratio()
    premium, remainder = divmod(numerator * quantity * 100, denominator)
    need(remainder == 0 and premium + fee_buffer_paise <= budget_paise,
         "AUTHORIZED_BUDGET_EXCEEDED")

    start = aware(at)
    value = dict(
        model="HILEGA_FIXTURE_EXECUTION_AUTHORIZATION_V1",
        authorization_id=uuid.uuid4().hex,
        account_scope=pin["scope"], request_id=request_id,
        wire_fingerprint=sha(wire), budget_paise=budget_paise,
        fee_buffer_paise=fee_buffer_paise,
        issued_at=start.isoformat(),
        expires_at=(start + timedelta(seconds=10)).isoformat(),
        production_execution_enabled=False,
    )
    value["signature"] = signature(value, pin)
    return value


def claim(db, authorization, pin, *, request_id, wire, at, attempt_id):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_ACCOUNT_REQUIRED")
    need(db.in_transaction, "CALLER_TRANSACTION_REQUIRED")
    need(isinstance(authorization, dict), "AUTHORIZATION_REQUIRED")
    value = dict(authorization)
    signed = value.pop("signature", None)
    need(isinstance(signed, str)
         and hmac.compare_digest(signature(value, pin), signed),
         "AUTHORIZATION_SIGNATURE_INVALID")
    need(value["model"] == "HILEGA_FIXTURE_EXECUTION_AUTHORIZATION_V1"
         and value["production_execution_enabled"] is False,
         "FIXTURE_AUTHORIZATION_REQUIRED")
    need(value["account_scope"] == pin["scope"]
         and value["request_id"] == request_id
         and value["wire_fingerprint"] == sha(wire),
         "AUTHORIZATION_BINDING_MISMATCH")
    start, end, now = map(aware, (
        value["issued_at"], value["expires_at"], at))
    need(0 < (end-start).total_seconds() <= 10
         and start <= now < end,
         "AUTHORIZATION_EXPIRED_OR_FUTURE")
    need(isinstance(attempt_id, str) and bool(attempt_id),
         "ATTEMPT_ID_REQUIRED")

    db.execute(
        "CREATE TABLE IF NOT EXISTS fixture_authorization_claims("
        "id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,"
        "attempt_id TEXT UNIQUE NOT NULL)")
    exists = db.execute(
        "SELECT 1 FROM fixture_authorization_claims "
        "WHERE id=? OR request_id=?",
        (value["authorization_id"], request_id),
    ).fetchone()
    need(exists is None, "AUTHORIZATION_ALREADY_CONSUMED")
    db.execute(
        "INSERT INTO fixture_authorization_claims VALUES(?,?,?)",
        (value["authorization_id"], request_id, attempt_id),
    )
    return dict(
        fixture_authorization_claimed=True,
        caller_commit_required=True,
        production_execution_enabled=False,
    )