from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
import test_bridge as fixtures
from adapter_reference.adapter import Store
from handoff import prepare_fixture_execution
from historical_receipt_checks import sha
from risk_evidence_audit import FLAGS,read_sources
from signature_checks import sign


class HandoffTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.BridgeTests();f.setUp();self.f=f;self.addCleanup(f.doCleanups)
        self.pin=f.pin;self.now="2026-10-29T05:30:02+00:00"
        request=f.f.request()
        request.update(order_id=None,state="PREPARED")
        request["draft"]["created_at"]=self.now
        request["draft"]["body"].update(validity="DAY",tag="fixture-entry",
            disclosed_quantity=0,trigger_price=0,is_amo=False,slice=False)
        request["draft"]["fingerprint"]=sha(request["draft"]["body"])
        f.f.set_request(request)
        out=f.f.get(f.f.app,"preparation_outbox","p1")
        out["disabled_request_candidate"]["draft"]=deepcopy(request["draft"])
        f.f.put(f.f.app,"preparation_outbox","p1",out)
        binding=f.f.get(f.f.app,"preparation_request_bindings","p1")
        stable={k:request[k] for k in ("request_id","draft","signal_id",
            "signal_at","direction","reservation_reference")}
        binding.update(request_fingerprint=sha(stable),outbox_fingerprint=sha(out))
        f.f.put(f.f.app,"preparation_request_bindings","p1",binding)
        with closing(sqlite3.connect(f.f.adapter)) as db,db:
            db.execute("DELETE FROM attempts");db.execute("DELETE FROM receipts")
            db.execute("UPDATE meta SET data=?",(json.dumps(dict(
                scope=self.pin["scope"],mode="LIVE_CLOSED")),))
        self.source=read_sources(f.f.app,f.f.adapter,self.pin["scope"])
        self.reservation=dict({k:False for k in FLAGS},
            model="HILEGA_APPLICATION_LOCAL_CASH_RESERVATION_V1",
            id="p1",account_scope=self.pin["scope"],state="RESERVED_DISABLED_REQUEST",
            request_fingerprint=sha(stable),plan_fingerprint=binding["plan_fingerprint"],
            shadow_hold_fingerprint=binding["hold_fingerprint"],
            outbox_fingerprint=binding["outbox_fingerprint"],
            amount_cents=10000,held_cents=10000,cash_cap_cents=20000,
            broker_cash_locked=False,policy=dict(allocation_numerator=1,allocation_denominator=2,
                daily_loss_limit_required=False,daily_loss_limit_paise=None,
                fixed_max_entry_cost_paise=None))
        self.reservation["signature"]=sign(self.reservation,self.pin)
        self.store=Store(f.f.app.parent/"separate-fixture.sqlite",self.pin["scope"],"OFFLINE_FIXTURE")

    def handoff(self,**kwargs):
        args=dict(source=self.source,reservation=self.reservation,
                  pin=self.pin,fixture_store=self.store,as_of=self.now)
        args.update(kwargs)
        return prepare_fixture_execution(**args)

    def test_handoff_prepares_only_separate_fixture_request(self):
        before=[p.read_bytes() for p in (self.f.f.app,self.f.f.adapter)]
        adapter,key=self.handoff()
        self.assertEqual(key,"p1")
        self.assertEqual(adapter.store.mode,"OFFLINE_FIXTURE")
        self.assertEqual(before,[p.read_bytes() for p in (self.f.f.app,self.f.f.adapter)])
        with adapter.store.tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],0)

    def test_live_pin_refused(self):
        with self.assertRaisesRegex(ValueError,"SYNTHETIC_FIXTURE_SCOPE_REQUIRED"):
            self.handoff(pin=dict(self.pin,scope="UPSTOX:"+"a"*64))

    def test_closed_store_cannot_become_fixture_transport(self):
        store=Store(self.f.f.app.parent/"closed.sqlite",self.pin["scope"],"LIVE_CLOSED")
        with self.assertRaisesRegex(ValueError,"SEPARATE_FIXTURE_STORE_REQUIRED"):
            self.handoff(fixture_store=store)

    def test_tampered_reservation_refused(self):
        bad=deepcopy(self.reservation);bad["held_cents"]=1
        with self.assertRaisesRegex(ValueError,"APPLICATION_RESERVATION_SIGNATURE_INVALID"):
            self.handoff(reservation=bad)

    def test_unknown_outcome_cannot_handoff(self):
        bad=deepcopy(self.reservation);bad["state"]="UNKNOWN_HOLD_RETAINED"
        bad.pop("signature");bad["signature"]=sign(bad,self.pin)
        with self.assertRaisesRegex(ValueError,"APPLICATION_RESERVATION_REFERENCE_MISMATCH"):
            self.handoff(reservation=bad)

    def test_missing_daily_limit_is_accepted(self):
        self.handoff()
        self.assertEqual(len(self.store.requests()),1)

    def test_repeat_handoff_does_not_duplicate(self):
        self.handoff();self.handoff()
        self.assertEqual(len(self.store.requests()),1)

    def test_changed_binding_is_not_handed_off(self):
        bad=deepcopy(self.source);bad["bindings"]["p1"]["plan_fingerprint"]="changed"
        with self.assertRaises(ValueError):self.handoff(source=bad)


if __name__=="__main__":
    unittest.main()
