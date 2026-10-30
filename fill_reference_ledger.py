from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import timezone
from decimal import Decimal
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest

ROOT = Path.cwd().resolve()
SCRIPT = Path(__file__).resolve()
CHECKER = Path.home() / "fill_history_check.py"
MODEL = "HILEGA_STAGED_ACCOUNT_FILL_REFERENCES_V1"
FLAGS = (
    "orders_sent", "production_execution_enabled",
    "entry_permission", "exit_submission_permission",
    "reservation_release_permission", "strategy_ownership_verified",
    "production_ready",
)
C = None


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_reason(exc):
    text = str(exc)
    return (
        text if text and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                             for c in text)
        else "REFERENCE_REVIEW_FAILED"
    )


def load_checker():
    global C
    need(CHECKER.is_file() and not CHECKER.is_symlink(),
         "CHECKER_FILE_REQUIRED")
    spec = importlib.util.spec_from_file_location(
        "verified_fill_history_checker", CHECKER
    )
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)
    C.load_validators()


class Ledger:
    def __init__(self, path, pin, *, fixture=False, create=False):
        self.path = Path(path).absolute()
        self.pin = deepcopy(pin)
        self.fixture = fixture
        self.mode = "STAGED_FIXTURE" if fixture else "STAGED_LIVE_ACCOUNT"
        need(
            pin["scope"].startswith("FIXTURE:") if fixture
            else pin["scope"].startswith("UPSTOX:"),
            "LEDGER_SCOPE_INVALID",
        )
        need(
            not self.path.is_symlink()
            and not any(p.is_symlink() for p in self.path.parents),
            "LEDGER_SYMLINK_FORBIDDEN",
        )
        parent = self.path.parent.stat()
        need(
            parent.st_uid == os.getuid()
            and stat.S_IMODE(parent.st_mode) & 0o077 == 0,
            "PRIVATE_LEDGER_DIRECTORY_REQUIRED",
        )
        if create:
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            os.close(fd)
            with self.db() as db:
                for sql in (
                    "CREATE TABLE ledger_meta(id INTEGER PRIMARY KEY,data TEXT)",
                    "CREATE TABLE capture_refs(id TEXT PRIMARY KEY,fp TEXT,data TEXT)",
                    "CREATE TABLE fill_refs(id TEXT PRIMARY KEY,fp TEXT,data TEXT)",
                    "CREATE TABLE current_state(id INTEGER PRIMARY KEY,data TEXT)",
                    "CREATE TABLE reviews(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT)",
                ):
                    db.execute(sql)
                value = self.seal("META", {})
                db.execute(
                    "INSERT INTO ledger_meta VALUES(1,?)",
                    (json.dumps(value, sort_keys=True),),
                )
        else:
            need(self.path.is_file(), "EXISTING_LEDGER_REQUIRED")
            info = self.path.stat()
            need(
                info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                "PRIVATE_LEDGER_FILE_REQUIRED",
            )
            with self.db() as db:
                self.load(db)

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, timeout=10
        )) as db:
            need(db.execute("PRAGMA journal_mode").fetchone()[0] == "delete",
                 "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def seal(self, kind, values):
        row = dict(values)
        row.update(
            model=MODEL, kind=kind, mode=self.mode,
            account_scope=self.pin["scope"],
            tool_sha256=sha_file(SCRIPT),
            checker_sha256=sha_file(CHECKER),
            **{name: False for name in FLAGS},
        )
        row["signature"] = C.M.sign(row, self.pin)
        return row

    def verify(self, raw, kind):
        row = json.loads(raw)
        payload = dict(row)
        signature = payload.pop("signature", None)
        need(
            isinstance(signature, str)
            and hmac.compare_digest(C.M.sign(payload, self.pin), signature),
            "LEDGER_SIGNATURE_INVALID",
        )
        need(
            row["model"] == MODEL and row["kind"] == kind
            and row["mode"] == self.mode
            and row["account_scope"] == self.pin["scope"]
            and row["tool_sha256"] == sha_file(SCRIPT)
            and row["checker_sha256"] == sha_file(CHECKER)
            and all(row.get(name) is False for name in FLAGS),
            "LEDGER_SCOPE_VERSION_OR_AUTHORITY_CHANGED",
        )
        return row

    def load(self, db):
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='ledger_meta'"
        ).fetchone()
        need(exists, "STAGING_LEDGER_MARKER_REQUIRED")
        meta = db.execute(
            "SELECT data FROM ledger_meta WHERE id=1"
        ).fetchone()
        need(meta is not None, "STAGING_LEDGER_MARKER_REQUIRED")
        self.verify(meta[0], "META")

        captures, fills = [], {}
        for sid, fp, raw in db.execute(
            "SELECT id,fp,data FROM capture_refs ORDER BY rowid"
        ):
            row = self.verify(raw, "CAPTURE")
            need(row["capture_id"] == sid and row["capture_fp"] == fp,
                 "CAPTURE_REFERENCE_CHANGED")
            captures.append((sid, fp))

        for key, fp, raw in db.execute(
            "SELECT id,fp,data FROM fill_refs"
        ):
            row = self.verify(raw, "FILL")
            facts = row["facts"]
            expected_key = C.M.sha([
                self.pin["scope"], facts["session_date"],
                facts["order_id"], facts["trade_id"],
            ])
            need(
                key == expected_key and C.M.sha(facts) == fp,
                "FILL_REFERENCE_CHANGED",
            )
            fills[key] = (fp, row)

        reviews = db.execute(
            "SELECT seq,data FROM reviews ORDER BY seq"
        ).fetchall()
        for index, (seq, raw) in enumerate(reviews, 1):
            row = self.verify(raw, "STATE")
            need(seq == index == row["review_count"],
                 "REVIEW_SEQUENCE_CHANGED")

        current = db.execute(
            "SELECT data FROM current_state WHERE id=1"
        ).fetchone()
        state = self.verify(current[0], "STATE") if current else None
        if state:
            need(
                state["capture_count"] == len(captures)
                and state["fill_count"] == len(fills)
                and state["review_count"] == len(reviews)
                and state["prefix_fp"] == C.M.sha(captures)
                and reviews[-1][1] == current[0],
                "LEDGER_COUNTS_OR_CURRENT_STATE_CHANGED",
            )
        else:
            need(not captures and not fills and not reviews,
                 "LEDGER_CURRENT_STATE_MISSING")
        return captures, fills, reviews, state

    def public(self, state, *, changed, replay=False):
        return {
            "status": "STAGED_REFERENCE_LEDGER_VERIFIED",
            "replay_status": state["report"]["status"],
            "review_reasons": state["report"].get("review_reasons", []),
            "capture_reference_count": state["capture_count"],
            "unique_fill_reference_count": state["fill_count"],
            "review_count": state["review_count"],
            "idempotent_replay": replay,
            "staging_ledger_modified": changed,
            "staging_ledger_persisted": True,
            "staging_ledger_path": str(self.path),
            "production_ledger_integrated": False,
            "production_database_modified": False,
            "verified_owned_quantity": None,
            "positions_reconciled": False,
            "fees_complete": False,
            "realized_net_pnl_paise": None,
            "open_net_pnl_paise": None,
            **{name: False for name in FLAGS},
        }

    def save_state(self, db, captures, fills, reviews, report):
        state = self.seal("STATE", {
            "capture_count": len(captures),
            "fill_count": len(fills),
            "review_count": len(reviews) + 1,
            "prefix_fp": C.M.sha(captures),
            "report": report,
        })
        raw = json.dumps(state, sort_keys=True)
        db.execute("INSERT INTO reviews(data) VALUES(?)", (raw,))
        db.execute(
            "INSERT OR REPLACE INTO current_state VALUES(1,?)", (raw,)
        )
        return state

    def sync(self, source, *, checkpoint=lambda point: None):
        with self.db() as db:
            old_refs, old_fills, reviews, current = self.load(db)
            try:
                captures, size = [], 0
                for capture in source:
                    size += len(json.dumps(capture).encode())
                    need(len(captures) < 200 and size <= 32_000_000,
                         "SOURCE_BATCH_LIMIT_EXCEEDED")
                    captures.append(capture)

                report = C.replay(captures, self.pin, fixture=self.fixture)
                refs, new_fills, seen = [], {}, set()
                for capture in captures:
                    sid = capture["snapshot_id"]
                    if sid in seen:
                        continue
                    seen.add(sid)
                    refs.append((sid, C.M.sha(capture)))
                    for trade in capture["trades"]:
                        facts = {
                            name: trade[name] for name in (
                                "order_id", "trade_id", "instrument",
                                "product", "side", "quantity",
                            )
                        }
                        facts.update(
                            session_date=capture["session_date"],
                            price=str(Decimal(str(trade["price"])).normalize()),
                            filled_at=C.M.aware(
                                trade["filled_at"]
                            ).astimezone(timezone.utc).isoformat(),
                        )
                        key = C.M.sha([
                            self.pin["scope"], facts["session_date"],
                            facts["order_id"], facts["trade_id"],
                        ])
                        new_fills.setdefault(
                            key, (C.M.sha(facts), facts, sid)
                        )

                need(old_refs == refs[:len(old_refs)],
                     "ARCHIVE_PREFIX_CHANGED_OR_TRUNCATED")
                for key, (fp, row) in old_fills.items():
                    need(key in new_fills and new_fills[key][0] == fp,
                         "STORED_FILL_CHANGED_OR_REMOVED")
                need(report["unique_account_fill_count"] == len(new_fills),
                     "REPLAY_LEDGER_PARITY_FAILED")

            except Exception as exc:
                state = self.save_state(db, old_refs, old_fills, reviews, {
                    "status": "BLOCKED_REFERENCE_REVIEW_FAILED",
                    "review_reasons": [safe_reason(exc)],
                })
                checkpoint("BEFORE_COMMIT")
                return self.public(state, changed=True)

            if refs == old_refs and current is not None:
                return self.public(current, changed=False, replay=True)

            capture_map = {c["snapshot_id"]: c for c in captures}
            for sid, fp in refs[len(old_refs):]:
                capture = capture_map[sid]
                row = self.seal("CAPTURE", {
                    "capture_id": sid, "capture_fp": fp,
                    "session_date": capture["session_date"],
                })
                db.execute(
                    "INSERT INTO capture_refs VALUES(?,?,?)",
                    (sid, fp, json.dumps(row, sort_keys=True)),
                )
            checkpoint("AFTER_CAPTURE_REFERENCES")

            for key, (fp, facts, sid) in new_fills.items():
                if key not in old_fills:
                    row = self.seal("FILL", {
                        "facts": facts, "first_capture_id": sid,
                    })
                    db.execute(
                        "INSERT INTO fill_refs VALUES(?,?,?)",
                        (key, fp, json.dumps(row, sort_keys=True)),
                    )
            checkpoint("AFTER_FILL_REFERENCES")
            state = self.save_state(db, refs, new_fills, reviews, report)
            checkpoint("BEFORE_COMMIT")
            return self.public(state, changed=True)

    def status(self):
        with closing(sqlite3.connect(
            self.path.as_uri() + "?mode=ro", uri=True
        )) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            try:
                _, _, _, current = self.load(db)
                need(current is not None, "LEDGER_HAS_NO_REVIEW")
                return self.public(current, changed=False)
            finally:
                db.rollback()


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "references.sqlite"
        self.ledger = Ledger(self.path, C.PIN, fixture=True, create=True)

    def test_deduplicated_fills(self):
        result = self.ledger.sync([C.sample(), C.sample(4)])
        self.assertEqual(result["unique_fill_reference_count"], 1)
        self.assertEqual(result["capture_reference_count"], 2)

    def test_reopen_and_replay(self):
        captures = [C.sample(), C.sample(4)]
        self.ledger.sync(captures)
        reopened = Ledger(self.path, C.PIN, fixture=True)
        result = reopened.sync(captures)
        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["review_count"], 1)

    def test_changed_fill_blocks_without_removing_rows(self):
        self.ledger.sync([C.sample(quantity=30)])
        result = self.ledger.sync([
            C.sample(quantity=30), C.sample(4, quantity=31)
        ])
        self.assertEqual(result["replay_status"],
                         "BLOCKED_REFERENCE_REVIEW_FAILED")
        self.assertEqual(result["unique_fill_reference_count"], 1)

    def test_missing_fill_retained(self):
        self.ledger.sync([C.sample()])
        missing = C.sample(4)
        missing.update(orders=[], trades=[])
        result = self.ledger.sync([C.sample(), C.signed(missing)])
        self.assertEqual(result["replay_status"], "REVIEW_REQUIRED")
        self.assertEqual(result["unique_fill_reference_count"], 1)

    def test_prefix_truncation_blocks(self):
        self.ledger.sync([C.sample(), C.sample(4)])
        result = self.ledger.sync([C.sample()])
        self.assertEqual(result["capture_reference_count"], 2)
        self.assertEqual(result["replay_status"],
                         "BLOCKED_REFERENCE_REVIEW_FAILED")

    def test_old_replay_does_not_clear_block(self):
        captures = [C.sample(), C.sample(4)]
        self.ledger.sync(captures)
        self.ledger.sync([C.sample()])
        result = self.ledger.sync(captures)
        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["replay_status"],
                         "BLOCKED_REFERENCE_REVIEW_FAILED")

    def test_atomic_rollback(self):
        self.ledger.sync([C.sample()])
        class Interrupted(BaseException):
            pass
        def stop(point):
            if point == "BEFORE_COMMIT":
                raise Interrupted()
        with self.assertRaises(Interrupted):
            self.ledger.sync(
                [C.sample(), C.sample(4)], checkpoint=stop
            )
        result = self.ledger.status()
        self.assertEqual(result["capture_reference_count"], 1)
        self.assertEqual(result["review_count"], 1)

    def test_empty_account_is_inconclusive(self):
        empty = C.sample()
        empty.update(orders=[], trades=[], positions=[])
        result = self.ledger.sync([C.signed(empty)])
        self.assertEqual(result["replay_status"],
                         "INCONCLUSIVE_NO_ACCOUNT_FILLS")
        self.assertEqual(result["unique_fill_reference_count"], 0)
        self.assertIsNone(result["verified_owned_quantity"])

    def test_wrong_scope_rejected(self):
        with self.assertRaises(ValueError):
            Ledger(
                self.path, dict(C.PIN, scope="FIXTURE:OTHER"),
                fixture=True,
            )

    def test_tampered_fill_rejected(self):
        self.ledger.sync([C.sample()])
        with closing(sqlite3.connect(self.path)) as db, db:
            raw = db.execute("SELECT data FROM fill_refs").fetchone()[0]
            row = json.loads(raw)
            row["facts"]["quantity"] = 999
            db.execute(
                "UPDATE fill_refs SET data=?", (json.dumps(row),)
            )
        with self.assertRaises(ValueError):
            self.ledger.status()

    def test_unrelated_database_untouched(self):
        wrong = self.path.parent / "unrelated.sqlite"
        with closing(sqlite3.connect(wrong)) as db, db:
            db.execute("CREATE TABLE unrelated(id INTEGER)")
        before = wrong.read_bytes()
        with self.assertRaises(ValueError):
            Ledger(wrong, C.PIN, fixture=True)
        self.assertEqual(before, wrong.read_bytes())

    def test_inputs_unchanged(self):
        captures = [C.sample(), C.sample(4)]
        before = deepcopy(captures)
        self.ledger.sync(captures)
        self.assertEqual(before, captures)

    def test_first_interruption_rolls_back_references(self):
        class Interrupted(BaseException):
            pass
        def stop(point):
            if point == "AFTER_CAPTURE_REFERENCES":
                raise Interrupted()
        with self.assertRaises(Interrupted):
            self.ledger.sync([C.sample()], checkpoint=stop)
        result = self.ledger.sync([C.sample()])
        self.assertEqual(result["capture_reference_count"], 1)
        self.assertEqual(result["review_count"], 1)

    def test_new_capture_can_follow_failed_review(self):
        self.ledger.sync([C.sample()])
        self.ledger.sync([])
        result = self.ledger.sync([C.sample(), C.sample(4)])
        self.assertEqual(result["replay_status"],
                         "ACCOUNT_FILL_REFERENCE_CHECKS_PASS")
        self.assertFalse(result["strategy_ownership_verified"])

    def test_partial_to_full_preserves_both_fills(self):
        first = C.sample(quantity=30)
        second = C.sample(4)
        second["trades"][0]["quantity"] = 30
        extra = deepcopy(second["trades"][0])
        extra.update(trade_id="fill-B", quantity=35)
        second["trades"].append(extra)
        result = self.ledger.sync([first, C.signed(second)])
        self.assertEqual(result["unique_fill_reference_count"], 2)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["selftest", "stage"])
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    load_checker()
    proof_path = SCRIPT.with_suffix(".validation.json")

    if args.action == "selftest":
        runner = unittest.TextTestRunner(verbosity=2)
        a = runner.run(
            unittest.defaultTestLoader.loadTestsFromTestCase(C.ReplayTests)
        )
        b = runner.run(
            unittest.defaultTestLoader.loadTestsFromTestCase(LedgerTests)
        )
        passed = (
            a.wasSuccessful() and b.wasSuccessful()
            and a.testsRun == 16 and b.testsRun == 15
        )
        proof = {
            "status": "FILL_REFERENCE_LEDGER_SELFTEST_PASS" if passed else "FAIL",
            "checker_tests": a.testsRun,
            "ledger_tests": b.testsRun,
            "tool_sha256": sha_file(SCRIPT),
            "checker_sha256": sha_file(CHECKER),
            "production_database_modified": False,
            "orders_sent": False,
            "production_execution_enabled": False,
            "production_ready": False,
        }
        proof_path.write_text(json.dumps(proof, indent=2) + "\n")
        print(json.dumps(proof, indent=2))
        return 0 if passed else 1

    proof = json.loads(proof_path.read_text())
    need(
        proof["status"] == "FILL_REFERENCE_LEDGER_SELFTEST_PASS"
        and proof["tool_sha256"] == sha_file(SCRIPT)
        and proof["checker_sha256"] == sha_file(CHECKER),
        "MATCHING_SELFTEST_PROOF_REQUIRED",
    )
    from market_lab.hilega_production_account_adapter_v1 import read_pin
    pin = read_pin(
        Path.home() / "hilega-private/upstox-account-pin.json"
    )
    research = ROOT / "data/research"
    need(research.is_dir() and not research.is_symlink(),
         "REGULAR_RESEARCH_DIRECTORY_REQUIRED")

    if args.ledger:
        path = args.ledger.absolute()
        need(
            path.parent.parent == research
            and path.parent.name.startswith("hilega-fill-ledger-stage-")
            and path.name == "references.sqlite",
            "STAGING_LEDGER_PATH_REQUIRED",
        )
        ledger = Ledger(path, pin)
    else:
        folder = Path(tempfile.mkdtemp(
            prefix="hilega-fill-ledger-stage-", dir=research
        ))
        ledger = Ledger(folder / "references.sqlite", pin, create=True)

    app = ROOT / "data/research/hilega-production-workspace/sim.sqlite"
    with closing(C.archive_captures(app)) as captures:
        result = ledger.sync(captures)
    verified = ledger.status()
    result["signed_readback_verified"] = True
    need(
        result["capture_reference_count"]
        == verified["capture_reference_count"]
        and result["unique_fill_reference_count"]
        == verified["unique_fill_reference_count"],
        "LEDGER_READBACK_CHANGED",
    )
    print(json.dumps(result, indent=2))
    return 1 if result["replay_status"] in {
        "REVIEW_REQUIRED", "BLOCKED_REFERENCE_REVIEW_FAILED"
    } else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({
            "status": "STAGED_LEDGER_STOPPED_FOR_REVIEW",
            "reason": safe_reason(exc),
            "production_database_modified": False,
            "orders_sent": False,
            "production_execution_enabled": False,
            "reservation_release_permission": False,
            "production_ready": False,
        }, indent=2))
        raise SystemExit(1)