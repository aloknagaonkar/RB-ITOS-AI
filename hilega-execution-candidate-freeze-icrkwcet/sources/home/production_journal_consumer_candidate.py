"""Durable candidate journal cursor. No activation or gate override."""
from contextlib import contextmanager
import fcntl
import hmac
import json
import os
from pathlib import Path
import re

from market_lab.hilega_production_account_adapter_v1 import sign
from market_lab.hilega_production_simulator_bridge_v1 import verified_records

TABLE = "production_candidate_journal_cursor"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


class ProductionJournalConsumerCandidate:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.store = coordinator.adapter.store
        self.pin = dict(coordinator.pin)
        self.journal = Path(coordinator.journal).absolute()
        need(self.store.mode == "LIVE_CLOSED"
             and self.store.scope == self.pin["scope"]
             and re.fullmatch(r"UPSTOX:[0-9a-f]{64}", self.pin["scope"]) is not None,
             "EXACT_LIVE_CLOSED_SCOPE_REQUIRED")

    @contextmanager
    def lock(self):
        fd = os.open(
            str(self.store.path) + ".execution-cursor.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def encode(self, sequence, fingerprint):
        row = dict(
            model="HILEGA_PRODUCTION_CANDIDATE_JOURNAL_CURSOR_V1",
            account_scope=self.pin["scope"], journal=str(self.journal),
            sequence=sequence, record_hash=fingerprint,
            production_execution_enabled=False,
        )
        row["signature"] = sign(row, self.pin)
        return json.dumps(row, sort_keys=True)

    def authenticate(self, raw):
        row = json.loads(raw)
        signed = row.pop("signature", None)
        need(isinstance(signed, str)
             and hmac.compare_digest(sign(row, self.pin), signed),
             "CURSOR_SIGNATURE_INVALID")
        need(row["model"] == "HILEGA_PRODUCTION_CANDIDATE_JOURNAL_CURSOR_V1"
             and row["account_scope"] == self.pin["scope"]
             and row["journal"] == str(self.journal)
             and row["production_execution_enabled"] is False,
             "CURSOR_SCOPE_OR_AUTHORITY_INVALID")
        return row

    def safe_to_advance(self, sequence, result):
        if result["status"] == "NO_CONFIRMED_EXECUTION_EVENT":
            return True
        allowed = {
            "CANDIDATE_ENTRY_ATTEMPT_RECORDED",
            "CANDIDATE_EXIT_ATTEMPT_RECORDED",
            "EXISTING_ENTRY_RECOVERED_NO_SUBMISSION",
            "EXISTING_EXIT_RECOVERED_NO_SUBMISSION",
        }
        if result["status"] not in allowed:
            return False
        event = self.coordinator.event(sequence)
        rows = [r for r in self.store.requests()
                if r["signal_id"] == event["id"]]
        return (
            len(rows) == 1 and rows[0].get("order_id") is not None
            and rows[0]["state"] in {
                "ACKNOWLEDGED_NOT_FILLED", "RECONCILIATION_REQUIRED",
            }
        )

    def poll(self, *, checkpoint=lambda stage: None):
        with self.lock():
            records = verified_records(self.journal)
            with self.store.tx() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS " + TABLE +
                    "(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)")
                found = db.execute(
                    "SELECT data FROM " + TABLE + " WHERE id=1").fetchone()
                if found is None:
                    raw = self.encode(
                        len(records), records[-1]["record_hash"] if records else None)
                    db.execute("INSERT INTO " + TABLE + " VALUES(1,?)", (raw,))
                    return dict(
                        status="BASELINED_WAIT_NEXT_FRESH_SIGNAL",
                        cursor_sequence=len(records), processed_record_count=0,
                        production_execution_enabled=False,
                    )
                previous_raw = found[0]
            cursor = self.authenticate(previous_raw)
            sequence = cursor["sequence"]
            need(type(sequence) is int and 0 <= sequence <= len(records),
                 "JOURNAL_TRUNCATED_OR_CURSOR_INVALID")
            need((sequence == 0 and cursor["record_hash"] is None)
                 or (sequence > 0 and
                     records[sequence-1]["record_hash"] == cursor["record_hash"]),
                 "JOURNAL_PREFIX_CHANGED")
            processed = 0
            for record in records[sequence:]:
                n = record["sequence"]
                result = self.coordinator.dispatch(n)
                if not self.safe_to_advance(n, result):
                    return dict(
                        status="CURSOR_HELD_FOR_RECONCILIATION",
                        execution_status=result["status"],
                        cursor_sequence=sequence,
                        processed_record_count=processed,
                        production_execution_enabled=False,
                    )
                checkpoint("AFTER_DISPATCH_BEFORE_CURSOR")
                current = verified_records(self.journal)
                need(len(current) >= n
                     and current[n-1]["record_hash"] == record["record_hash"],
                     "JOURNAL_CHANGED_BEFORE_CURSOR")
                next_raw = self.encode(n, record["record_hash"])
                with self.store.tx() as db:
                    saved = db.execute(
                        "SELECT data FROM " + TABLE + " WHERE id=1"
                    ).fetchone()[0]
                    need(saved == previous_raw, "CURSOR_CHANGED")
                    db.execute(
                        "UPDATE " + TABLE + " SET data=? WHERE id=1",
                        (next_raw,))
                previous_raw, sequence = next_raw, n
                processed += 1
            return dict(
                status="CANDIDATE_JOURNAL_PROCESSED",
                cursor_sequence=sequence, processed_record_count=processed,
                production_execution_enabled=False,
            )
