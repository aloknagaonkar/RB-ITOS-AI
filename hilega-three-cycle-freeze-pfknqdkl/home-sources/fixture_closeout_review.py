"""Fixture closeout arithmetic. No broker cash or reservation-release authority."""
from decimal import Decimal
import hmac

from cancellation_lifecycle_review import review_with_cancellations
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    aware, sign, day,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def trade_value_paise(trade):
    price = Decimal(str(trade["price"]))
    need(price.is_finite() and price > 0, "TRADE_PRICE_INVALID")
    quantity = trade["quantity"]
    need(type(quantity) is int and quantity > 0, "TRADE_QUANTITY_INVALID")
    numerator, denominator = price.as_integer_ratio()
    value, remainder = divmod(numerator * quantity * 100, denominator)
    need(remainder == 0, "EXACT_PAISE_TRADE_VALUE_REQUIRED")
    return value


def fee_total(evidence, snapshot, pin, *, as_of):
    need(isinstance(evidence, dict), "SIGNED_FEE_EVIDENCE_REQUIRED")
    payload = dict(evidence)
    signature = payload.pop("signature", None)
    need(isinstance(signature, str)
         and hmac.compare_digest(sign(payload, pin), signature),
         "FEE_SIGNATURE_INVALID")
    need(payload.get("model") == "HILEGA_FIXTURE_FEE_EVIDENCE_V1"
         and payload.get("account_scope") == pin["scope"]
         and payload.get("snapshot_fingerprint") == sha(snapshot)
         and payload.get("complete") is True
         and payload.get("production_execution_enabled") is False,
         "FIXTURE_FEE_BINDING_INVALID")
    generated, now = aware(payload["generated_at"]), aware(as_of)
    need(0 <= (now-generated).total_seconds() <= 30
         and day(generated) == day(now), "FEE_EVIDENCE_STALE_OR_FUTURE")
    lines = payload.get("lines")
    need(isinstance(lines, list), "FEE_LINES_REQUIRED")
    expected = {(t["order_id"], t["trade_id"]) for t in snapshot["trades"]}
    seen, total = set(), 0
    for line in lines:
        key = line["order_id"], line["trade_id"]
        need(key not in seen, "DUPLICATE_FEE_LINE")
        seen.add(key)
        fee = line["fee_paise"]
        need(type(fee) is int and fee >= 0, "NONNEGATIVE_INTEGER_FEE_REQUIRED")
        total += fee
    need(seen == expected, "FEE_TRADE_COVERAGE_MISMATCH")
    return total


def assess_closeout(
    source, snapshot, pin, *, entry_id, journal, exit_sequences,
    fee_evidence, as_of,
):
    need(pin["scope"].startswith("FIXTURE:")
         and source["mode"] == "OFFLINE_FIXTURE",
         "FIXTURE_CLOSEOUT_ONLY")
    reviewed = review_with_cancellations(
        source, snapshot, pin, entry_id=entry_id, as_of=as_of,
        journal=journal, exit_sequences=exit_sequences,
    )
    reasons = []
    if reviewed["reviewed_remaining_quantity"] != 0:
        reasons.append("POSITION_NOT_FLAT")
    if any(o["status"] not in {"FILLED", "CANCELLED", "REJECTED"}
           or o["pending"] != 0 for o in snapshot["orders"]):
        reasons.append("WORKING_OR_UNRESOLVED_ORDER")
    fees = None
    if fee_evidence is None:
        reasons.append("COMPLETE_FEE_EVIDENCE_REQUIRED")
    else:
        fees = fee_total(fee_evidence, snapshot, pin, as_of=as_of)
    flat = reviewed["reviewed_remaining_quantity"] == 0
    bought = sum(trade_value_paise(t) for t in snapshot["trades"]
                 if t["side"] == "BUY")
    sold = sum(trade_value_paise(t) for t in snapshot["trades"]
               if t["side"] == "SELL")
    gross = sold-bought if flat else None
    return dict(
        model="HILEGA_FIXTURE_CLOSEOUT_REVIEW_V1",
        status="FIXTURE_CLOSEOUT_CONDITIONS_PASSED" if not reasons else "HOLD_RETAINED",
        reasons=sorted(set(reasons)),
        entry_request_id=entry_id,
        snapshot_fingerprint=sha(snapshot),
        source_fingerprint=sha(source),
        reviewed_remaining_quantity=reviewed["reviewed_remaining_quantity"],
        fixture_buy_value_paise=bought,
        fixture_sell_value_paise=sold,
        fixture_gross_realized_pnl_paise=gross,
        fixture_fees_paise=fees,
        fixture_net_realized_pnl_paise=(
            gross-fees if gross is not None and fees is not None else None),
        fixture_release_conditions_passed=not reasons,
        actual_broker_fees_verified=False,
        application_reservation_modified=False,
        broker_cash_locked=False,
        reservation_release_permission=False,
        strategy_ownership_verified=False,
        orders_sent=False,
        production_execution_enabled=False,
        production_ready=False,
    )
