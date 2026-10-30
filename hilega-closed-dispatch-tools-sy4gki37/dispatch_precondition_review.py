"""Read-only prepared-entry checks; no dispatch or database access."""
import json
import re

from market_lab.hilega_preparation_runtime_v1.ownership_checks import (
    risk_evidence_audit as audit,
)
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
from market_lab.hilega_preparation_runtime_v1.evidence import validate, digest
from market_lab.hilega_execution_port_v1.adapter import validated_request


def need(ok, reason):
    if not ok:
        raise ValueError(reason)



def verify_candidate_cost(candidate, reservation, body, contract, ask):
    from market_lab.hilega_nifty_option_price_grid_v1 import (
        PROFILE, number, validate_price,
    )
    need(body.get("order_type") == "LIMIT"
         and body.get("transaction_type") == "BUY",
         "BUY_LIMIT_CANDIDATE_REQUIRED")
    quantity = body.get("quantity")
    need(type(quantity) is int and quantity > 0
         and number(contract["lot_size"]) == quantity,
         "EXACT_ONE_LOT_QUANTITY_REQUIRED")
    price = validate_price(contract, body["price"], profile=PROFILE)
    need(price == number(ask), "LIMIT_PRICE_DIFFERS_FROM_OBSERVED_ASK")

    numerator, denominator = price.as_integer_ratio()
    premium, remainder = divmod(numerator * quantity * 100, denominator)
    need(remainder == 0, "EXACT_PAISE_PREMIUM_REQUIRED")
    for field in ("premium_cents", "fee_buffer_cents", "budget_cents"):
        need(type(candidate.get(field)) is int and candidate[field] > 0,
             "CANDIDATE_COST_INTEGER_REQUIRED")
    need(candidate["premium_cents"] == premium,
         "CANDIDATE_PREMIUM_MISMATCH")
    buffer = candidate["fee_buffer_cents"]
    budget = premium + buffer
    need(candidate["budget_cents"] == budget,
         "CANDIDATE_BUDGET_ARITHMETIC_MISMATCH")
    need(type(reservation.get("premium_cents")) is int
         and type(reservation.get("fee_buffer_cents")) is int
         and reservation["premium_cents"] == premium
         and reservation["fee_buffer_cents"] == buffer,
         "RESERVATION_COST_COMPONENT_MISMATCH")
    need(type(reservation.get("held_cents")) is int
         and type(reservation.get("cash_cap_cents")) is int
         and budget <= reservation["held_cents"]
         <= reservation["cash_cap_cents"],
         "CANDIDATE_EXCEEDS_RESERVED_BUDGET")
    return dict(premium_paise=premium, buffer_paise=buffer,
                budget_paise=budget)


def verify_candidate_age(created_at, as_of):
    from market_lab.hilega_preparation_runtime_v1.evidence import aware
    age = (aware(as_of) - aware(created_at)).total_seconds()
    need(0 <= age <= 10, "CANDIDATE_STALE_OR_FUTURE")
    return age

def review(source, pin, *, as_of):
    result = dict(
        model="HILEGA_DISPATCH_PRECONDITION_REVIEW_V1",
        scope="LOCAL_REFERENCES_AND_SIGNED_PREPARATION_EVIDENCE_ONLY",
        status="BLOCKED_REFERENCE_CHECKS",
        reference_checks_passed=False,
        reasons=[],
        dispatch_blockers=[
            "PRODUCTION_MUTATIONS_CLOSED_IN_CODE",
            "RUNTIME_DISPATCH_AUTHORIZATION_NOT_IMPLEMENTED",
        ],
        current_account_recaptured=False,
        signal_admission_reauthorized=False,
        pricing_policy_approved_for_production=False,
        real_funds_reservation_verified=False,
        fees_complete=False,
        database_modified=False,
        broker_reads_performed=False,
        entry_permission=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False,
    )
    try:
        need(source["scope"] == pin["scope"]
             and source["mode"] == "LIVE_CLOSED",
             "CLOSED_PINNED_SOURCE_REQUIRED")
        need(source["control"]["mode"] == "PAUSED",
             "PAUSED_CONTROLLER_REQUIRED")
        from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open
        from market_lab.hilega_preparation_runtime_v1.evidence import aware
        now = aware(as_of)
        need(entry_clock_open(now), "ENTRY_CLOCK_WINDOW_CLOSED")
        audit.assess(source)

        stop = source["stop_state"]
        need(isinstance(stop, list) and len(stop) == 2
             and all(type(v) is int and v >= 0 for v in stop)
             and stop[0] == stop[1], "STOP_STATE_UNRESOLVED")
        need(not source["attempts"] and not source["receipts"],
             "EXISTING_ATTEMPT_OR_RECEIPT_REQUIRES_RECONCILIATION")
        need(all(source["counts"][k] == 0 for k in (
            "intents", "sim_orders", "sim_fills",
            "sim_allocation_reservations",
        )), "CONTROLLER_EXECUTION_HISTORY_REQUIRES_REVIEW")
        need(len(source["requests"]) == 1
             and len(source["bindings"]) == 1,
             "SINGLE_BOUND_PREPARED_ENTRY_REQUIRED")

        key, fingerprint, raw = source["requests"][0]
        request = json.loads(raw)
        need(request["state"] == "PREPARED"
             and request["order_id"] is None,
             "UNSUBMITTED_PREPARED_REQUEST_REQUIRED")
        need(set(source["plans"]) == set(source["holds"])
             == set(source["outbox"]) == set(source["bindings"]) == {key},
             "SINGLE_APPLICATION_ENTRY_REQUIRED")
        need(set(source["cash_reservations"]) == {key},
             "SINGLE_LOCAL_RESERVATION_REQUIRED")

        reservation = source["cash_reservations"][key]
        verify_row(reservation, pin)
        need(reservation["state"] == "RESERVED_DISABLED_REQUEST",
             "UNKNOWN_OUTCOME_HOLD_RETAINED")
        binding = source["bindings"][key]
        need(
            reservation["request_fingerprint"] == fingerprint
            and reservation["plan_fingerprint"] == digest(source["plans"][key])
            and reservation["shadow_hold_fingerprint"] == digest(source["holds"][key])
            and reservation["outbox_fingerprint"] == digest(source["outbox"][key]),
            "RESERVATION_BINDING_REFERENCE_MISMATCH",
        )
        need(reservation["id"] == key
             and reservation["held_cents"] == binding["held_cents"]
             and reservation["cash_cap_cents"] == binding["cash_cap_cents"],
             "RESERVATION_BINDING_AMOUNT_MISMATCH")

        _, calculated = validated_request(
            request["draft"],
            signal_id=request["signal_id"],
            signal_at=request["signal_at"],
            direction=request["direction"],
            reservation_reference=request["reservation_reference"],
            as_of=as_of,
        )
        need(calculated == fingerprint, "REQUEST_FINGERPRINT_MISMATCH")
        need(request["draft"]["body"]["transaction_type"] == "BUY",
             "ENTRY_BUY_REQUIRED")

        bundle = json.loads(source["evidence"][binding["bundle_fingerprint"]])
        plans = validate(bundle, pin, as_of=as_of)
        plan = next(p for p in plans if p["direction"] == request["direction"])
        need(plan["evidence_checks_passed"],
             "PREPARATION_EVIDENCE_NOT_CLEARED")
        need(plan["instrument"] == request["draft"]["body"]["instrument_token"]
             and plan["quantity"] == request["draft"]["body"]["quantity"],
             "CURRENT_PREVIEW_CONTRACT_MISMATCH")
        need(reservation["held_cents"] <= plan["half_cash_cap_cents"],
             "SIGNED_CASH_CAP_EXCEEDED")

        candidate = source["outbox"][key]["disabled_request_candidate"]
        costs = verify_candidate_cost(
            candidate, reservation, request["draft"]["body"],
            plan["contract"], plan["quote"]["ask"],
        )
        need(costs["budget_paise"] <= plan["half_cash_cap_cents"],
             "CANDIDATE_EXCEEDS_SIGNED_CASH_CAP")
        from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open
        from market_lab.hilega_preparation_runtime_v1.evidence import aware, day
        from market_lab.hilega_preparation_runtime_v1.limit_candidate import build_candidate
        from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE

        need(entry_clock_open(aware(request["signal_at"])),
             "ENTRY_CLOCK_WINDOW_CLOSED")
        need(source["control"].get("session_date") == day(now),
             "CONTROL_SESSION_MISMATCH")
        verify_candidate_age(candidate["draft"]["created_at"], as_of)
        expected = build_candidate(
            source["plans"][key], source["holds"][key],
            source["outbox"][key], bundle, pin,
            now=now, session_date=day(now),
            fee_buffer_cents=candidate["fee_buffer_cents"], profile=PROFILE,
        )
        need(candidate == expected, "CANDIDATE_RECONSTRUCTION_MISMATCH")
        result.update(
            status="REFERENCES_CHECKED_DISPATCH_STILL_BLOCKED",
            reference_checks_passed=True,
        )
    except Exception as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", reason):
            reason = "SOURCE_SCHEMA_OR_EVIDENCE_INVALID"
        result["reasons"] = [reason]
    return result