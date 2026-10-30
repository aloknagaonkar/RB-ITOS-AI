from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import unittest

ROOT = Path.cwd().resolve()
M = None
VALIDATE_ROWS = None
WRITER_SHA = "7cc48fb3422bae9a86a2e2fa7d0d143ffbbfa7cabfab248c3b9ee8b14f084041"
MANIFEST_SHA = "09ac943ec667024266520a6382cffa75d02d6f7939222e95a0894cd305ef4857"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def file_sha(path):
    need(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    need(not any(p.is_symlink() for p in path.parents),
         "SYMLINK_PARENT_FORBIDDEN")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_validators():
    global M, VALIDATE_ROWS
    folder = ROOT / "hilega-ownership-producer-tools-v1"
    manifest_path = folder / "manifest.json"
    need(file_sha(manifest_path) == MANIFEST_SHA,
         "PRODUCER_MANIFEST_CHANGED")
    manifest = json.loads(manifest_path.read_text())
    for parent, items in (
        (folder, manifest["package_sha256"]),
        (ROOT, manifest["installed_source_sha256"]),
    ):
        for name, expected in items.items():
            need(file_sha(parent / name) == expected,
                 "PACKAGE_OR_INSTALLED_SOURCE_CHANGED")
    writer = ROOT / (
        "backend/market_lab/hilega_preparation_runtime_v1/"
        "ownership_state.py"
    )
    need(file_sha(writer) == WRITER_SHA, "WRITER_VERSION_CHANGED")
    sys.path.insert(0, str(ROOT / "backend"))
    from market_lab.hilega_preparation_runtime_v1 import ownership_state
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge \
        import validate_account_rows
    M = ownership_state
    VALIDATE_ROWS = validate_account_rows


def replay(captures, pin, *, fixture=False):
    if fixture:
        need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_SCOPE_REQUIRED")
    else:
        need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
             "LIVE_PIN_SCOPE_REQUIRED")

    seen_captures, fills, orders = {}, {}, {}
    previous_fills = {}
    sessions, reasons = set(), set()
    duplicates = duplicate_captures = 0
    last_generated = None

    for capture in captures:
        sid = capture.get("snapshot_id")
        need(isinstance(sid, str) and 0 < len(sid) <= 200,
             "CAPTURE_ID_INVALID")
        fingerprint = M.sha(capture)
        if sid in seen_captures:
            need(seen_captures[sid] == fingerprint, "CAPTURE_ID_REUSED")
            duplicate_captures += 1
            continue

        M.verify(capture, pin, as_of=capture["completed_at"])
        need(
            capture.get("profile_verified_before_and_after") is True
            and capture.get("account_position_rows_complete") is True
            and capture.get("source_atomic") is False
            and capture.get("position_fill_linkage_verified") is False
            and capture.get("live_pnl") is None,
            "CAPTURE_COMPLETENESS_OR_AUTHORITY_INVALID",
        )
        start = M.aware(capture["generated_at"])
        end = M.aware(capture["completed_at"])
        session = capture["session_date"]
        need(M.day(start) == M.day(end) == session,
             "CAPTURE_SESSION_INVALID")
        if not fixture:
            need(end <= datetime.now(timezone.utc),
                 "CAPTURE_TIMESTAMP_IN_FUTURE")
        need(last_generated is None or start >= last_generated,
             "CAPTURE_TIME_REGRESSION")
        last_generated = start

        current_orders, _ = VALIDATE_ROWS(capture)
        seen_captures[sid] = fingerprint
        sessions.add(session)
        need(len(seen_captures) <= 1000, "CAPTURE_LIMIT_REQUIRES_BATCHING")

        for oid, order in current_orders.items():
            key = session, oid
            old = orders.get(key)
            if old:
                need(all(old[k] == order[k] for k in
                         ("instrument", "product", "side")),
                     "ORDER_CONTRACT_CHANGED")
                need(order["filled"] >= old["filled"],
                     "CUMULATIVE_FILL_REGRESSION")
                if old["quantity"] != order["quantity"]:
                    reasons.add("ORDER_QUANTITY_CHANGE_REQUIRES_REVIEW")
                if old["status"] in {"FILLED", "CANCELLED", "REJECTED"}:
                    need(order["status"] == old["status"],
                         "TERMINAL_ORDER_STATE_CHANGED")
            orders[key] = dict(order)

        current_keys = set()
        for trade in capture["trades"]:
            key = session, trade["order_id"], trade["trade_id"]
            normalized = (
                trade["instrument"], trade["product"], trade["side"],
                trade["quantity"],
                str(Decimal(str(trade["price"])).normalize()),
                M.aware(trade["filled_at"]).astimezone(
                    timezone.utc
                ).isoformat(),
            )
            current_keys.add(key)
            if key in fills:
                need(fills[key] == normalized, "IMMUTABLE_FILL_CHANGED")
                duplicates += 1
            else:
                fills[key] = normalized

        if previous_fills.get(session, set()) - current_keys:
            reasons.add("PREVIOUS_FILL_NOT_VISIBLE_IN_LATER_CAPTURE")
        previous_fills[session] = (
            previous_fills.get(session, set()) | current_keys
        )
        need(len(fills) <= 100000 and len(orders) <= 100000,
             "HISTORY_LIMIT_REQUIRES_BATCHING")

    need(seen_captures, "NO_ARCHIVED_CAPTURES")
    if not fills:
        reasons.add("NO_ACCOUNT_FILLS_TO_RECONCILE")
    status = (
        "REVIEW_REQUIRED"
        if reasons - {"NO_ACCOUNT_FILLS_TO_RECONCILE"}
        else "ACCOUNT_FILL_REFERENCE_CHECKS_PASS"
        if fills else "INCONCLUSIVE_NO_ACCOUNT_FILLS"
    )
    return {
        "status": status,
        "scope": "ACCOUNT_CAPTURE_FILL_REFERENCE_REPLAY_ONLY",
        "authenticated_capture_count": len(seen_captures),
        "duplicate_capture_observations": duplicate_captures,
        "session_count": len(sessions),
        "unique_account_fill_count": len(fills),
        "duplicate_fill_observations": duplicates,
        "observed_buy_fill_quantity": sum(
            value[3] for value in fills.values() if value[2] == "BUY"
        ),
        "observed_sell_fill_quantity": sum(
            value[3] for value in fills.values() if value[2] == "SELL"
        ),
        "review_reasons": sorted(reasons),
        "live_evidence_assessed": not fixture,
        "opening_position_baseline_verified": False,
        "positions_reconciled": False,
        "strategy_ownership_verified": False,
        "verified_owned_quantity": None,
        "ledger_persisted": False,
        "database_modified": False,
        "broker_reads_performed": False,
        "orders_sent": False,
        "production_execution_enabled": False,
        "reservation_release_permission": False,
        "fees_complete": False,
        "realized_net_pnl_paise": None,
        "open_net_pnl_paise": None,
        "production_ready": False,
    }


def archive_captures(path):
    file_sha(path)  # Regular-file/symlink check; no writes.
    with closing(sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=10
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        try:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='preparation_account_captures'"
            ).fetchone()
            need(exists, "CAPTURE_ARCHIVE_MISSING")
            for count, (sid, fingerprint, raw) in enumerate(db.execute(
                "SELECT id,fingerprint,data "
                "FROM preparation_account_captures ORDER BY rowid"
            ), 1):
                need(count <= 1000, "CAPTURE_LIMIT_REQUIRES_BATCHING")
                need(len(raw.encode()) <= 2_000_000,
                     "ARCHIVED_CAPTURE_TOO_LARGE")
                capture = json.loads(raw)
                need(capture["snapshot_id"] == sid
                     and M.sha(capture) == fingerprint,
                     "ARCHIVE_FINGERPRINT_MISMATCH")
                yield capture
        finally:
            db.rollback()


PIN = {"scope": "FIXTURE:FILL-HISTORY", "key": "11" * 32}


def signed(capture):
    capture.pop("signature", None)
    capture["signature"] = M.sign(capture, PIN)
    return capture


def sample(step=2, quantity=65, day=30):
    base = datetime(2026, 10, day, 4, 0, tzinfo=timezone.utc)
    stamp = lambda seconds: (base + timedelta(seconds=seconds)).isoformat()
    capture = {
        "model": "HILEGA_PRODUCTION_ACCOUNT_ADAPTER_V1",
        "evidence_mode": "LIVE_READ_ONLY_ACCOUNT_PINNED",
        "account_scope": PIN["scope"],
        "snapshot_id": f"fixture-{day}-{step}",
        "generated_at": stamp(step),
        "completed_at": stamp(step + 1),
        "session_date": f"2026-10-{day}",
        "status": "READ_ONLY_CAPTURED",
        "account_identity_verified": True,
        "profile_verified_before_and_after": True,
        "account_position_rows_complete": True,
        "source_atomic": False,
        "position_fill_linkage_verified": False,
        "live_pnl": None,
        "production_execution_enabled": False,
        "entry_permission": False,
        "orders_sent": False,
        "diagnostics": {},
        "orders": [{
            "order_id": "order-1", "instrument": "NSE_FO|FIXTURE",
            "product": "I", "side": "BUY", "quantity": 65,
            "filled": quantity, "pending": 65 - quantity,
            "status": "FILLED" if quantity == 65 else "PARTIAL",
            "placed_at": stamp(0),
        }],
        "trades": [{
            "order_id": "order-1", "trade_id": "fill-A",
            "instrument": "NSE_FO|FIXTURE", "product": "I",
            "side": "BUY", "quantity": quantity, "price": "100",
            "filled_at": stamp(1),
        }],
        "positions": [{
            "instrument": "NSE_FO|FIXTURE",
            "product": "I", "quantity": quantity,
        }],
    }
    return signed(capture)


class ReplayTests(unittest.TestCase):
    def run_replay(self, captures):
        return replay(captures, PIN, fixture=True)

    def test_repeated_fill_is_counted_once(self):
        r = self.run_replay([sample(), sample(4)])
        self.assertEqual(r["unique_account_fill_count"], 1)
        self.assertEqual(r["observed_buy_fill_quantity"], 65)
        self.assertEqual(r["duplicate_fill_observations"], 1)

    def test_partial_then_full_fill(self):
        first, second = sample(quantity=30), sample(4)
        second["trades"][0]["quantity"] = 30
        extra = deepcopy(second["trades"][0])
        extra.update(trade_id="fill-B", quantity=35)
        second["trades"].append(extra)
        r = self.run_replay([first, signed(second)])
        self.assertEqual(r["unique_account_fill_count"], 2)
        self.assertEqual(r["observed_buy_fill_quantity"], 65)

    def test_changed_fill_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "IMMUTABLE_FILL_CHANGED"):
            self.run_replay([
                sample(quantity=30), sample(4, quantity=31)
            ])

    def test_missing_fill_is_retained_and_flagged(self):
        later = sample(4)
        later.update(orders=[], trades=[])
        r = self.run_replay([sample(), signed(later)])
        self.assertEqual(r["unique_account_fill_count"], 1)
        self.assertEqual(r["status"], "REVIEW_REQUIRED")

    def test_cumulative_regression_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "CUMULATIVE_FILL_REGRESSION"):
            self.run_replay([
                sample(quantity=30), sample(4, quantity=20)
            ])

    def test_sessions_do_not_merge_fill_ids(self):
        r = self.run_replay([sample(), sample(day=31)])
        self.assertEqual(r["session_count"], 2)
        self.assertEqual(r["unique_account_fill_count"], 2)
        self.assertNotIn(
            "PREVIOUS_FILL_NOT_VISIBLE_IN_LATER_CAPTURE",
            r["review_reasons"],
        )

    def test_bad_signature_is_rejected(self):
        bad = sample()
        bad["snapshot_id"] = "tampered"
        with self.assertRaises(ValueError):
            self.run_replay([bad])

    def test_inputs_are_unchanged(self):
        captures = [sample(), sample(4)]
        before = deepcopy(captures)
        self.run_replay(captures)
        self.assertEqual(before, captures)

    def test_empty_history_is_inconclusive(self):
        empty = sample()
        empty.update(orders=[], trades=[], positions=[])
        r = self.run_replay([signed(empty)])
        self.assertEqual(r["status"], "INCONCLUSIVE_NO_ACCOUNT_FILLS")
        self.assertIsNone(r["realized_net_pnl_paise"])

    def test_quantity_modification_requires_review(self):
        first, later = sample(quantity=30), sample(4, quantity=30)
        later["orders"][0].update(quantity=80, pending=50)
        r = self.run_replay([first, signed(later)])
        self.assertEqual(r["status"], "REVIEW_REQUIRED")

    def test_equivalent_price_formats_match(self):
        later = sample(4)
        later["trades"][0]["price"] = "100.00"
        r = self.run_replay([sample(), signed(later)])
        self.assertEqual(r["unique_account_fill_count"], 1)

    def test_duplicate_capture_is_idempotent(self):
        capture = sample()
        r = self.run_replay([capture, deepcopy(capture)])
        self.assertEqual(r["authenticated_capture_count"], 1)
        self.assertEqual(r["duplicate_capture_observations"], 1)

    def test_duplicate_trade_within_capture_is_rejected(self):
        bad = sample()
        bad["trades"].append(deepcopy(bad["trades"][0]))
        with self.assertRaises(ValueError):
            self.run_replay([signed(bad)])

    def test_reused_capture_id_is_rejected(self):
        changed = sample()
        changed["trades"][0]["price"] = "101"
        with self.assertRaisesRegex(ValueError, "CAPTURE_ID_REUSED"):
            self.run_replay([sample(), signed(changed)])

    def test_capture_time_regression_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "CAPTURE_TIME_REGRESSION"):
            self.run_replay([sample(4), sample()])

    def test_terminal_status_change_is_rejected(self):
        later = sample(4)
        later["orders"][0]["status"] = "CANCELLED"
        with self.assertRaisesRegex(ValueError, "TERMINAL_ORDER_STATE_CHANGED"):
            self.run_replay([sample(), signed(later)])


def main():
    need(len(sys.argv) == 2 and sys.argv[1] in {"selftest", "check"},
         "USE_SELFTEST_OR_CHECK")
    load_validators()
    if sys.argv[1] == "selftest":
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ReplayTests)
        )
        return 0 if result.wasSuccessful() else 1

    from market_lab.hilega_production_account_adapter_v1 import read_pin
    pin = read_pin(
        Path.home() / "hilega-private/upstox-account-pin.json"
    )
    app = ROOT / "data/research/hilega-production-workspace/sim.sqlite"
    with closing(archive_captures(app)) as captures:
        report = replay(captures, pin)
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "REVIEW_REQUIRED" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        text = str(exc)
        reason = (
            text if re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", text)
            else type(exc).__name__
        )
        print(json.dumps({
            "status": "FILL_HISTORY_STOPPED_FOR_REVIEW",
            "reason": reason,
            "database_modified": False,
            "orders_sent": False,
            "production_execution_enabled": False,
            "reservation_release_permission": False,
            "production_ready": False,
        }, indent=2))
        raise SystemExit(1)