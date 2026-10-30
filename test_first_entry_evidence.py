"""Synthetic evidence tests. No broker calls or database access."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / "backend"))

from market_lab.hilega_preparation_runtime_v1.evidence import dependencies
from market_lab.hilega_production_account_adapter_v1 import sign

path = Path.home() / "first_entry_baseline.py"
spec = importlib.util.spec_from_file_location("baseline_test_target", path)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
_, gate = dependencies()

PIN = {"scope": "FIXTURE:FIRST-ENTRY-EVIDENCE", "key": "22" * 32}
NOW = datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc)


def signed(value):
    value = deepcopy(value)
    value.pop("signature", None)
    value["signature"] = sign(value, PIN)
    return value


def sample():
    funds = {
        "field": "data.available_to_trade.cash_available_to_trade.total",
        "cash_available_to_trade": "1000.01",
    }
    return signed(dict(
        model="HILEGA_READ_ONLY_CASH_OBSERVATION_V1",
        evidence_mode="LIVE_READ_ONLY_ACCOUNT_PINNED",
        snapshot_id="synthetic-baseline-only",
        account_scope=PIN["scope"],
        account_identity_verified=True,
        account_position_rows_complete=True,
        status="READ_ONLY_CAPTURED",
        started_at=(NOW - timedelta(seconds=2)).isoformat(),
        completed_at=(NOW - timedelta(seconds=1)).isoformat(),
        session_date="2026-10-30",
        funds_before=deepcopy(funds),
        funds_after=deepcopy(funds),
        funds_changed_during_capture=False,
        orders=[], trades=[], positions=[],
        diagnostics={"issues": []},
        production_execution_enabled=False,
        orders_sent=False,
        entry_permission=False,
        capture_atomic=False,
    ))


def review(value):
    cash = gate.verify_capture(value, PIN, as_of=NOW.isoformat())
    return baseline.assess(cash, True)


class EvidenceTests(unittest.TestCase):
    def test_funded_half_cash(self):
        result = review(sample())
        self.assertEqual(result["verified_available_cash_paise"], 100001)
        self.assertEqual(result["half_cash_budget_paise"], 50000)
        self.assertEqual(result["status"], "READ_ONLY_BASELINE_CHECKS_PASS")
        self.assertFalse(result["entry_permission"])

    def test_signature_tamper(self):
        value = sample()
        value["funds_after"]["cash_available_to_trade"] = "999999"
        with self.assertRaises(ValueError):
            review(value)

    def test_wrong_account(self):
        value = sample()
        value["account_scope"] = "FIXTURE:OTHER"
        with self.assertRaises(ValueError):
            review(signed(value))

    def test_stale_capture(self):
        value = sample()
        value["started_at"] = (NOW - timedelta(seconds=40)).isoformat()
        value["completed_at"] = (NOW - timedelta(seconds=39)).isoformat()
        with self.assertRaises(ValueError):
            review(signed(value))

    def test_future_capture(self):
        value = sample()
        value["completed_at"] = (NOW + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            review(signed(value))

    def test_cash_drift_blocks(self):
        value = sample()
        value["funds_before"]["cash_available_to_trade"] = "1100.01"
        value["funds_changed_during_capture"] = True
        self.assertIn("FUNDS_CHANGED_DURING_CAPTURE",
                      review(signed(value))["reasons"])

    def test_orders_and_trades_block(self):
        for field in ("orders", "trades"):
            with self.subTest(field=field):
                value = sample()
                # Only tests the conservative nonempty-list blocker.
                value[field] = [{"synthetic": True}]
                self.assertIn(
                    "ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED",
                    review(signed(value))["reasons"])

    def test_nonzero_position_blocks(self):
        value = sample()
        value["positions"] = [{"quantity": 65}]
        self.assertIn("ACCOUNT_EXPOSURE_OWNERSHIP_UNVERIFIED",
                      review(signed(value))["reasons"])

    def test_diagnostics_block(self):
        value = sample()
        value["diagnostics"]["issues"] = ["SYNTHETIC_REVIEW"]
        self.assertIn("ACCOUNT_EVIDENCE_DIAGNOSTICS_REQUIRE_REVIEW",
                      review(signed(value))["reasons"])

    def test_execution_flag_rejected(self):
        value = sample()
        value["entry_permission"] = True
        with self.assertRaises(ValueError):
            review(signed(value))

    def test_boolean_position_rejected(self):
        value = sample()
        value["positions"] = [{"quantity": True}]
        with self.assertRaises(ValueError):
            review(signed(value))

    def test_inputs_unchanged(self):
        value = sample()
        original = deepcopy(value)
        review(value)
        self.assertEqual(value, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)