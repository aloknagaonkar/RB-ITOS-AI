"""Staged account-capture -> lifecycle review callback. No order submission."""
from application_lifecycle_review import record_application_review
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import verify


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def capture_and_record(
    application, adapter, pin, *, journal, exit_sequences,
    capture_provider, clock, mode="LIVE_CLOSED",
    checkpoint=lambda stage: None,
):
    before = read_sources(application, adapter, pin["scope"], expected_mode=mode)
    if not before["bindings"]:
        need(not before["requests"]
             and not before["attempts"] and not before["receipts"]
             and not before["cash_reservations"],
             "UNBOUND_ACTIVITY_REQUIRES_RECONCILIATION")
        return dict(
            status="NO_BOUND_ENTRY_CAPTURE_NOT_REQUESTED",
            account_capture_requested=False,
            database_modified=False,
            orders_sent_to_upstox=False,
            production_execution_enabled=False,
            runtime_integrated=False,
        )
    need(len(before["bindings"]) == 1, "SINGLE_BOUND_ENTRY_REQUIRED")
    key = next(iter(before["bindings"]))
    snapshot = capture_provider()
    # Validate even on a historical replay: this callback promises a fresh
    # capture. Existing-attempt recovery uses a separate non-submitting path.
    verify(snapshot, pin, as_of=clock().isoformat())
    current = read_sources(
        application, adapter, pin["scope"], expected_mode=mode)
    need(sha(current) == sha(before), "SOURCE_CHANGED_DURING_ACCOUNT_CAPTURE")
    result = record_application_review(
        application, adapter, snapshot, pin,
        entry_id=key, journal=journal, exit_sequences=exit_sequences,
        clock=clock, mode=mode,
    )
    checkpoint("AFTER_COMMIT_BEFORE_RESULT")
    return dict(
        result,
        account_capture_requested=True,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        runtime_integrated=False,
    )
