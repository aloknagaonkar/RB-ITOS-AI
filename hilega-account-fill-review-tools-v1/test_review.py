
import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).with_name("review.py")
spec = importlib.util.spec_from_file_location("review_under_test", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ReferenceChecks(unittest.TestCase):
    def setUp(self):
        self.order = dict(
            order_id="fixture-order", instrument="fixture-option",
            product="I", side="BUY", quantity=65, filled=65, status="FILLED",
        )
        self.trade = dict(
            order_id="fixture-order", trade_id="fixture-fill",
            instrument="fixture-option", product="I", side="BUY", quantity=65,
        )
        self.link = {k: self.order[k] for k in (
            "order_id", "instrument", "product", "side", "quantity",
        )}
        self.snapshot = dict(
            orders=[self.order], trades=[self.trade], positions=[],
        )

    def blocked(self, snapshot, reason, links=None):
        with self.assertRaisesRegex(ValueError, "^" + reason + "$"):
            m.compare([self.link] if links is None else links, snapshot)

    def test_empty_account_has_no_reference_matches(self):
        result = m.compare([], dict(orders=[], trades=[], positions=[]))
        self.assertEqual(result["current_order_reference_matches"], 0)
        self.assertNotIn("realized_net_pnl", result)

    def test_full_fill_reference_matches(self):
        result = m.compare([self.link], self.snapshot)
        self.assertEqual(result["current_order_reference_matches"], 1)

    def test_multiple_fills_sum_to_order_total(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["trades"] = [
            dict(self.trade, quantity=30),
            dict(self.trade, trade_id="second-fill", quantity=35),
        ]
        self.assertEqual(
            m.compare([self.link], snapshot)["current_trade_count"], 2
        )

    def test_partial_fill_remains_nonterminal(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["orders"][0].update(filled=30, status="PARTIAL")
        snapshot["trades"][0]["quantity"] = 30
        self.assertEqual(
            m.compare([self.link], snapshot)["nonterminal_order_count"], 1
        )

    def test_cancelled_partial_fill_can_match_reference(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["orders"][0].update(filled=30, status="CANCELLED")
        snapshot["trades"][0]["quantity"] = 30
        result = m.compare([self.link], snapshot)
        self.assertEqual(result["current_order_reference_matches"], 1)
        self.assertEqual(result["nonterminal_order_count"], 0)

    def test_acknowledgement_without_fill_is_not_a_trade(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["orders"][0].update(filled=0, status="OPEN")
        snapshot["trades"] = []
        result = m.compare([self.link], snapshot)
        self.assertEqual(result["current_trade_count"], 0)
        self.assertEqual(result["nonterminal_order_count"], 1)

    def test_missing_fill_blocks(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["trades"] = []
        self.blocked(snapshot, "ORDER_TRADE_FILL_TOTAL_MISMATCH")

    def test_excess_fill_blocks(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["trades"][0]["quantity"] = 66
        self.blocked(snapshot, "ORDER_TRADE_FILL_TOTAL_MISMATCH")

    def test_duplicate_order_blocks(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["orders"].append(dict(self.order))
        self.blocked(snapshot, "DUPLICATE_ORDER_ID")

    def test_duplicate_trade_blocks(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["trades"].append(dict(self.trade))
        self.blocked(snapshot, "DUPLICATE_TRADE_ID")

    def test_orphan_trade_blocks(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["orders"] = []
        self.blocked(snapshot, "TRADE_ORDER_MISSING")

    def test_trade_identity_mismatch_blocks(self):
        for field, value in (
            ("instrument", "other-option"), ("product", "D"), ("side", "SELL"),
        ):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(self.snapshot)
                snapshot["trades"][0][field] = value
                self.blocked(snapshot, "TRADE_IDENTITY_MISMATCH")

    def test_invalid_trade_quantity_blocks(self):
        for value in (True, 0, -1, "65", 65.0):
            with self.subTest(value=value):
                snapshot = copy.deepcopy(self.snapshot)
                snapshot["trades"][0]["quantity"] = value
                self.blocked(snapshot, "TRADE_QUANTITY_INVALID")

    def test_historical_contract_mismatch_blocks(self):
        for field, value in (
            ("instrument", "other-option"), ("product", "D"),
            ("side", "SELL"), ("quantity", 130),
        ):
            with self.subTest(field=field):
                link = dict(self.link)
                link[field] = value
                self.blocked(
                    self.snapshot,
                    "HISTORICAL_ACK_CURRENT_ORDER_MISMATCH",
                    links=[link],
                )

    def test_same_symbol_does_not_adopt_unrelated_order(self):
        link = dict(self.link, order_id="different-historical-order")
        result = m.compare([link], self.snapshot)
        self.assertEqual(result["current_order_reference_matches"], 0)
        self.assertEqual(
            result["current_orders_without_historical_reference"], 1
        )
        self.assertEqual(
            result["historical_orders_absent_from_current_snapshot"], 1
        )

    def test_nonzero_position_remains_explicit(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["positions"] = [
            dict(instrument="fixture-option", product="I", quantity=65),
        ]
        result = m.compare([self.link], snapshot)
        self.assertEqual(result["nonzero_position_count"], 1)
        self.assertNotIn("strategy_ownership_verified", result)

    def test_inputs_are_not_modified(self):
        before = copy.deepcopy(([self.link], self.snapshot))
        m.compare([self.link], self.snapshot)
        self.assertEqual(([self.link], self.snapshot), before)


if __name__ == "__main__":
    unittest.main()
