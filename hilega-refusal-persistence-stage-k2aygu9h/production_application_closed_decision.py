import re
"""Pinned-account application-owned refusal-only decision transaction."""
from pathlib import Path
import sqlite3

from closed_entry_dispatch import review_module
from production_closed_decisions import record, sha, need
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_connection,
)


def record_application_decision(
    store, adapter, pin, *, clock, checkpoint=lambda stage: None,
):
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "PINNED_UPSTOX_SCOPE_REQUIRED")
    app = Path(store.path)
    broker = Path(adapter)
    for path in (app, broker):
        need(path.is_file() and not path.is_symlink()
             and not any(p.is_symlink() for p in path.absolute().parents),
             "REGULAR_DATABASE_REQUIRED")
    need(not app.samefile(broker), "DISTINCT_DATABASES_REQUIRED")

    with store.lock(), store.db() as db:
        need(not db.in_transaction, "UNEXPECTED_EXISTING_TRANSACTION")
        need(db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete",
             "APPLICATION_DELETE_JOURNAL_REQUIRED")
        db.execute(
            "ATTACH DATABASE ? AS broker",
            (broker.resolve().as_uri() + "?mode=ro",),
        )
        need(db.execute("PRAGMA broker.journal_mode").fetchone()[0] == "delete",
             "ADAPTER_DELETE_JOURNAL_REQUIRED")
        db.execute("PRAGMA main.synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")

        source = read_connection(db, pin["scope"])
        need(len(source["requests"]) == 1, "SINGLE_REQUEST_REQUIRED")
        report = review_module.review(
            source, pin, as_of=clock().isoformat())
        checkpoint("AFTER_REVIEW")
        need(read_connection(db, pin["scope"]) == source,
             "LOCAL_SOURCE_CHANGED_IN_TRANSACTION")

        closed = dict(
            model="HILEGA_CLOSED_ENTRY_DISPATCH_V1",
            status="DISPATCH_REFUSED_LIVE_GATE_CLOSED",
            reference_checks_passed=report["reference_checks_passed"],
            review_reasons=report["reasons"],
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
        result = record(
            db, pin, request_id=source["requests"][0][0],
            source_fingerprint=sha(source), report=closed,
            assessed_at=clock().isoformat(),
        )
        checkpoint("AFTER_DECISION_INSERT")

        checkpoint("BEFORE_COMMIT")
        final_source = read_connection(db, pin["scope"])
        need(final_source == source, "SOURCE_CHANGED_BEFORE_COMMIT")
        final = review_module.review(
            final_source, pin, as_of=clock().isoformat(),
        )
        need(final == report, "REVIEW_CHANGED_BEFORE_COMMIT")

    return dict(
        result,
        status="APPLICATION_CLOSED_REFUSAL_COMMITTED",
        application_decision_persisted=True,
        broker_evidence_atomic=False,
        production_runtime_integrated=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )