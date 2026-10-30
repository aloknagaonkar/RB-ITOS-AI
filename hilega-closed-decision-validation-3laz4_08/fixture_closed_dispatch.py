"""Fixture-only review-to-decision integration. No transport."""
import json

from closed_entry_dispatch import dispatch_closed, read_sources
from closed_dispatch_decisions import record, sha, need


def record_fixture_decision(
    db, application, adapter, pin, *, as_of, checkpoint=lambda stage: None,
):
    from pathlib import Path

    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_SCOPE_REQUIRED")
    need(db.in_transaction, "CALLER_TRANSACTION_REQUIRED")
    database = db.execute("PRAGMA database_list").fetchone()[2]
    need(bool(database), "SEPARATE_FILE_DATABASE_REQUIRED")
    paths = [
        Path(database).resolve(),
        Path(application).resolve(),
        Path(adapter).resolve(),
    ]
    need(len(set(paths)) == 3, "THREE_DISTINCT_DATABASES_REQUIRED")

    before = read_sources(application, adapter, pin["scope"])
    need(len(before["requests"]) == 1, "SINGLE_REQUEST_REQUIRED")
    request_id = before["requests"][0][0]

    report = dispatch_closed(application, adapter, pin, as_of=as_of)
    checkpoint("AFTER_REVIEW")
    need(read_sources(application, adapter, pin["scope"]) == before,
         "SOURCE_CHANGED_BEFORE_DECISION")
    result = record(
        db, pin, request_id=request_id,
        source_fingerprint=sha(before), report=report, assessed_at=as_of,
    )
    checkpoint("AFTER_RECORD_INSERT")
    need(read_sources(application, adapter, pin["scope"]) == before,
         "SOURCE_CHANGED_BEFORE_RETURN")
    return dict(
        result,
        status="FIXTURE_CLOSED_DISPATCH_DECISION_RECORDED",
        caller_commit_required=True,
        source_and_decision_commit_atomic=False,
        production_runtime_integrated=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )