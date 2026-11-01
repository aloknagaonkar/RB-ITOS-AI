"""Reusable fixture-cycle retirement; no live execution authority."""
from contextlib import closing
from copy import deepcopy
import hmac
import json
import sqlite3

from fixture_cycle_exit import (
    CLOSEOUTS, review_cycle_position,
)
from fixture_reference_retirement_candidate import ACTIVE
from fixture_cycle_history import load_closed_history, cycle_delta
from market_lab.hilega_preparation_runtime_v1.ownership_state import (
    rollback_database,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_connection,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    sign, verify,
)

TABLE = "fixture_cycle_retirements"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def authenticated_closeout(record, pin, entry_id):
    payload = dict(record)
    signature = payload.pop("signature", None)
    need(
        isinstance(signature, str)
        and hmac.compare_digest(sign(payload, pin), signature),
        "REPEAT_CLOSEOUT_SIGNATURE_INVALID")
    need(
        record["model"] == "HILEGA_FIXTURE_CYCLE_CLOSEOUT_V1"
        and record["account_scope"] == pin["scope"]
        and record["entry_id"] == entry_id
        and record["active_references_retired"] is False
        and record["reservation_release_permission"] is False
        and record["production_execution_enabled"] is False,
        "REPEAT_CLOSEOUT_BINDING_INVALID")
    need(
        sha(record["source"]) == record["source_fingerprint"]
        and sha(record["snapshot"]) == record["snapshot_fingerprint"]
        and sha(dict(
            source=record["source"], snapshot=record["snapshot"],
            event=record["event"])) == record["input_fingerprint"],
        "REPEAT_CLOSEOUT_EVIDENCE_CHANGED")
    verify(record["snapshot"], pin, as_of=record["assessed_at"])
    need(
        record["review"]["remaining_quantity"] == 0
        and record["review"]["pending_exit_quantity"] == 0
        and record["review"]["all_orders_terminal"] is True,
        "REPEAT_CLOSEOUT_NOT_FLAT")
    return record


def retire_cycle_fixture(
    application_store, execution_path, snapshot, pin, *,
    entry_id, clock, checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"),
         "FIXTURE_CYCLE_RETIREMENT_ONLY")
    app, broker = map(
        rollback_database, (application_store.path, execution_path))
    need(not app.samefile(broker), "DISTINCT_DATABASES_REQUIRED")
    with application_store.lock():
        with closing(sqlite3.connect(
            app.as_uri()+"?mode=rw", uri=True, timeout=10,
        )) as db:
            db.execute(
                "ATTACH DATABASE ? AS broker",
                (broker.as_uri()+"?mode=ro",))
            need(all(
                db.execute("PRAGMA "+name+".journal_mode").fetchone()[0]
                == "delete" for name in ("main", "broker")),
                "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA main.synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                found = db.execute(
                    "SELECT data FROM "+CLOSEOUTS+" WHERE id=?",
                    (entry_id,)).fetchone()
                need(found is not None, "REPEAT_CLOSEOUT_REQUIRED")
                closeout = authenticated_closeout(
                    json.loads(found[0]), pin, entry_id)
                archives = load_closed_history(db, pin, before_entry_id=entry_id)
                history_fingerprints = sorted(sha(r) for r in archives)
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name=?", (TABLE,)
                ).fetchone()
                old = db.execute(
                    "SELECT data FROM "+TABLE+" WHERE id=?",
                    (entry_id,)).fetchone() if exists else None
                if old is not None:
                    row = json.loads(old[0])
                    payload = dict(row)
                    signature = payload.pop("signature", None)
                    need(
                        isinstance(signature, str)
                        and hmac.compare_digest(sign(payload, pin), signature),
                        "REPEAT_RETIREMENT_SIGNATURE_INVALID")
                    need(
                        row["model"] == "HILEGA_FIXTURE_CYCLE_RETIREMENT_V1"
                        and row["entry_id"] == entry_id
                        and row["account_scope"] == pin["scope"]
                        and row["closeout_fingerprint"] == sha(closeout)
                        and row["history_fingerprints"] == history_fingerprints
                        and row["cycle_index"] == archives[0]["cycle_count"]+1
                        and row["predecessor_fingerprint"] == sha(archives[0])
                        and row["cycle_delta"] == cycle_delta(archives[0], closeout)
                        and row["local_reference_retired"] is True
                        and row["reservation_release_permission"] is False
                        and row["production_execution_enabled"] is False,
                        "REPEAT_RETIREMENT_BINDING_CHANGED")
                    need(not any(db.execute(
                        "SELECT 1 FROM "+table+" WHERE id=?",
                        (entry_id,)).fetchone() for table in ACTIVE),
                        "RETIRED_REPEAT_REFERENCE_REAPPEARED")
                    db.rollback()
                    return dict(
                        status="CYCLE_RETIREMENT_HISTORICAL_REPLAY",
                        idempotent_replay=True, database_modified=False,
                        next_entry_admission_assessed=False,
                        reservation_release_permission=False,
                        production_execution_enabled=False)

                source = read_connection(
                    db, pin["scope"], expected_mode="OFFLINE_FIXTURE")
                need(all(
                    set(source[category]) == {entry_id}
                    for category in ACTIVE.values()),
                    "SINGLE_ACTIVE_REPEAT_LIFECYCLE_REQUIRED")
                need(sha(source) == closeout["source_fingerprint"],
                     "REPEAT_SOURCE_CHANGED_AFTER_CLOSEOUT")
                now = clock()
                report = review_cycle_position(
                    db, source, snapshot, pin, entry_id,
                    closeout["event"], now.isoformat())
                need(
                    report["remaining_quantity"] == 0
                    and report["pending_exit_quantity"] == 0
                    and report["all_orders_terminal"] is True,
                    "REPEAT_RETIREMENT_REQUIRES_TERMINAL_FLAT")
                row = dict(
                    model="HILEGA_FIXTURE_CYCLE_RETIREMENT_V1",
                    entry_id=entry_id, account_scope=pin["scope"],
                    assessed_at=now.isoformat(),
                    cycle_index=archives[0]["cycle_count"]+1,
                    predecessor_fingerprint=sha(archives[0]),
                    cycle_delta=cycle_delta(archives[0], closeout),
                    closeout_fingerprint=sha(closeout),
                    history_fingerprints=history_fingerprints,
                    snapshot=snapshot, snapshot_fingerprint=sha(snapshot),
                    review=report,
                    retired_reference_fingerprints={
                        table: sha(source[category][entry_id])
                        for table, category in ACTIVE.items()
                    },
                    local_reference_retired=True,
                    broker_cash_release_assessed=False,
                    next_entry_admission_assessed=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False)
                row = json.loads(json.dumps(row))
                row["signature"] = sign(row, pin)
                db.execute(
                    "CREATE TABLE IF NOT EXISTS "+TABLE+"("
                    "id TEXT PRIMARY KEY,data TEXT NOT NULL)")
                db.execute(
                    "INSERT INTO "+TABLE+" VALUES(?,?)",
                    (entry_id, json.dumps(row, sort_keys=True)))
                checkpoint("AFTER_CYCLE_RETIREMENT_SEAL")
                for table in ACTIVE:
                    changed = db.execute(
                        "DELETE FROM main."+table+" WHERE id=?",
                        (entry_id,))
                    need(changed.rowcount == 1,
                         "REPEAT_ACTIVE_REFERENCE_CHANGED")
                checkpoint("AFTER_CYCLE_REFERENCES_RETIRED")
                checkpoint("BEFORE_CYCLE_RETIREMENT_COMMIT")
                expected = deepcopy(source)
                for table, category in ACTIVE.items():
                    expected[category] = {}
                    if table in expected["counts"]:
                        expected["counts"][table] = 0
                current = read_connection(
                    db, pin["scope"], expected_mode="OFFLINE_FIXTURE")
                need(sha(current) == sha(expected),
                     "REPEAT_RETIREMENT_SOURCE_CHANGED")

                final_report = review_cycle_position(
                    db, source, snapshot, pin, entry_id,
                    closeout["event"], clock().isoformat())
                need(final_report == report,
                     "REPEAT_RETIREMENT_REVIEW_CHANGED")
                persisted_closeout = db.execute(
                    "SELECT data FROM "+CLOSEOUTS+" WHERE id=?",
                    (entry_id,)).fetchone()
                need(
                    persisted_closeout is not None
                    and sha(authenticated_closeout(
                        json.loads(persisted_closeout[0]), pin, entry_id))
                        == sha(closeout),
                    "REPEAT_CLOSEOUT_CHANGED_DURING_RETIREMENT")
                final_history = load_closed_history(db, pin, before_entry_id=entry_id)
                need(
                    sorted(sha(r) for r in final_history)
                    == history_fingerprints,
                    "REPEAT_HISTORY_CHANGED_DURING_RETIREMENT")
                saved = json.loads(db.execute(
                    "SELECT data FROM "+TABLE+" WHERE id=?",
                    (entry_id,)).fetchone()[0])
                need(saved == row, "REPEAT_RETIREMENT_RECORD_CHANGED")
                db.commit()
                return dict(
                    status="FIXTURE_CYCLE_REFERENCES_RETIRED",
                    idempotent_replay=False,
                    database_modified=True,
                    broker_records_deleted=False,
                    signed_evidence_deleted=False,
                    next_entry_admission_assessed=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False)
            finally:
                if db.in_transaction:
                    db.rollback()

