from contextlib import closing
from datetime import datetime
from pathlib import Path
import json
import sqlite3

from market_lab.hilega_preparation_runtime_v1.source import event_digest
from market_lab.hilega_production_simulator_bridge_v1 import (
    verified_records, accepted, POLICY, VERSION,
)

app = Path(
    "data/research/hilega-production-workspace/sim.sqlite"
).resolve()
boundary = datetime.fromisoformat("2026-10-30T11:10:00+05:30")

with closing(sqlite3.connect(app.as_uri()+"?mode=ro", uri=True)) as db:
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    cursor_row = db.execute(
        "SELECT data FROM preparation_source WHERE id=1"
    ).fetchone()
    audits = db.execute(
        "SELECT seq,data FROM preparation_events ORDER BY seq"
    ).fetchall()
    db.rollback()

if cursor_row is None:
    raise SystemExit("STOP: source cursor required")
cursor = json.loads(cursor_row[0])
journal = Path(cursor["path"])
if journal.is_symlink() or not journal.is_file():
    raise SystemExit("STOP: regular source journal required")

records = verified_records(journal)
sequence = cursor["sequence"]
if not (
    type(sequence) is int and 0 <= sequence <= len(records)
    and (sequence == 0 or records[sequence-1]["record_hash"] == cursor["hash"])
):
    raise SystemExit("STOP: source cursor prefix mismatch")

expected = {}
for record in records:
    payload = record.get("payload") or {}
    stamp = payload.get("decision_timestamp") or payload.get("cutoff_timestamp")
    if not stamp:
        continue
    try:
        at = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        continue
    if at != boundary or payload.get("policy_id") != POLICY:
        continue
    if payload.get("strategy_version") != VERSION:
        raise SystemExit("STOP: target-boundary strategy version mismatch")

    for event in accepted(record):
        if datetime.fromisoformat(event["event_at"]) != boundary:
            continue
        reference = dict(
            signal_id=event["id"],
            signal_at=event["event_at"],
            direction=event["direction"],
            source_sequence=event["source_sequence"],
            source_record_hash=event["source_record_hash"],
            event_fingerprint=event_digest(event),
        )
        if reference["source_sequence"] > sequence:
            raise SystemExit("STOP: matching event not yet consumed")
        if event["id"] in expected and expected[event["id"]] != reference:
            raise SystemExit("STOP: conflicting source event identity")
        expected[event["id"]] = reference

if not expected:
    raise SystemExit("STOP: no matching confirmed journal event")

matches = []
for seq, raw in audits:
    row = json.loads(raw)
    for reference in row.get("source_event_references", []):
        stamp = reference.get("signal_at")
        if not stamp or datetime.fromisoformat(stamp) != boundary:
            continue
        if expected.get(reference.get("signal_id")) != reference:
            raise SystemExit("STOP: audit reference does not match journal")
        matches.append({
            "audit_sequence": seq,
            "recorded_at": row.get("at"),
            "status": row.get("status"),
            "reasons": row.get("reasons"),
            "signal_id": reference["signal_id"],
            "source_sequence": reference["source_sequence"],
        })

linked = {m["signal_id"] for m in matches}
complete = linked == set(expected)
print(json.dumps({
    "status": (
        "LIVE_SIGNAL_AUDIT_LINKAGE_VERIFIED" if complete
        else "LIVE_SIGNAL_AUDIT_LINKAGE_INCOMPLETE"
    ),
    "signal_boundary": boundary.isoformat(),
    "confirmed_source_event_count": len(expected),
    "linked_source_event_count": len(linked),
    "matching_audit_records": matches,
    "scope": "JOURNAL_TO_PREPARATION_AUDIT_REFERENCES_ONLY",
    "dispatch_or_fill_verified": False,
    "signal_replayed": False,
    "database_modified": False,
    "broker_reads_performed": False,
    "orders_sent": False,
    "production_execution_enabled": False,
}, indent=2))
raise SystemExit(0 if complete else 1)