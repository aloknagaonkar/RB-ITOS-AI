
from contextlib import closing
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

STAGE = Path(__file__).resolve().parent
ROOT = STAGE.parent
BASELINE = json.loads((STAGE / "baseline.json").read_text())
CANDIDATE = STAGE / "ownership_state.py"
INSTALLED = ROOT / (
    "backend/market_lab/hilega_preparation_runtime_v1/ownership_state.py"
)
PRODUCER = ROOT / "hilega-ownership-producer-tools-v1"

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

if digest(INSTALLED.read_bytes()) != BASELINE["installed_sha256"]:
    raise SystemExit("STOP: installed writer changed")
if digest(CANDIDATE.read_bytes()) != BASELINE["candidate_sha256"]:
    raise SystemExit("STOP: staged candidate changed")

sys.path.insert(0, str(PRODUCER))
import test_ownership_state as fixtures

namespace = "_hilega_capture_archive_candidate"
package = ModuleType(namespace)
package.__path__ = [
    str(STAGE),
    str(INSTALLED.parent),
]
sys.modules[namespace] = package
m = importlib.import_module(namespace + ".ownership_state")
assert Path(m.__file__).resolve() == CANDIDATE.resolve()

TABLE = "preparation_account_captures"

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.RuntimeRecordTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.app = self.fx.f.app
        self.broker = self.fx.f.adapter
        self.pin = self.fx.pin
        self.snapshot = deepcopy(self.fx.snapshot)
        self.assertTrue(self.pin["scope"].startswith("FIXTURE:"))
        self.assertNotEqual(
            self.app.resolve(),
            ROOT / "data/research/hilega-production-workspace/sim.sqlite",
        )
        network = patch(
            "socket.socket.connect",
            side_effect=AssertionError("NO_NETWORK_IN_TESTS"),
        )
        network.start()
        self.addCleanup(network.stop)

    def record(self, snapshot=None, **kwargs):
        return m.record_entry_review(
            self.app, self.broker,
            self.snapshot if snapshot is None else snapshot,
            self.pin, mode="OFFLINE_FIXTURE",
            clock=lambda: self.fx.now, **kwargs,
        )

    def current(self):
        with closing(sqlite3.connect(self.app)) as db:
            return m.current_row(db, self.pin, "OFFLINE_FIXTURE")

    def count(self, table):
        with closing(sqlite3.connect(self.app)) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            return (
                db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                if exists else 0
            )

    def archived(self, sid=None):
        sid = sid or self.snapshot["snapshot_id"]
        with closing(sqlite3.connect(self.app)) as db:
            return db.execute(
                "SELECT fingerprint,data FROM " + TABLE + " WHERE id=?",
                (sid,),
            ).fetchone()

    def signed(self, snapshot):
        snapshot.pop("signature", None)
        snapshot["signature"] = m.sign(snapshot, self.pin)
        return snapshot

    def test_capture_payload_and_fingerprint_preserved(self):
        self.record()
        fingerprint, raw = self.archived()
        self.assertEqual(json.loads(raw), self.snapshot)
        self.assertEqual(fingerprint, m.sha(self.snapshot))
        self.assertTrue(self.current()["raw_account_capture_persisted"])

    def test_exact_replay_does_not_duplicate(self):
        self.record()
        result = self.record()
        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(self.count(TABLE), 1)
        self.assertEqual(self.count(m.HISTORY), 1)

    def test_existing_history_is_preserved(self):
        self.fx.record()
        old_id = self.snapshot["snapshot_id"]
        with closing(sqlite3.connect(self.app)) as db:
            before = db.execute(
                "SELECT data FROM " + m.HISTORY + " WHERE id=?", (old_id,)
            ).fetchone()[0]
        fresh = deepcopy(self.snapshot)
        fresh["snapshot_id"] = "new-archive-observation"
        self.record(self.signed(fresh))
        with closing(sqlite3.connect(self.app)) as db:
            after = db.execute(
                "SELECT data FROM " + m.HISTORY + " WHERE id=?", (old_id,)
            ).fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(self.count(m.HISTORY), 2)
        self.assertEqual(self.count(TABLE), 1)

    def test_bad_signature_is_not_archived(self):
        bad = deepcopy(self.snapshot)
        bad["snapshot_id"] = "tampered"
        self.record(bad)
        self.assertEqual(self.count(TABLE), 0)
        self.assertEqual(self.current()["status"], "BLOCKED")
        self.assertFalse(self.current()["raw_account_capture_persisted"])

    def test_local_failure_event_is_not_broker_evidence(self):
        self.record({
            "model": "HILEGA_OWNERSHIP_PRODUCER_FAILURE_V1",
            "snapshot_id": "local-failure",
        })
        self.assertEqual(self.count(TABLE), 0)
        self.assertEqual(self.current()["status"], "BLOCKED")

    def test_reused_id_cannot_overwrite_capture(self):
        self.record()
        before = self.archived()
        changed = deepcopy(self.snapshot)
        changed["positions"][0]["quantity"] = 0
        self.record(self.signed(changed))
        self.assertEqual(before, self.archived())
        self.assertEqual(self.current()["status"], "BLOCKED")

    def test_archive_and_state_roll_back_together(self):
        self.record()
        previous = self.current()
        fresh = deepcopy(self.snapshot)
        fresh["snapshot_id"] = "interrupted-capture"
        self.signed(fresh)
        class Interrupted(BaseException):
            pass
        def stop(point):
            if point == "AFTER_OWNERSHIP_HISTORY_INSERT":
                raise Interrupted()
        with self.assertRaises(Interrupted):
            self.record(fresh, checkpoint=stop)
        self.assertEqual(self.current(), previous)
        self.assertEqual(self.count(TABLE), 1)
        self.assertEqual(self.count(m.HISTORY), 1)

    def test_first_interruption_leaves_no_archive(self):
        class Interrupted(BaseException):
            pass
        def stop(point):
            if point == "BEFORE_OWNERSHIP_COMMIT":
                raise Interrupted()
        with self.assertRaises(Interrupted):
            self.record(checkpoint=stop)
        self.assertEqual(self.count(TABLE), 0)
        self.assertEqual(self.count(m.CURRENT), 0)

    def test_archive_conflict_blocks_without_overwrite(self):
        with closing(sqlite3.connect(self.app)) as db, db:
            db.execute(
                "CREATE TABLE " + TABLE +
                "(id TEXT PRIMARY KEY,fingerprint TEXT,data TEXT)"
            )
            db.execute(
                "INSERT INTO " + TABLE + " VALUES(?,?,?)",
                (self.snapshot["snapshot_id"], "wrong", "{}"),
            )
        before = self.archived()
        self.record()
        self.assertEqual(before, self.archived())
        self.assertEqual(self.current()["status"], "BLOCKED")
        self.assertIn(
            "CAPTURE_ARCHIVE_ID_CONFLICT", self.current()["reasons"]
        )

    def test_empty_account_is_evidence_not_zero_strategy_pnl(self):
        empty = deepcopy(self.snapshot)
        empty.update(orders=[], trades=[], positions=[])
        self.record(self.signed(empty))
        self.assertEqual(self.count(TABLE), 1)
        row = self.current()
        self.assertEqual(row["status"], "BLOCKED")
        self.assertTrue(row["raw_account_capture_persisted"])
        self.assertIsNone(row["reviewed_entry_quantity"])
        self.assertIsNone(row["realized_net_pnl_paise"])

    def test_partial_fill_is_archived_without_exit_permission(self):
        partial = deepcopy(self.snapshot)
        partial["orders"][0].update(
            filled=30, pending=35, status="PARTIAL"
        )
        partial["trades"][0]["quantity"] = 30
        partial["positions"][0]["quantity"] = 30
        self.record(self.signed(partial))
        self.assertEqual(self.count(TABLE), 1)
        self.assertEqual(self.current()["status"], "BLOCKED")
        self.assertFalse(self.current()["exit_submission_permission"])

    def test_malformed_fill_rows_are_not_archived(self):
        bad = deepcopy(self.snapshot)
        bad["trades"][0]["quantity"] = True
        self.record(self.signed(bad))
        self.assertEqual(self.count(TABLE), 0)
        self.assertEqual(self.current()["status"], "BLOCKED")

    def test_broker_and_cash_reservation_are_unchanged(self):
        broker_before = self.broker.read_bytes()
        cash_before = self.fx.f.get(
            self.app, "preparation_cash_reservations", "p1"
        )
        self.record()
        self.assertEqual(broker_before, self.broker.read_bytes())
        self.assertEqual(
            cash_before,
            self.fx.f.get(self.app, "preparation_cash_reservations", "p1"),
        )

    def test_direct_archive_requires_existing_transaction(self):
        with closing(sqlite3.connect(self.app)) as db:
            with self.assertRaisesRegex(
                ValueError, "CAPTURE_ARCHIVE_TRANSACTION_REQUIRED"
            ):
                m.archive_authenticated_capture(
                    db, self.snapshot, self.pin,
                    as_of=self.fx.now.isoformat(),
                )
        self.assertEqual(self.count(TABLE), 0)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ArchiveTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    unchanged = digest(INSTALLED.read_bytes()) == BASELINE["installed_sha256"]
    report = {
        "status": (
            "STAGED_CAPTURE_ARCHIVE_TESTS_PASS"
            if result.wasSuccessful() and unchanged else "FAIL"
        ),
        "tests_run": result.testsRun,
        "candidate_sha256": digest(CANDIDATE.read_bytes()),
        "installed_writer_unchanged": unchanged,
        "production_database_accessed": False,
        "applied": False,
        "services_restarted": False,
        "orders_sent": False,
        "production_execution_enabled": False,
        "reservation_release_permission": False,
        "production_ready": False,
    }
    (STAGE / "VALIDATION.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))
    raise SystemExit(
        0 if report["status"] == "STAGED_CAPTURE_ARCHIVE_TESTS_PASS" else 1
    )
