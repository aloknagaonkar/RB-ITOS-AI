from copy import deepcopy
from pathlib import Path
import sqlite3
from contextlib import closing
import unittest
import test_bridge as fixtures
from signature_checks import sign
from exit_intent import create_reference, ReferenceStore


class ExitIntentTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BridgeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture
        self.path=self.f.f.app.parent/"isolated-exit.sqlite"

    def reference(self, *, quantity=65,exit_key="fixture-exit",snapshot=None):
        s=deepcopy(self.f.snapshot if snapshot is None else snapshot)
        s["signature"]=sign(s,self.f.pin)
        return create_reference(self.f.source(),s,self.f.pin,
            entry_request_id="p1",exit_key=exit_key,quantity=quantity,
            reason="FIXTURE_STRATEGY_EXIT",as_of=self.f.at)

    def test_build_never_creates_executable_request(self):
        r=self.reference()
        self.assertEqual(r["side"],"SELL")
        self.assertEqual(r["parent_request_id"],"p1")
        for flag in ("orders_sent","production_execution_enabled",
                     "strategy_ownership_verified","executable_request_created",
                     "reservation_release_permission","production_ready"):
            self.assertIs(r[flag],False)
        self.assertNotIn("body",r)

    def test_reopen_preserves_exit_intent(self):
        store=ReferenceStore.create(self.path,self.f.pin)
        r=self.reference()
        self.assertFalse(store.record(r,as_of=self.f.at)["idempotent_replay"])
        reopened=ReferenceStore(self.path,self.f.pin)
        self.assertTrue(reopened.record(r,as_of=self.f.at)["idempotent_replay"])

    def test_changed_exit_key_payload_rejected(self):
        store=ReferenceStore.create(self.path,self.f.pin)
        store.record(self.reference(),as_of=self.f.at)
        with self.assertRaisesRegex(ValueError,"EXIT_KEY_REUSED_WITH_CHANGED_INTENT"):
            store.record(self.reference(quantity=30),as_of=self.f.at)

    def test_second_pending_exit_for_parent_blocked(self):
        store=ReferenceStore.create(self.path,self.f.pin)
        store.record(self.reference(),as_of=self.f.at)
        with self.assertRaisesRegex(ValueError,"PENDING_EXIT_REFERENCE_ALREADY_EXISTS"):
            store.record(self.reference(exit_key="second-exit"),as_of=self.f.at)

    def test_exit_cannot_exceed_filled_parent(self):
        with self.assertRaisesRegex(ValueError,"EXIT_EXCEEDS_PARENT_FILLED_QUANTITY"):
            self.reference(quantity=66)

    def test_boolean_or_zero_exit_quantity_rejected(self):
        for q in (True,0,-1,"65"):
            with self.subTest(quantity=q):
                with self.assertRaisesRegex(ValueError,"EXIT_QUANTITY_INVALID"):
                    self.reference(quantity=q)

    def test_missing_position_prevents_exit_reference(self):
        with self.assertRaisesRegex(ValueError,"CURRENT_ENTRY_POSITION_REFERENCE_REQUIRED"):
            self.reference(snapshot=dict(self.f.snapshot,positions=[]))

    def test_partial_open_entry_prevents_exit_reference(self):
        s=deepcopy(self.f.snapshot)
        s["orders"][0].update(status="PARTIAL",filled=30,pending=35)
        s["trades"][0]["quantity"]=30
        s["positions"][0]["quantity"]=30
        with self.assertRaisesRegex(ValueError,"CURRENT_ENTRY_POSITION_REFERENCE_REQUIRED"):
            self.reference(snapshot=s,quantity=30)

    def test_partial_cancel_uses_actual_fill_quantity(self):
        s=deepcopy(self.f.snapshot)
        s["orders"][0].update(status="CANCELLED",filled=30,pending=0)
        s["trades"][0]["quantity"]=30
        s["positions"][0]["quantity"]=30
        self.assertEqual(self.reference(snapshot=s,quantity=30)["quantity"],30)
        with self.assertRaisesRegex(ValueError,"EXIT_EXCEEDS_PARENT_FILLED_QUANTITY"):
            self.reference(snapshot=s,quantity=31)

    def test_tampered_reference_rejected(self):
        store=ReferenceStore.create(self.path,self.f.pin)
        r=self.reference();r["quantity"]=1
        with self.assertRaisesRegex(ValueError,"EXIT_REFERENCE_SIGNATURE_INVALID"):
            store.record(r,as_of=self.f.at)

    def test_expired_reference_rejected_before_write(self):
        store=ReferenceStore.create(self.path,self.f.pin)
        with self.assertRaisesRegex(ValueError,"EXIT_REFERENCE_STALE_OR_FUTURE"):
            store.record(self.reference(),as_of="2026-10-29T05:30:13+00:00")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM exit_references").fetchone()[0],0)

    def test_existing_database_never_overwritten(self):
        self.path.write_bytes(b"UNRELATED")
        with self.assertRaises(FileExistsError):
            ReferenceStore.create(self.path,self.f.pin)
        self.assertEqual(self.path.read_bytes(),b"UNRELATED")

    def test_wrong_account_cannot_open_store(self):
        ReferenceStore.create(self.path,self.f.pin)
        pin=dict(self.f.pin,scope="FIXTURE:OTHER")
        with self.assertRaisesRegex(ValueError,"EXIT_REFERENCE_STORE_SCOPE_OR_MODE_MISMATCH"):
            ReferenceStore(self.path,pin)

    def test_application_and_adapter_databases_unchanged(self):
        paths=(self.f.f.app,self.f.f.adapter)
        before=[p.read_bytes() for p in paths]
        store=ReferenceStore.create(self.path,self.f.pin)
        store.record(self.reference(),as_of=self.f.at)
        self.assertEqual(before,[p.read_bytes() for p in paths])

    def test_unknown_existing_store_is_not_adopted(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE unrelated(id INTEGER)")
        before=self.path.read_bytes()
        with self.assertRaises(sqlite3.OperationalError):
            ReferenceStore(self.path,self.f.pin)
        self.assertEqual(before,self.path.read_bytes())


if __name__=="__main__":
    unittest.main()
