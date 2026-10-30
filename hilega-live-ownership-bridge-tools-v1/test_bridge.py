from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from bridge import correlate
from signature_checks import sign, MODEL, LIVE
from risk_evidence_audit import read_sources
from test_risk_evidence_audit import Fixture
from historical_receipt_checks import sha


class BridgeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.f = Fixture(Path(tmp.name))
        self.f.bind()
        self.f.acknowledge()
        self.pin = dict(scope=self.f.scope, key="11"*32)
        self.at = "2026-10-29T05:30:02+00:00"
        self.snapshot = dict(
            model=MODEL, evidence_mode=LIVE,
            generated_at="2026-10-29T05:30:00+00:00",
            completed_at="2026-10-29T05:30:01+00:00",
            session_date="2026-10-29", account_scope=self.f.scope,
            snapshot_id="fixture-snapshot", status="READ_ONLY_CAPTURED",
            account_identity_verified=True, profile_verified_before_and_after=True,
            account_position_rows_complete=True, source_atomic=False,
            position_fill_linkage_verified=False, live_pnl=None,
            production_execution_enabled=False, entry_permission=False,
            orders_sent=False, diagnostics={},
            orders=[dict(order_id="FIXTURE-ORDER", instrument="NSE_FO|FIXTURE",
                product="I", side="BUY", quantity=65, filled=65, pending=0,
                status="FILLED", placed_at="2026-10-29T11:00:00+05:30")],
            trades=[dict(order_id="FIXTURE-ORDER", trade_id="fixture-fill",
                instrument="NSE_FO|FIXTURE", product="I", side="BUY",
                quantity=65, price="100.05",
                filled_at="2026-10-29T11:00:01+05:30")],
            positions=[dict(instrument="NSE_FO|FIXTURE", product="I", quantity=65)])

    def source(self):
        return read_sources(self.f.app, self.f.adapter, self.f.scope,
                            expected_mode="OFFLINE_FIXTURE")

    def run_review(self, snapshot=None, source=None, at=None):
        s=deepcopy(snapshot if snapshot is not None else self.snapshot)
        s["signature"]=sign(s,self.pin)
        return correlate(self.source() if source is None else source,
                         s,self.pin,as_of=at or self.at)

    def reject(self, code, edit):
        s=deepcopy(self.snapshot);edit(s)
        with self.assertRaisesRegex(ValueError, code):
            self.run_review(s)

    def test_linked_fill_has_no_ownership_or_pnl_authority(self):
        r=self.run_review()
        self.assertEqual(r["current_bound_fill_quantity"],65)
        self.assertEqual(r["current_bound_order_reference_count"],1)
        for k in ("strategy_ownership_verified","production_ready",
                  "risk_gate_input_ready","entry_permission",
                  "reservation_release_permission","fees_complete"):
            self.assertIs(r[k],False)
        self.assertIsNone(r["realized_net_pnl_paise"])

    def test_empty_capture_is_not_zero_pnl(self):
        s=dict(self.snapshot,orders=[],trades=[],positions=[])
        r=self.run_review(s)
        self.assertEqual(r["missing_current_bound_order_count"],1)
        self.assertIsNone(r["open_net_pnl_paise"])

    def test_signature_tamper(self):
        s=deepcopy(self.snapshot);s["signature"]=sign(s,self.pin)
        s["snapshot_id"]="tampered"
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_SIGNATURE_INVALID"):
            correlate(self.source(),s,self.pin,as_of=self.at)

    def test_stale_capture(self):
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_STALE_OR_FUTURE"):
            self.run_review(at="2026-10-29T05:30:31+00:00")

    def test_future_capture(self):
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_STALE_OR_FUTURE"):
            self.run_review(at="2026-10-29T05:29:59+00:00")

    def test_wrong_account(self):
        self.reject("SNAPSHOT_ACCOUNT_SCOPE_MISMATCH",
                    lambda s:s.update(account_scope="OTHER"))

    def test_fixture_evidence_cannot_pass_live_capture_check(self):
        self.reject("LIVE_PINNED_EVIDENCE_REQUIRED",
                    lambda s:s.update(evidence_mode="OFFLINE_FIXTURE"))

    def test_execution_permission_rejected(self):
        self.reject("UNEXPECTED_EXECUTION_PERMISSION",
                    lambda s:s.update(entry_permission=True))

    def test_atomic_claim_rejected(self):
        self.reject("UNEXPECTED_CAPTURE_AUTHORITY",
                    lambda s:s.update(source_atomic=True))

    def test_duplicate_orders(self):
        self.reject("DUPLICATE_ORDER_ID",
                    lambda s:s["orders"].append(deepcopy(s["orders"][0])))

    def test_duplicate_trades(self):
        self.reject("DUPLICATE_TRADE_ID",
                    lambda s:s["trades"].append(deepcopy(s["trades"][0])))

    def test_missing_fill(self):
        self.reject("ORDER_TRADE_FILL_TOTAL_MISMATCH",lambda s:s.update(trades=[]))

    def test_invalid_prices(self):
        for price in ("NaN","Infinity","0","-1",True):
            with self.subTest(price=price):
                self.reject("TRADE_PRICE_INVALID",
                    lambda s:s["trades"][0].update(price=price))

    def test_boolean_quantity(self):
        self.reject("TRADE_QUANTITY_INVALID",
                    lambda s:s["trades"][0].update(quantity=True))

    def test_trade_contract_mismatch(self):
        self.reject("TRADE_CONTRACT_MISMATCH",
                    lambda s:s["trades"][0].update(side="SELL"))

    def test_bound_contract_mismatch(self):
        def edit(s):
            s["orders"][0]["instrument"]="OTHER"
            s["trades"][0]["instrument"]="OTHER"
        self.reject("BOUND_ORDER_CONTRACT_MISMATCH",edit)

    def test_pre_signal_order(self):
        self.reject("ORDER_PRECEDES_SIGNAL",
            lambda s:s["orders"][0].update(placed_at="2026-10-29T10:59:59+05:30"))

    def test_future_fill(self):
        self.reject("TRADE_TIME_INVALID",
            lambda s:s["trades"][0].update(filled_at="2026-10-29T11:00:02+05:30"))

    def test_unrelated_order_not_adopted_by_symbol(self):
        s=deepcopy(self.snapshot)
        s["orders"][0]["order_id"]="UNRELATED"
        s["trades"][0]["order_id"]="UNRELATED"
        r=self.run_review(s)
        self.assertEqual(r["current_bound_order_reference_count"],0)
        self.assertEqual(r["current_unlinked_order_count"],1)

    def test_ack_without_app_binding_not_adopted(self):
        source=self.source();source["bindings"]={}
        r=self.run_review(source=source)
        self.assertEqual(r["acknowledgements_without_application_binding"],1)
        self.assertEqual(r["current_bound_fill_quantity"],0)

    def test_changed_application_hash_rejected(self):
        source=self.source();source["holds"]["p1"]["held_cents"]=1
        with self.assertRaisesRegex(ValueError,"APPLICATION_BINDING_HASH_MISMATCH"):
            self.run_review(source=source)

    def test_partial_cancel_has_reference_not_position_authority(self):
        s=deepcopy(self.snapshot)
        s["orders"][0].update(status="CANCELLED",filled=30)
        s["trades"][0]["quantity"]=30
        r=self.run_review(s)
        self.assertEqual(r["current_bound_fill_quantity"],30)
        self.assertFalse(r["strategy_ownership_verified"])

    def test_duplicate_positions(self):
        self.reject("DUPLICATE_POSITION_KEY",
            lambda s:s["positions"].append(deepcopy(s["positions"][0])))

    def test_inputs_and_databases_unchanged(self):
        before=deepcopy(self.snapshot)
        raw=[p.read_bytes() for p in (self.f.app,self.f.adapter)]
        self.run_review()
        self.assertEqual(self.snapshot,before)
        self.assertEqual(raw,[p.read_bytes() for p in (self.f.app,self.f.adapter)])

    def test_summary_does_not_expose_raw_ids(self):
        text=json.dumps(self.run_review())
        for value in ("FIXTURE-ORDER","fixture-fill","fixture-snapshot",self.pin["key"]):
            self.assertNotIn(value,text)

    def test_prior_session_ack_not_adopted(self):
        source=self.source()
        key,fp,raw=source["requests"][0]
        request=json.loads(raw)
        request["signal_at"]="2026-10-28T11:00:00+05:30"
        stable={k:request[k] for k in ("request_id","draft","signal_id",
                                     "signal_at","direction","reservation_reference")}
        fp=sha(stable)
        source["requests"]=[(key,fp,json.dumps(request))]
        source["bindings"][key]["request_fingerprint"]=fp
        r=self.run_review(source=source)
        self.assertEqual(r["prior_session_ack_count"],1)
        self.assertEqual(r["current_bound_fill_quantity"],0)

    def test_exact_thirty_second_age_boundary(self):
        r=self.run_review(at="2026-10-29T05:30:30+00:00")
        self.assertEqual(r["account_capture_age_seconds"],30)

    def test_invalid_partial_state(self):
        self.reject("PARTIAL_ORDER_INCONSISTENT",
                    lambda s:s["orders"][0].update(status="PARTIAL"))

    def test_profile_confirmation_required(self):
        self.reject("COMPLETE_PINNED_CAPTURE_REQUIRED",
                    lambda s:s.update(profile_verified_before_and_after=False))


if __name__=="__main__":
    unittest.main()
