from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest
import test_exit_ack as fixtures
from exit_fills import reconcile_fixture_exit
from signature_checks import sign


class ExitFillTests(unittest.TestCase):
    def setUp(self):
        self.a=fixtures.ExitAckTests()
        self.a.setUp()
        self.addCleanup(self.a.doCleanups)
        self.a.submit_fixture()
        self.a.bind()
        self.pin=self.a.pin
        base=self.a.base.f.snapshot
        _,receipt=self.a.receipt()
        self.exit_order=receipt["body"]["data"]["order_ids"][0]
        self.snapshot=deepcopy(base)
        self.snapshot.update(snapshot_id="fixture-fill-capture",
            generated_at="2026-10-29T05:30:05+00:00",
            completed_at="2026-10-29T05:30:06+00:00")
        self.snapshot["orders"].append(dict(order_id=self.exit_order,
            instrument="NSE_FO|FIXTURE",product="I",side="SELL",quantity=65,
            filled=65,pending=0,status="FILLED",
            placed_at="2026-10-29T11:00:02+05:30"))
        self.snapshot["trades"].append(dict(order_id=self.exit_order,
            trade_id="fixture-exit-fill",instrument="NSE_FO|FIXTURE",
            product="I",side="SELL",quantity=65,price="101",
            filled_at="2026-10-29T11:00:04+05:30"))
        self.snapshot["positions"][0]["quantity"]=0

    def review(self,snapshot=None,**kwargs):
        s=deepcopy(self.snapshot if snapshot is None else snapshot)
        s.pop("signature",None);s["signature"]=sign(s,self.pin)
        args=dict(reference_path=self.a.path,adapter_path=self.a.adapterpath,
            pin=self.pin,snapshot=s,exit_id=self.a.exit_id,
            as_of="2026-10-29T05:30:07+00:00")
        args.update(kwargs)
        return reconcile_fixture_exit(**args)

    def test_full_exit_requires_explicit_flat_row_and_terminal_orders(self):
        r=self.review()
        self.assertTrue(r["fixture_flat_reference_verified"])
        self.assertEqual(r["remaining_quantity"],0)
        self.assertFalse(r["reservation_release_permission"])
        self.assertFalse(r["production_ready"])
        self.assertIsNone(r["net_pnl"])

    def test_partial_exit_retains_remaining_exposure(self):
        s=deepcopy(self.snapshot)
        s["orders"][1].update(status="PARTIAL",filled=30,pending=35)
        s["trades"][1]["quantity"]=30
        s["positions"][0]["quantity"]=35
        r=self.review(s)
        self.assertEqual(r["remaining_quantity"],35)
        self.assertFalse(r["fixture_flat_reference_verified"])

    def test_partial_cancel_is_not_flat(self):
        s=deepcopy(self.snapshot)
        s["orders"][1].update(status="CANCELLED",filled=30,pending=0)
        s["trades"][1]["quantity"]=30
        s["positions"][0]["quantity"]=35
        r=self.review(s)
        self.assertTrue(r["all_referenced_orders_terminal"])
        self.assertFalse(r["fixture_flat_reference_verified"])

    def test_missing_position_not_flat(self):
        s=dict(self.snapshot,positions=[])
        with self.assertRaisesRegex(ValueError,"MISSING_POSITION_ROW_IS_NOT_FLAT"):
            self.review(s)

    def test_position_mismatch_blocks(self):
        s=deepcopy(self.snapshot);s["positions"][0]["quantity"]=1
        with self.assertRaisesRegex(ValueError,"BROKER_POSITION_QUANTITY_MISMATCH"):
            self.review(s)

    def test_sell_cannot_borrow_future_buy_fill(self):
        s=deepcopy(self.snapshot)
        s["trades"][0]["quantity"]=30
        s["trades"].append(dict(s["trades"][0],trade_id="later-buy",
            quantity=35,filled_at="2026-10-29T11:00:05+05:30"))
        with self.assertRaisesRegex(ValueError,"EXIT_PRECEDES_AVAILABLE_ENTRY_FILLS"):
            self.review(s)

    def test_same_time_opposite_fills_require_review(self):
        s=deepcopy(self.snapshot)
        s["trades"][0]["filled_at"]=s["trades"][1]["filled_at"]
        with self.assertRaisesRegex(ValueError,"OPPOSITE_FILL_TIME_ORDER_AMBIGUOUS"):
            self.review(s)

    def test_previous_fill_cannot_disappear(self):
        self.review()
        s=deepcopy(self.snapshot);s["snapshot_id"]="second"
        s["trades"][1]["trade_id"]="replacement-exit"
        with self.assertRaisesRegex(ValueError,"PREVIOUS_FILL_CHANGED_OR_DISAPPEARED"):
            self.review(s)

    def test_previous_price_correction_requires_review(self):
        self.review()
        s=deepcopy(self.snapshot);s["snapshot_id"]="second"
        s["trades"][1]["price"]="102"
        with self.assertRaisesRegex(ValueError,"PREVIOUS_FILL_CHANGED_OR_DISAPPEARED"):
            self.review(s)

    def test_changed_snapshot_id_payload_rejected(self):
        self.review()
        s=deepcopy(self.snapshot);s["diagnostics"]={"changed":True}
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_ID_REUSED_WITH_CHANGED_EVIDENCE"):
            self.review(s)

    def test_identical_replay_does_not_duplicate_snapshots(self):
        self.review();self.review()
        with closing(sqlite3.connect(self.a.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM exit_fill_snapshots").fetchone()[0],1)

    def test_failure_rolls_back_state_and_snapshot(self):
        def fail(stage):
            if stage=="AFTER_STATE_WRITE":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):
            self.review(checkpoint=fail)
        with closing(sqlite3.connect(self.a.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='exit_fill_state'").fetchone())

    def test_unrelated_account_order_blocks(self):
        s=deepcopy(self.snapshot)
        s["orders"].append(dict(s["orders"][0],order_id="UNRELATED",filled=0,
                                pending=0,status="CANCELLED"))
        with self.assertRaisesRegex(ValueError,"MISSING_OR_UNLINKED_ACCOUNT_ORDER"):
            self.review(s)

    def test_adapter_unchanged_by_fill_reconciliation(self):
        before=self.a.adapterpath.read_bytes()
        self.review()
        self.assertEqual(before,self.a.adapterpath.read_bytes())

    def test_live_account_refused(self):
        with self.assertRaisesRegex(ValueError,"FIXTURE_ACCOUNT_REQUIRED"):
            self.review(pin=dict(self.pin,scope="UPSTOX:"+"a"*64))

    def test_rejected_parent_cannot_erase_filled_baseline(self):
        s=deepcopy(self.snapshot)
        s["orders"][0].update(status="REJECTED",filled=0,pending=0)
        s["orders"][1].update(status="REJECTED",filled=0,pending=0)
        s["trades"]=[]
        with self.assertRaisesRegex(ValueError,"PARENT_FILL_BASELINE_BELOW_EXIT_INTENT"):
            self.review(s)

    def test_unrelated_position_blocks(self):
        s=deepcopy(self.snapshot)
        s["positions"].append(dict(instrument="OTHER",product="I",quantity=1))
        with self.assertRaisesRegex(ValueError,"UNLINKED_ACCOUNT_EXPOSURE"):
            self.review(s)

    def test_stale_fill_capture_blocks(self):
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_STALE_OR_FUTURE"):
            self.review(as_of="2026-10-29T05:30:36+00:00")

    def test_tampered_fill_capture_signature_blocks(self):
        s=deepcopy(self.snapshot);s["signature"]=sign(s,self.pin)
        s["snapshot_id"]="tampered"
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_SIGNATURE_INVALID"):
            reconcile_fixture_exit(self.a.path,self.a.adapterpath,self.pin,s,
                self.a.exit_id,as_of="2026-10-29T05:30:07+00:00")

    def test_persisted_fill_state_tampering_blocks(self):
        self.review()
        with closing(sqlite3.connect(self.a.path)) as db,db:
            row=db.execute("SELECT data FROM exit_fill_state WHERE id=?",
                           (self.a.exit_id,)).fetchone()
            value=json.loads(row[0]);value["remaining_quantity"]=999
            db.execute("UPDATE exit_fill_state SET data=? WHERE id=?",
                       (json.dumps(value),self.a.exit_id))
        with self.assertRaisesRegex(ValueError,"PERSISTED_FILL_STATE_SIGNATURE_INVALID"):
            self.review()


if __name__=="__main__":
    unittest.main()
