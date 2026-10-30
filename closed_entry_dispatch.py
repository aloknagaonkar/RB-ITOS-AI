"""Closed entry-dispatch prototype. SELECT-only; no transport or ledger writes."""
import importlib.util
from pathlib import Path

from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)

review_path = Path(__file__).with_name("dispatch_precondition_review.py")
if review_path.is_symlink() or not review_path.is_file():
    raise ValueError("REGULAR_REVIEW_MODULE_REQUIRED")
spec = importlib.util.spec_from_file_location(
    "closed_dispatch_review", review_path)
review_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review_module)


def dispatch_closed(application, adapter, pin, *, as_of):
    # Both reads use the existing attached, read-only SQLite reader.
    before = read_sources(application, adapter, pin["scope"])
    checked = review_module.review(before, pin, as_of=as_of)
    after = read_sources(application, adapter, pin["scope"])
    if before != after:
        raise ValueError("LOCAL_SOURCES_CHANGED_DURING_DISPATCH_REVIEW")

    # Explicitly construct permissions: never inherit them from review output.
    return dict(
        model="HILEGA_CLOSED_ENTRY_DISPATCH_V1",
        status="DISPATCH_REFUSED_LIVE_GATE_CLOSED",
        reference_checks_passed=checked["reference_checks_passed"],
        review_reasons=checked["reasons"],
        dispatch_blockers=[
            "PRODUCTION_MUTATIONS_CLOSED_IN_CODE",
            "RUNTIME_DISPATCH_AUTHORIZATION_NOT_IMPLEMENTED",
        ],
        local_sources_unchanged=True,
        evidence_sources_atomic=False,
        current_account_recaptured=False,
        database_modified=False,
        transport_attempt_created=False,
        broker_reads_performed=False,
        entry_permission=False,
        exit_submission_permission=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False,
    )