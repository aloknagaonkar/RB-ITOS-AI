from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
import test_atomic_exit as fixtures
from adapter_reference.adapter import Store, Adapter, FixtureTransport, encode
from exit_ack import bind_fixture_ack


class ExitAckTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.AtomicExitTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.base.bind()
        self.pin=self.base.f.pin
        self.path=self.base.path
        self.adapterpath=self.base.f.f.adapter
        self.exit_id=self.base.reference["id"]
        # All data is synthetic. Use the supplied adapter's actual fake transport.
        with closing(sqlite3.connect(self.adapterpath)) as db,db:
            db.execute("UPDATE meta SET data=?",(encode(dict(
                scope=self.pin["scope"],mode="OFFLINE_FIXTURE")),))
        store=Store(self.adapterpath,self.pin["scope"],"OFFLINE_FIXTURE")
        self.transport=FixtureTransport(store)
        self.adapter=Adapter(store,self.transport)

    def submit_fixture(self):
        return self.adapter.submit(self.exit_id)

    def bind(self,**kwargs):
        args=dict(reference_path=self.path,adapter_path=self.adapterpath,
                  pin=self.pin,exit_id=self.exit_id,as_of=self.base.f.at)
        args.update(kwargs)
        return bind_fixture_ack(**args)

    def receipt(self):
        with closing(sqlite3.connect(self.adapterpath)) as db:
            row=db.execute("SELECT receipts.id,receipts.data FROM receipts JOIN attempts "
                "ON attempts.id=receipts.id WHERE attempts.request_id=?",
                (self.exit_id,)).fetchone()
            return row[0],json.loads(row[1])

    def change_receipt(self,edit):
        key,value=self.receipt();edit(value)
        with closing(sqlite3.connect(self.adapterpath)) as db,db:
            db.execute("UPDATE receipts SET data=? WHERE id=?",(json.dumps(value),key))

    def ack_count(self):
        with closing(sqlite3.connect(self.path)) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='exit_acknowledgements'").fetchone()
            return db.execute("SELECT COUNT(*) FROM exit_acknowledgements").fetchone()[0] if exists else 0

    def test_acknowledgement_never_confirms_fill_or_flatness(self):
        self.submit_fixture()
        r=self.bind()
        self.assertEqual(self.ack_count(),1)
        for key in ("fill_confirmed","flat_confirmed","retry_allowed",
                    "production_execution_enabled","reservation_release_permission"):
            self.assertIs(r[key],False)

    def test_replay_is_idempotent(self):
        self.submit_fixture();self.bind()
        self.assertTrue(self.bind()["idempotent_replay"])
        self.assertEqual(self.ack_count(),1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM exit_ack_events").fetchone()[0],1)

    def test_unsubmitted_exit_is_not_adopted(self):
        with self.assertRaisesRegex(ValueError,"EXIT_ACKNOWLEDGEMENT_UNRESOLVED_NO_RETRY"):
            self.bind()
        self.assertEqual(self.ack_count(),0)

    def test_split_ack_stays_unresolved(self):
        self.transport.split_ack=True
        self.submit_fixture()
        with self.assertRaisesRegex(ValueError,"EXIT_ACKNOWLEDGEMENT_UNRESOLVED_NO_RETRY"):
            self.bind()

    def test_missing_receipt_rejected(self):
        self.submit_fixture()
        key,_=self.receipt()
        with closing(sqlite3.connect(self.adapterpath)) as db,db:
            db.execute("DELETE FROM receipts WHERE id=?",(key,))
        with self.assertRaisesRegex(ValueError,"DURABLE_PLACE_RECEIPT_REQUIRED"):
            self.bind()

    def test_wrong_receipt_origin_rejected(self):
        self.submit_fixture()
        self.change_receipt(lambda r:r.update(origin="LOCAL_HTTP_TRANSPORT"))
        with self.assertRaisesRegex(ValueError,"RECEIPT_PROVENANCE_MISMATCH"):
            self.bind()

    def test_boolean_http_status_rejected(self):
        self.submit_fixture()
        self.change_receipt(lambda r:r.update(http_status=True))
        with self.assertRaisesRegex(ValueError,"SUCCESSFUL_PLACE_RECEIPT_REQUIRED"):
            self.bind()

    def test_wrong_order_ack_rejected(self):
        self.submit_fixture()
        self.change_receipt(lambda r:r.update(body=dict(
            status="success",data={"order_ids":["OTHER-ORDER"]})))
        with self.assertRaisesRegex(ValueError,"ACK_ORDER_BINDING_MISMATCH"):
            self.bind()

    def test_wrong_wire_fingerprint_rejected(self):
        self.submit_fixture()
        self.change_receipt(lambda r:r.update(wire_fingerprint="changed"))
        with self.assertRaisesRegex(ValueError,"RECEIPT_PROVENANCE_MISMATCH"):
            self.bind()

    def test_timeout_without_receipt_not_retried(self):
        self.transport.timeout_after=True
        self.submit_fixture()
        before=self.base.counts()
        with self.assertRaisesRegex(ValueError,"EXIT_ACKNOWLEDGEMENT_UNRESOLVED_NO_RETRY"):
            self.bind()
        self.assertEqual(before,self.base.counts())

    def test_rollback_after_ack_insert(self):
        self.submit_fixture()
        def fail(stage):
            if stage=="AFTER_ACK_INSERT":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):
            self.bind(checkpoint=fail)
        self.assertEqual(self.ack_count(),0)

    def test_rollback_before_commit(self):
        self.submit_fixture()
        def fail(stage):
            if stage=="BEFORE_COMMIT":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):
            self.bind(checkpoint=fail)
        self.assertEqual(self.ack_count(),0)

    def test_binding_does_not_change_adapter_or_call_transport(self):
        self.submit_fixture()
        before=self.adapterpath.read_bytes()
        with patch.object(self.transport,"send",side_effect=AssertionError("No send")):
            self.bind()
        self.assertEqual(before,self.adapterpath.read_bytes())

    def test_live_scope_rejected(self):
        with self.assertRaisesRegex(ValueError,"FIXTURE_ACCOUNT_REQUIRED"):
            self.bind(pin=dict(self.pin,scope="UPSTOX:"+"a"*64))

    def test_next_session_ack_not_silently_adopted(self):
        self.submit_fixture()
        with self.assertRaisesRegex(ValueError,"ACK_BINDING_SESSION_OR_TIME_INVALID"):
            self.bind(as_of="2026-10-30T05:30:02+00:00")


if __name__=="__main__":
    unittest.main()
