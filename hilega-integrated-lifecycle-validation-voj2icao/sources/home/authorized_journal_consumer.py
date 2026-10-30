"""Durable synthetic journal consumer. No live account support."""
from contextlib import contextmanager
import fcntl
import hmac
import json
import os
from pathlib import Path

from authorized_event_dispatcher import dispatch_journal_record
from market_lab.hilega_execution_port_v1.adapter import Store
from market_lab.hilega_production_account_adapter_v1 import sign
from market_lab.hilega_production_simulator_bridge_v1 import verified_records


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


class AuthorizedFixtureConsumer:
    def __init__(self, application, closed_adapter, execution, pin, journal, *, adapter_module, clock):
        need(pin["scope"].startswith("FIXTURE:"), "SYNTHETIC_ACCOUNT_REQUIRED")
        need(type(execution) is adapter_module.Store and execution.mode == "OFFLINE_FIXTURE"
             and execution.scope == pin["scope"], "EXACT_FIXTURE_STORE_REQUIRED")
        self.adapter_module = adapter_module
        self.clock = clock
        self.app = application
        self.closed = closed_adapter
        self.execution = execution
        self.pin = dict(pin)
        self.journal = Path(journal).resolve()

    @contextmanager
    def lock(self):
        path = str(self.execution.path) + ".journal-consumer.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def encode(self, sequence, fingerprint):
        value = dict(
            model="HILEGA_FIXTURE_DISPATCH_CURSOR_V1",
            account_scope=self.pin["scope"],
            journal=str(self.journal),
            sequence=sequence, record_hash=fingerprint,
        )
        value["signature"] = sign(value, self.pin)
        return json.dumps(value, sort_keys=True)

    def cursor(self):
        with self.execution.tx() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fixture_dispatch_cursor("
                "id INTEGER PRIMARY KEY,data TEXT NOT NULL)")
            row = db.execute(
                "SELECT data FROM fixture_dispatch_cursor WHERE id=1"
            ).fetchone()
            if row is None:
                raw = self.encode(0, None)
                db.execute(
                    "INSERT INTO fixture_dispatch_cursor VALUES(1,?)", (raw,))
            else:
                raw = row[0]
        value = json.loads(raw)
        signature = value.pop("signature", None)
        need(isinstance(signature, str)
             and hmac.compare_digest(sign(value, self.pin), signature),
             "CURSOR_SIGNATURE_INVALID")
        need(value["model"] == "HILEGA_FIXTURE_DISPATCH_CURSOR_V1"
             and value["account_scope"] == self.pin["scope"]
             and value["journal"] == str(self.journal),
             "CURSOR_SCOPE_OR_JOURNAL_MISMATCH")
        return value, raw

    def poll(self, *, as_of, checkpoint=lambda stage: None):
        with self.lock():
            records = verified_records(self.journal)
            cursor, previous_raw = self.cursor()
            sequence = cursor["sequence"]
            need(type(sequence) is int and 0 <= sequence <= len(records),
                 "SOURCE_TRUNCATED_OR_CURSOR_INVALID")
            need((sequence == 0 and cursor["record_hash"] is None)
                 or (sequence > 0 and
                     records[sequence-1]["record_hash"] == cursor["record_hash"]),
                 "SOURCE_PREFIX_CHANGED")
            processed = 0
            for record in records[sequence:]:
                result = dispatch_journal_record(
                    self.app, self.closed, self.execution, self.pin,
                    self.journal, sequence=record["sequence"], as_of=as_of,
                    adapter_module=self.adapter_module, clock=self.clock,
                )
                checkpoint("AFTER_DISPATCH_BEFORE_CURSOR")
                # Do not checkpoint a replaced/truncated source prefix.
                current = verified_records(self.journal)
                n = record["sequence"]
                need(len(current) >= n
                     and current[n-1]["record_hash"] == record["record_hash"],
                     "SOURCE_CHANGED_BEFORE_CURSOR")
                next_raw = self.encode(n, record["record_hash"])
                with self.execution.tx() as db:
                    saved = db.execute(
                        "SELECT data FROM fixture_dispatch_cursor WHERE id=1"
                    ).fetchone()[0]
                    need(saved == previous_raw, "CURSOR_CHANGED")
                    db.execute(
                        "UPDATE fixture_dispatch_cursor SET data=? WHERE id=1",
                        (next_raw,),
                    )
                previous_raw = next_raw
                sequence = n
                processed += 1
            return dict(
                processed_record_count=processed,
                cursor_sequence=sequence,
                scope="SYNTHETIC_FIXTURE_ONLY",
                production_runtime_integrated=False,
                orders_sent_to_upstox=False,
                production_execution_enabled=False,
            )