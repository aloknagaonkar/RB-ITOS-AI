from copy import deepcopy
import unittest
from bridge import position_references


class PositionReferences(unittest.TestCase):
    def setUp(self):
        self.orders={"entry":dict(instrument="fixture-option",product="I",
                                  side="BUY",filled=65,status="FILLED")}
        self.positions={("fixture-option","I"):65}

    def review(self, *, orders=None, positions=None, matched=None, **kwargs):
        args=dict(missing=0,unbound=0,without_binding=0,prior=0)
        args.update(kwargs)
        return position_references(
            self.orders if orders is None else orders,
            self.positions if positions is None else positions,
            {"entry"} if matched is None else matched, **args)

    def test_matching_entry_does_not_grant_strategy_ownership(self):
        r=self.review()
        self.assertTrue(r["current_entry_buy_position_quantities_match"])
        self.assertFalse(r["strategy_ownership_verified"])

    def test_missing_position_is_not_flat(self):
        r=self.review(positions={})
        self.assertEqual(r["missing_position_row_count"],1)
        self.assertFalse(r["current_entry_buy_position_quantities_match"])

    def test_quantity_mismatch_blocks(self):
        r=self.review(positions={("fixture-option","I"):64})
        self.assertEqual(r["mismatched_position_row_count"],1)
        self.assertFalse(r["current_entry_buy_position_quantities_match"])

    def test_short_position_blocks(self):
        r=self.review(positions={("fixture-option","I"):-65})
        self.assertEqual(r["mismatched_position_row_count"],1)

    def test_unlinked_exposure_blocks(self):
        p=dict(self.positions);p[("other-option","I")]=1
        r=self.review(positions=p)
        self.assertEqual(r["unlinked_nonzero_position_key_count"],1)
        self.assertFalse(r["current_entry_buy_position_quantities_match"])

    def test_unrelated_zero_row_does_not_create_exposure(self):
        p=dict(self.positions);p[("other-option","I")]=0
        self.assertTrue(self.review(positions=p)[
            "current_entry_buy_position_quantities_match"])

    def test_unrelated_order_blocks_even_with_matching_position(self):
        orders=deepcopy(self.orders);orders["other"]=dict(orders["entry"])
        self.assertIn("UNLINKED_ACCOUNT_ORDER_PREVENTS_POSITION_RECONCILIATION",
                      self.review(orders=orders)["position_reference_reasons"])

    def test_sell_exit_never_uses_entry_only_mapping(self):
        orders=deepcopy(self.orders);orders["entry"]["side"]="SELL"
        self.assertIn("SELL_EXIT_OWNERSHIP_NOT_SUPPORTED",
                      self.review(orders=orders)["position_reference_reasons"])

    def test_pending_entry_blocks(self):
        orders=deepcopy(self.orders)
        orders["entry"].update(status="PARTIAL",filled=30)
        r=self.review(orders=orders,positions={("fixture-option","I"):30})
        self.assertIn("NONTERMINAL_BOUND_ORDER_REQUIRES_RECONCILIATION",
                      r["position_reference_reasons"])

    def test_partial_cancel_matches_actual_fill_quantity_only(self):
        orders=deepcopy(self.orders)
        orders["entry"].update(status="CANCELLED",filled=30)
        r=self.review(orders=orders,positions={("fixture-option","I"):30})
        self.assertTrue(r["current_entry_buy_position_quantities_match"])
        self.assertEqual(r["expected_bound_buy_fill_quantity"],30)

    def test_multiple_entry_fills_same_key_sum(self):
        orders=deepcopy(self.orders)
        orders["second"]=dict(orders["entry"],filled=35)
        r=self.review(orders=orders,matched={"entry","second"},
                      positions={("fixture-option","I"):100})
        self.assertTrue(r["current_entry_buy_position_quantities_match"])

    def test_empty_account_never_establishes_baseline(self):
        r=self.review(orders={},positions={},matched=set())
        self.assertFalse(r["current_entry_buy_position_quantities_match"])

    def test_all_unresolved_reference_states_block(self):
        for flag in ("missing","unbound","without_binding","prior"):
            with self.subTest(flag=flag):
                r=self.review(**{flag:1})
                self.assertFalse(r["current_entry_buy_position_quantities_match"])

    def test_wrong_product_is_not_matching_exposure(self):
        r=self.review(positions={("fixture-option","D"):65})
        self.assertEqual(r["missing_position_row_count"],1)
        self.assertEqual(r["unlinked_nonzero_position_key_count"],1)

    def test_inputs_unchanged(self):
        before=deepcopy((self.orders,self.positions))
        self.review()
        self.assertEqual((self.orders,self.positions),before)


if __name__=="__main__":
    unittest.main()
