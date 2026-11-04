"""Staged application lifecycle reference persistence. No execution."""
from contextlib import closing
import fcntl
import os
import re
import sqlite3

from application_lifecycle_state import record_review
from market_lab.hilega_preparation_runtime_v1.ownership_state import rollback_database
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_connection


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def record_application_review(
    application, adapter, snapshot, pin, *,
    entry_id, journal, exit_sequences, clock,
    mode="LIVE_CLOSED", checkpoint=lambda stage: None,
):
    need(mode in {"LIVE_CLOSED", "OFFLINE_FIXTURE"}, "EVIDENCE_MODE_INVALID")
    if mode == "LIVE_CLOSED":
        need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
             "LIVE_PIN_SCOPE_REQUIRED")
    else:
        need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_SCOPE_REQUIRED")
    app, broker = map(rollback_database, (application, adapter))
    need(not app.samefile(broker), "DISTINCT_DATABASES_REQUIRED")
    lock_path = str(app) + ".control.lock"
    # Require the application's existing lock; do not initialize a Store.
    fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with closing(sqlite3.connect(
                app.as_uri() + "?mode=rw", uri=True, timeout=10,
            )) as db:
                db.execute("ATTACH DATABASE ? AS broker",
                           (broker.as_uri() + "?mode=ro",))
                need(
                    db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete"
                    and db.execute(
                        "PRAGMA broker.journal_mode").fetchone()[0] == "delete",
                    "DELETE_JOURNAL_REQUIRED",
                )
                db.execute("PRAGMA main.synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                try:
                    result = record_review(
                        db, pin, snapshot,
                        read_source=lambda: read_connection(
                            db, pin["scope"], expected_mode=mode),
                        entry_id=entry_id, journal=journal,
                        exit_sequences=exit_sequences,
                        clock=clock, checkpoint=checkpoint,
                    )
                    db.commit()
                    return dict(
                        result,
                        status=(
                            "APPLICATION_LIFECYCLE_REPLAY"
                            if result["idempotent_replay"] else
                            "APPLICATION_LIFECYCLE_REVIEW_COMMITTED"
                        ),
                        database_modified=not result["idempotent_replay"],
                        evidence_sources_atomic=False,
                        runtime_integrated=False,
                        orders_sent=False,
                        production_execution_enabled=False,
                        exit_submission_permission=False,
                        reservation_release_permission=False,
                    )
                except BaseException:
                    db.rollback()
                    raise
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
