"""Read-only first-entry baseline. No order or database writes."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unittest

ROOT = Path.cwd().resolve()


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def load(path, name):
    need(path.is_file() and not path.is_symlink(),
         "REGULAR_SOURCE_REQUIRED")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assess(cash, local_clear):
    need(type(local_clear) is bool, "LOCAL_CHECK_REQUIRED")
    need(cash.get("capture_verified") is True,
         "VERIFIED_CASH_REQUIRED")
    available = cash["cash_cents"]
    cap = cash["half_cash_cap_cents"]
    need(type(available) is int and available >= 0
         and type(cap) is int and cap == available // 2,
         "HALF_CASH_ARITHMETIC_INVALID")
    reasons = list(cash["reasons"])
    need(all(isinstance(r, str) for r in reasons),
         "CASH_REASONS_INVALID")
    if not local_clear:
        reasons.append("LOCAL_ACTIVITY_REQUIRES_REVIEW")
    if cap <= 0:
        reasons.append("NO_CASH_CAPACITY")
    return dict(
        model="HILEGA_FIRST_ENTRY_BASELINE_REVIEW_V1",
        status=("BLOCKED_BASELINE_REVIEW" if reasons
                else "READ_ONLY_BASELINE_CHECKS_PASS"),
        reasons=sorted(set(reasons)),
        verified_available_cash_paise=available,
        half_cash_budget_paise=cap,
        entry_allocation_fraction="0.50",
        daily_loss_limit_required=False,
        scope="EMPTY_ACCOUNT_FIRST_ENTRY_BASELINE_ONLY",
        previous_strategy_fills_required=False,
        candidate_cost_assessed=False,
        contract_and_quote_assessed=False,
        signal_admission_assessed=False,
        evidence_sources_atomic=False,
        baseline_is_persisted_opening_position_proof=False,
        strategy_ownership_verified=False,
        fees_complete=False,
        broker_cash_locked=False,
        database_modified=False,
        controller_changed=False,
        entry_permission=False,
        exit_submission_permission=False,
        reservation_release_permission=False,
        orders_sent=False,
        production_execution_enabled=False,
        production_ready=False,
    )


class Tests(unittest.TestCase):
    def cash(self, amount=100001):
        return dict(capture_verified=True, cash_cents=amount,
                    half_cash_cap_cents=amount // 2, reasons=[])

    def test_half_cash_rounds_down(self):
        self.assertEqual(
            assess(self.cash(), True)["half_cash_budget_paise"], 50000)

    def test_zero_cash_blocks(self):
        self.assertIn("NO_CASH_CAPACITY",
                      assess(self.cash(0), True)["reasons"])

    def test_local_activity_blocks(self):
        self.assertIn("LOCAL_ACTIVITY_REQUIRES_REVIEW",
                      assess(self.cash(), False)["reasons"])

    def test_cash_reasons_retained(self):
        cash = self.cash()
        cash["reasons"] = ["FUNDS_CHANGED_DURING_CAPTURE"]
        self.assertIn("FUNDS_CHANGED_DURING_CAPTURE",
                      assess(cash, True)["reasons"])

    def test_bad_cap_rejected(self):
        cash = self.cash()
        cash["half_cash_cap_cents"] += 1
        with self.assertRaises(ValueError):
            assess(cash, True)

    def test_boolean_cash_rejected(self):
        cash = self.cash()
        cash["cash_cents"] = True
        with self.assertRaises(ValueError):
            assess(cash, True)

    def test_inputs_unchanged(self):
        cash = self.cash()
        old = deepcopy(cash)
        assess(cash, True)
        self.assertEqual(cash, old)

    def test_pass_grants_no_permission(self):
        result = assess(self.cash(), True)
        self.assertEqual(result["status"],
                         "READ_ONLY_BASELINE_CHECKS_PASS")
        for key in ("entry_permission", "orders_sent",
                    "production_execution_enabled", "production_ready"):
            self.assertIs(result[key], False)


def check():
    producer = load(
        ROOT / "hilega-ownership-producer-tools-v1/producer.py",
        "baseline_existing_producer")
    producer.package_check(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))

    from dotenv import dotenv_values
    from market_lab.hilega_production_account_adapter_v1 import (
        read_pin, Client,
    )
    from market_lab.hilega_preparation_runtime_v1.collect import collectors
    from market_lab.hilega_preparation_runtime_v1.evidence import dependencies
    from market_lab.hilega_preparation_runtime_v1 import cash_reservation
    from market_lab.hilega_preparation_runtime_v1.ownership_checks import (
        risk_evidence_audit as audit,
    )

    pin_path = Path.home() / "hilega-private/upstox-account-pin.json"
    pin = read_pin(pin_path)
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "LIVE_ACCOUNT_PIN_REQUIRED")
    app = ROOT / "data/research/hilega-production-workspace/sim.sqlite"
    broker = ROOT / "data/research/hilega-broker-adapter-closed/adapter.sqlite"

    def local():
        source = audit.read_sources(app, broker, pin["scope"])
        audit.assess(source)
        control = source["control"]
        need(control.get("production_execution_enabled") is False,
             "CLOSED_CONTROLLER_REQUIRED")
        need(control.get("mode") == "PAUSED",
             "PAUSED_CONTROLLER_REQUIRED")
        stop = source["stop_state"]
        need(isinstance(stop, list) and len(stop) == 2
             and all(type(v) is int and v >= 0 for v in stop)
             and stop[0] == stop[1], "STOP_STATE_UNRESOLVED")

        # Additional local preparation/reservation rows are blockers.
        tables = {
            "intents", "sim_orders", "sim_fills",
            "sim_allocation_reservations",
            "preparation_plans", "preparation_shadow_holds",
            "preparation_outbox", "preparation_request_bindings",
            "staged_intents", "staged_reservations",
            "staged_adapter_requests", cash_reservation.TABLE,
        }
        counts = {}
        with closing(sqlite3.connect(
                app.resolve().as_uri() + "?mode=ro",
                uri=True, timeout=10)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            present = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in sorted(tables):
                need(re.fullmatch(r"[a-z_]+", table) is not None,
                     "TABLE_NAME_INVALID")
                counts[table] = (
                    db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    if table in present else 0)
            db.rollback()
        clear = not any(counts.values()) and not any(
            source[k] for k in ("requests", "attempts", "receipts",
                               "plans", "holds", "outbox", "bindings"))
        return source, counts, clear

    before = local()
    _, gate = dependencies()
    _, _, cash_module, _ = collectors()
    settings = dotenv_values(ROOT / ".env")

    def setting(name):
        shell, file = os.getenv(name), settings.get(name)
        need(not (shell and file and shell != file),
             "TOKEN_CONFIGURATION_CONFLICT")
        return shell or file

    token = (setting("HILEGA_PRODUCTION_BROKER_READ_TOKEN")
             or setting("UPSTOX_ACCESS_TOKEN") or "").strip()
    need(bool(token), "READ_TOKEN_MISSING")
    snapshot = cash_module.capture(Client(token), pin)
    need(read_pin(pin_path) == pin, "ACCOUNT_PIN_CHANGED")
    after = local()
    need(before == after, "LOCAL_SOURCES_CHANGED_DURING_CAPTURE")

    now = datetime.now(timezone.utc)
    cash = gate.verify_capture(snapshot, pin, as_of=now.isoformat())
    # Bound total age from capture START, not only completion.
    start = datetime.fromisoformat(snapshot["started_at"])
    need(0 <= (now - start).total_seconds() <= 30,
         "CAPTURE_START_STALE_OR_FUTURE")
    need(snapshot.get("capture_atomic") is False,
         "UNEXPECTED_ATOMIC_CAPTURE_CLAIM")
    result = assess(cash, after[2])
    result.update(
        assessed_at=now.isoformat(),
        account_capture_started_at=snapshot["started_at"],
        account_capture_completed_at=snapshot["completed_at"],
        account_capture_age_seconds=(now - start).total_seconds(),
        signed_cash_capture_verified=True,
        local_sources_unchanged_during_capture=True,
        broker_reads_performed=True,
        local_activity_counts=after[1],
    )
    print(json.dumps(result, indent=2))
    return 1 if result["reasons"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("selftest", "check"))
    args = parser.parse_args()
    if args.action == "selftest":
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
        return 0 if result.wasSuccessful() else 1
    return check()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", reason):
            reason = "SOURCE_OR_CAPTURE_REVIEW_REQUIRED"
        print(json.dumps(dict(
            status="FIRST_ENTRY_BASELINE_STOPPED_FOR_REVIEW",
            reason=reason,
            database_modified=False,
            orders_sent=False,
            production_execution_enabled=False,
            production_ready=False,
        ), indent=2))
        raise SystemExit(1)