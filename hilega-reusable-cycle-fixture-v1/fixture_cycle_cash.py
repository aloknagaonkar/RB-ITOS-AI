"""Reusable fixture-cycle cash; no live execution authority."""
from fixture_cycle_history import (
    review_reentry_history, order_identity, trade_identity,
)
from market_lab.hilega_preparation_runtime_v1.evidence import dependencies, fresh_window
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware, day


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def account_rows(snapshot):
    orders, positions = validate_account_rows(snapshot)
    return dict(
        orders={key: order_identity(row) for key, row in orders.items()},
        trades={(row["order_id"], row["trade_id"]): trade_identity(row)
                for row in snapshot["trades"]},
        positions=positions,
    )


def review_repeat_entry(
    account_capture, cash_capture, archives, pin, *,
    signal_at, premium_paise, fee_buffer_paise, as_of,
):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_REPEAT_ENTRY_ONLY")
    need(bool(archives), "CLOSED_HISTORY_REQUIRED")
    need(type(premium_paise) is int and premium_paise > 0
         and type(fee_buffer_paise) is int and fee_buffer_paise > 0,
         "POSITIVE_INTEGER_PREMIUM_AND_BUFFER_REQUIRED")

    history = review_reentry_history(
        account_capture, archives, pin, as_of=as_of)
    _, gate = dependencies()
    cash = gate.verify_capture(cash_capture, pin, as_of=as_of)
    fresh_window(
        cash_capture["started_at"], cash_capture["completed_at"], as_of)

    # Compare normalized rows without editing either signed envelope.
    need(account_rows(cash_capture) == account_rows(account_capture),
         "ACCOUNT_AND_CASH_CAPTURE_ROWS_DIFFER")
    earliest = min(
        aware(account_capture["generated_at"]),
        aware(cash_capture["started_at"]))
    latest = max(
        aware(account_capture["completed_at"]),
        aware(cash_capture["completed_at"]))
    need(0 <= (latest-earliest).total_seconds() <= 30,
         "COMBINED_CAPTURE_WINDOW_TOO_LONG")

    signal, now = aware(signal_at), aware(as_of)
    need(day(signal) == day(now)
         and 0 <= (now-signal).total_seconds() <= 60,
         "FRESH_SAME_SESSION_SIGNAL_REQUIRED")
    need(all(signal > aware(row["snapshot"]["completed_at"])
             for row in archives),
         "SIGNAL_NOT_AFTER_CLOSED_LIFECYCLE")
    need(signal <= earliest, "CAPTURE_PRECEDES_NEW_SIGNAL")

    issues = cash_capture["diagnostics"]["issues"]
    need(all(isinstance(issue, str) for issue in issues),
         "CASH_DIAGNOSTICS_SCHEMA_INVALID")
    need(set(issues) <= {"BROKER_ORDERS_NOT_MAPPED_TO_STRATEGY"},
         "UNRESOLVED_CASH_DIAGNOSTICS")
    reasons = set(cash["reasons"])
    # Only these ownership warnings are resolved by the history checks above.
    reasons.discard("ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED")
    reasons.discard("ACCOUNT_EVIDENCE_DIAGNOSTICS_REQUIRE_REVIEW")
    available = cash["cash_cents"]
    cap = cash["half_cash_cap_cents"]
    budget = premium_paise + fee_buffer_paise
    if available <= 0 or cap <= 0:
        reasons.add("NO_CASH_CAPACITY")
    if budget > cap:
        reasons.add("HALF_CASH_CAP_EXCEEDED")

    return dict(
        model="HILEGA_FIXTURE_REPEAT_ENTRY_CASH_REVIEW_V1",
        status="REENTRY_REFERENCE_CHECKS_PASS" if not reasons else "BLOCKED",
        reasons=sorted(reasons),
        verified_available_cash_paise=available,
        half_cash_budget_paise=cap,
        proposed_premium_paise=premium_paise,
        explicit_fee_buffer_paise=fee_buffer_paise,
        proposed_budget_paise=budget,
        closed_lifecycle_count=history["matched_closed_lifecycle_count"],
        account_capture_fingerprint=sha(account_capture),
        cash_capture_fingerprint=sha(cash_capture),
        signed_captures_modified=False,
        historical_cash_used_as_current_capacity=False,
        new_signal_journal_admission_verified=False,
        controller_resume_assessed=False,
        market_quote_and_contract_assessed=False,
        entry_permission=False,
        reservation_release_permission=False,
        production_execution_enabled=False,
        production_ready=False,
    )

