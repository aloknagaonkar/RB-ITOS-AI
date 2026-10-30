from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest
import test_exit_fills as fixtures
from gross_pnl import preview_fixture_pnl
from fee_report import query
from signature_checks import sign


class GrossPnlTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ExitFillTests();self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.review()
        self.pin=self.f.pin;self.at="2026-10-29T05:30:07+00:00"
        with closing(sqlite3.connect(self.f.a.path)) as db:
            self.state=json.loads(db.execute("SELECT data FROM exit_fill_state").fetchone()[0])

    def preview(self,state=None,fee=None,**kwargs):
        s=deepcopy(self.state if state is None else state)
        s.pop("signature",None);s["signature"]=sign(s,self.pin)
        args=dict(state=s,pin=self.pin,as_of=self.at,fee_capture=fee)
        args.update(kwargs)
        return preview_fixture_pnl(**args)

    def partial(self):
        s=deepcopy(self.state)
        oid=next(k for k,o in s["orders"].items() if o["side"]=="SELL")
        s["orders"][oid].update(filled=30,pending=35,status="PARTIAL")
        for f in s["fills"].values():
            if f["side"]=="SELL":f["quantity"]=30
        s.update(remaining_quantity=35,fixture_flat_reference_verified=False,
                 all_referenced_orders_terminal=False)
        return s

    def fee(self,total=0):
        raw=dict(status="success",data=dict(charges_breakdown=dict(
            total=total,brokerage=total,taxes={},charges={})))
        value=dict(model="HILEGA_AGGREGATE_FEE_REPORT_CAPTURE_V1",
            account_scope=self.pin["scope"],session_date="2026-10-29",
            started_at="2026-10-29T05:30:05+00:00",
            completed_at="2026-10-29T05:30:06+00:00",
            profile_verified_before_and_after=True,query=query("2026-10-29"),
            provider_response=raw,source_atomic=False,orders_sent=False,
            production_execution_enabled=False,entry_permission=False)
        value["signature"]=sign(value,self.pin)
        return value

    def test_closed_gross_is_exact_paise(self):
        r=self.preview()
        self.assertEqual(r["gross_realized_paise"],6175)
        self.assertEqual(r["open_gross_pnl_paise"],0)
        self.assertIsNone(r["realized_net_pnl_paise"])

    def test_partial_realized_gross_uses_sold_quantity(self):
        r=self.preview(self.partial())
        self.assertEqual(r["gross_realized_paise"],2850)
        self.assertEqual(r["remaining_quantity"],35)
        self.assertEqual(r["remaining_cost_basis_paise_fraction"],
                         dict(numerator=350175,denominator=1))

    def test_open_position_does_not_invent_a_mark(self):
        r=self.preview(self.partial())
        self.assertIsNone(r["open_gross_pnl_paise"])
        self.assertIsNone(r["open_net_pnl_paise"])

    def test_aggregate_charges_not_deducted_from_strategy(self):
        r=self.preview(fee=self.fee(total=100))
        self.assertEqual(r["reported_account_aggregate_fee_paise"],10000)
        self.assertEqual(r["gross_realized_paise"],6175)
        self.assertIsNone(r["strategy_fees_paise"])
        self.assertIsNone(r["realized_net_pnl_paise"])

    def test_zero_aggregate_never_proves_fee_completeness(self):
        r=self.preview(fee=self.fee())
        self.assertFalse(r["fees_complete"])
        self.assertFalse(r["risk_gate_input_ready"])
        self.assertFalse(r["account_aggregate_fees_applied_to_strategy"])

    def test_wrong_fee_account_rejected(self):
        fee=self.fee();fee["account_scope"]="FIXTURE:OTHER"
        fee.pop("signature");fee["signature"]=sign(fee,self.pin)
        with self.assertRaisesRegex(ValueError,"EVIDENCE_ACCOUNT_SCOPE_MISMATCH"):
            self.preview(fee=fee)

    def test_unsigned_state_rejected(self):
        s=deepcopy(self.state);s.pop("signature")
        with self.assertRaisesRegex(ValueError,"EVIDENCE_SIGNATURE_INVALID"):
            preview_fixture_pnl(s,self.pin,as_of=self.at)

    def test_tampered_state_rejected(self):
        s=deepcopy(self.state);s["remaining_quantity"]=999
        with self.assertRaisesRegex(ValueError,"EVIDENCE_SIGNATURE_INVALID"):
            preview_fixture_pnl(s,self.pin,as_of=self.at)

    def test_wrong_state_account_rejected(self):
        s=deepcopy(self.state);s["account_scope"]="FIXTURE:OTHER"
        with self.assertRaisesRegex(ValueError,"EVIDENCE_ACCOUNT_SCOPE_MISMATCH"):
            self.preview(s)

    def test_stale_state_rejected(self):
        with self.assertRaisesRegex(ValueError,"FILL_STATE_STALE_FUTURE_OR_WRONG_SESSION"):
            self.preview(as_of="2026-10-29T05:30:36+00:00")

    def test_live_scope_never_accepted(self):
        with self.assertRaisesRegex(ValueError,"FIXTURE_ACCOUNT_REQUIRED"):
            self.preview(pin=dict(self.pin,scope="UPSTOX:"+"a"*64))

    def test_sell_cannot_borrow_future_fill(self):
        s=deepcopy(self.state)
        buy=next(f for f in s["fills"].values() if f["side"]=="BUY")
        buy["quantity"]=30
        later=dict(buy,trade_id="later-buy",quantity=35,
                   filled_at="2026-10-29T11:00:05+05:30")
        s["fills"][later["order_id"]+"|"+later["trade_id"]]=later
        with self.assertRaisesRegex(ValueError,"EXIT_PRECEDES_AVAILABLE_ENTRY_FILLS"):
            self.preview(s)

    def split_buys(self,s):
        buy=next(f for f in s["fills"].values() if f["side"]=="BUY")
        buy.update(quantity=20,price="100")
        second=dict(buy,trade_id="second-buy",quantity=45,price="101",
                    filled_at="2026-10-29T11:00:03+05:30")
        s["fills"][second["order_id"]+"|"+second["trade_id"]]=second

    def test_multiple_buy_prices_weighted_exactly(self):
        s=deepcopy(self.state);self.split_buys(s)
        self.assertEqual(self.preview(s)["gross_realized_paise"],2000)

    def test_fractional_paise_not_silently_rounded(self):
        s=self.partial();self.split_buys(s)
        r=self.preview(s)
        self.assertIsNone(r["gross_realized_paise"])
        self.assertEqual(r["gross_realized_paise_fraction"],
                         dict(numerator=12000,denominator=13))

    def test_no_history_is_not_zero_pnl(self):
        s=deepcopy(self.state);s["fills"]={}
        for o in s["orders"].values():o.update(status="REJECTED",filled=0,pending=0)
        with self.assertRaisesRegex(ValueError,"NO_EXECUTION_BASELINE_IS_NOT_ZERO_PNL"):
            self.preview(s)

    def test_zero_gross_does_not_mean_zero_net(self):
        s=deepcopy(self.state)
        for f in s["fills"].values():f["price"]="100"
        r=self.preview(s)
        self.assertEqual(r["gross_realized_paise"],0)
        self.assertIsNone(r["realized_net_pnl_paise"])

    def test_negative_gross_preserved(self):
        s=deepcopy(self.state)
        for f in s["fills"].values():
            if f["side"]=="SELL":f["price"]="99.05"
        self.assertEqual(self.preview(s)["gross_realized_paise"],-6500)

    def test_no_fee_capture_keeps_fees_unknown(self):
        r=self.preview()
        self.assertFalse(r["aggregate_fee_capture_assessed"])
        self.assertIsNone(r["reported_account_aggregate_fee_paise"])

    def test_inputs_unchanged(self):
        state=deepcopy(self.state);fee=self.fee();before=deepcopy((state,fee))
        self.preview(state,fee=fee)
        self.assertEqual((state,fee),before)

    def test_stale_fee_capture_rejected(self):
        fee=self.fee()
        fee.update(started_at="2026-10-29T05:29:00+00:00",
                   completed_at="2026-10-29T05:29:01+00:00")
        fee.pop("signature");fee["signature"]=sign(fee,self.pin)
        with self.assertRaisesRegex(ValueError,"FEE_CAPTURE_STALE_FUTURE_OR_WRONG_SCOPE"):
            self.preview(fee=fee)


if __name__=="__main__":
    unittest.main()
