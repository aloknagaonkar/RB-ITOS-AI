"""Fixture-only local-reference retirement; broker evidence is preserved."""
from contextlib import closing
from copy import deepcopy
import hmac
import json
import sqlite3

from closed_history_baseline_candidate import seal_history, authenticate, TABLE as HISTORY
from cancellation_lifecycle_review import review_with_cancellations
from market_lab.hilega_preparation_runtime_v1.ownership_state import rollback_database
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_connection
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

TABLE = "fixture_local_reference_retirements"
ACTIVE = {
    "preparation_plans": "plans",
    "preparation_shadow_holds": "holds",
    "preparation_outbox": "outbox",
    "preparation_request_bindings": "bindings",
    "preparation_cash_reservations": "cash_reservations",
}


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def authenticated_retirement(row, archive, pin, entry_id):
    payload = dict(row)
    signed = payload.pop("signature", None)
    need(isinstance(signed, str)
         and hmac.compare_digest(sign(payload, pin), signed),
         "RETIREMENT_SIGNATURE_INVALID")
    authenticate(archive, pin)
    need(row["model"] == "HILEGA_FIXTURE_LOCAL_REFERENCE_RETIREMENT_V1"
         and row["account_scope"] == pin["scope"]
         and row["entry_id"] == archive["entry_id"] == entry_id
         and row["archive_fingerprint"] == sha(archive)
         and row["reservation_release_permission"] is False
         and row["production_execution_enabled"] is False,
         "RETIREMENT_BINDING_OR_AUTHORITY_INVALID")


def retire_fixture_references(
    application_store, execution_path, snapshot, pin, *,
    entry_id, journal, exit_sequences, clock,
    checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_RETIREMENT_ONLY")
    app, broker = map(
        rollback_database, (application_store.path, execution_path))
    need(not app.samefile(broker), "DISTINCT_DATABASES_REQUIRED")
    with application_store.lock():
        with closing(sqlite3.connect(
            app.as_uri()+"?mode=rw", uri=True, timeout=10,
        )) as db:
            db.execute("ATTACH DATABASE ? AS broker",
                       (broker.as_uri()+"?mode=ro",))
            need(db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete"
                 and db.execute("PRAGMA broker.journal_mode").fetchone()[0] == "delete",
                 "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA main.synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                exists = db.execute(
                    "SELECT 1 FROM main.sqlite_master WHERE name=?", (TABLE,)
                ).fetchone()
                old = db.execute(
                    "SELECT data FROM "+TABLE+" WHERE id=?", (entry_id,)
                ).fetchone() if exists else None
                if old:
                    row = json.loads(old[0])
                    archived = db.execute(
                        "SELECT data FROM "+HISTORY+" WHERE id=?", (entry_id,)
                    ).fetchone()
                    need(archived is not None, "RETIREMENT_ARCHIVE_MISSING")
                    authenticated_retirement(
                        row, json.loads(archived[0]), pin, entry_id)
                    need(not any(db.execute(
                        "SELECT 1 FROM "+table+" WHERE id=?", (entry_id,)
                    ).fetchone() for table in ACTIVE),
                        "RETIRED_REFERENCE_REAPPEARED")
                    db.rollback()
                    return dict(
                        status="HISTORICAL_RETIREMENT_REPLAY",
                        idempotent_replay=True, database_modified=False,
                        current_entry_admission_assessed=False,
                        reservation_release_permission=False,
                        production_execution_enabled=False,
                    )

                source = read_connection(
                    db, pin["scope"], expected_mode="OFFLINE_FIXTURE")
                need(all(set(source[key]) == {entry_id}
                         for key in ACTIVE.values()),
                     "SINGLE_ACTIVE_LIFECYCLE_REQUIRED")
                archive = seal_history(
                    db, source, snapshot, pin, entry_id=entry_id,
                    journal=journal, exit_sequences=exit_sequences,
                    as_of=clock().isoformat(),
                )["record"]
                checkpoint("AFTER_HISTORY_SEAL")

                row = dict(
                    model="HILEGA_FIXTURE_LOCAL_REFERENCE_RETIREMENT_V1",
                    account_scope=pin["scope"], entry_id=entry_id,
                    archive_fingerprint=sha(archive),
                    retired_reference_fingerprints={
                        table: sha(source[key][entry_id])
                        for table, key in ACTIVE.items()
                    },
                    local_reference_retired=True,
                    broker_cash_release_assessed=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False,
                )
                row["signature"] = sign(row, pin)
                db.execute(
                    "CREATE TABLE IF NOT EXISTS "+TABLE+
                    "(id TEXT PRIMARY KEY,data TEXT NOT NULL)")
                db.execute("INSERT INTO "+TABLE+" VALUES(?,?)",
                           (entry_id, json.dumps(row, sort_keys=True)))
                for table in ACTIVE:
                    changed = db.execute(
                        "DELETE FROM main."+table+" WHERE id=?", (entry_id,))
                    need(changed.rowcount == 1, "ACTIVE_REFERENCE_CHANGED")
                checkpoint("AFTER_ACTIVE_REFERENCES_RETIRED")
                checkpoint("BEFORE_RETIREMENT_COMMIT")

                expected = deepcopy(source)
                for table, key in ACTIVE.items():
                    expected[key] = {}
                    if table in expected["counts"]:
                        expected["counts"][table] = 0
                current = read_connection(
                    db, pin["scope"], expected_mode="OFFLINE_FIXTURE")
                need(sha(current) == sha(expected),
                     "SOURCE_CHANGED_DURING_RETIREMENT")
                # Recheck original closure evidence after transaction waits.
                final = review_with_cancellations(
                    source, snapshot, pin, entry_id=entry_id,
                    journal=journal, exit_sequences=exit_sequences,
                    as_of=clock().isoformat())
                need(final["reviewed_remaining_quantity"] == 0,
                     "LIFECYCLE_NO_LONGER_FLAT")
                authenticated_retirement(row, archive, pin, entry_id)
                db.commit()
                return dict(
                    status="FIXTURE_LOCAL_REFERENCES_RETIRED",
                    idempotent_replay=False, database_modified=True,
                    broker_records_deleted=False,
                    signed_evidence_deleted=False,
                    repeat_entry_enabled=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False,
                )
            except BaseException:
                db.rollback()
                raise
