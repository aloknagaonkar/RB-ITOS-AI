from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest
from atomic_exit_binding import bind_fixture_exit
from exit_intent import ReferenceStore
from historical_receipt_checks import sha
import test_exit_intent as fixtures


class AtomicExitTests(unittest.TestCase):
    def setUp(self):
        self.e=fixtures.ExitIntentTests()
        self.e.setUp()
        self.addCleanup(self.e.doCleanups)
        self.f=self.e.f
        with closing(sqlite3.connect(self.f.f.adapter)) as db:
            db.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL)")
        self.path=self.e.path
        ReferenceStore.create(self.path,self.f.pin)
        self.reference=self.e.reference()
        self.draft=self.make_draft(self.reference)

    def make_draft(self,ref):
        body=dict(quantity=ref["quantity"],product="I",validity="DAY",price=100,
            tag="fixture-exit",instrument_token=ref["instrument"],
            order_type="LIMIT",transaction_type="SELL",disclosed_quantity=0,
            trigger_price=0,is_amo=False,slice=False)
        return dict(model="HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1",
            request_id=ref["id"],created_at=self.f.at,documented_method="POST",
            documented_host="api-hft.upstox.com",documented_path="/v3/order/place",
            body=body,fingerprint=sha(body),submission_enabled=False,
            entry_permission=False,orders_sent=False)

    def bind(self,**kwargs):
        args=dict(reference_path=self.path,adapter_path=self.f.f.adapter,
            pin=self.f.pin,reference=self.reference,draft=self.draft,
            direction="BULLISH",as_of=self.f.at)
        args.update(kwargs)
        return bind_fixture_exit(**args)

    def counts(self):
        with closing(sqlite3.connect(self.path)) as a,closing(sqlite3.connect(self.f.f.adapter)) as b:
            return (a.execute("SELECT COUNT(*) FROM exit_references").fetchone()[0],
                    b.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
                    b.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    b.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
                    b.execute("SELECT COUNT(*) FROM receipts").fetchone()[0])

    def test_both_references_commit_without_transport_attempt(self):
        before=self.counts()
        r=self.bind()
        after=self.counts()
        self.assertEqual(after,(1,before[1]+1,before[2]+1,before[3],before[4]))
        self.assertFalse(r["production_execution_enabled"])
        self.assertFalse(r["orders_sent"])

    def test_replay_does_not_duplicate(self):
        self.bind();before=self.counts()
        self.assertTrue(self.bind()["idempotent_replay"])
        self.assertEqual(self.counts(),before)

    def test_rollback_after_exit_insert(self):
        before=self.counts()
        def fail(stage):
            if stage=="AFTER_EXIT_REFERENCE":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):self.bind(checkpoint=fail)
        self.assertEqual(self.counts(),before)

    def test_rollback_after_adapter_insert(self):
        before=self.counts()
        def fail(stage):
            if stage=="AFTER_ADAPTER_REQUEST":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):self.bind(checkpoint=fail)
        self.assertEqual(self.counts(),before)

    def test_rollback_before_commit(self):
        before=self.counts()
        def fail(stage):
            if stage=="BEFORE_COMMIT":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):self.bind(checkpoint=fail)
        self.assertEqual(self.counts(),before)

    def test_live_account_refused_before_database_access(self):
        with self.assertRaisesRegex(ValueError,"FIXTURE_ACCOUNT_REQUIRED"):
            self.bind(pin=dict(self.f.pin,scope="UPSTOX:"+"a"*64))

    def test_live_closed_adapter_not_mutated(self):
        with closing(sqlite3.connect(self.f.f.adapter)) as db,db:
            db.execute("UPDATE meta SET data=?",(json.dumps(dict(
                scope=self.f.pin["scope"],mode="LIVE_CLOSED")),))
        before=self.counts()
        with self.assertRaisesRegex(ValueError,"FIXTURE_ADAPTER_REQUIRED"):self.bind()
        self.assertEqual(self.counts(),before)

    def test_wrong_exit_quantity_refused(self):
        draft=deepcopy(self.draft);draft["body"]["quantity"]=66
        draft["fingerprint"]=sha(draft["body"])
        with self.assertRaisesRegex(ValueError,"EXIT_REQUEST_CONTRACT_MISMATCH"):
            self.bind(draft=draft)

    def test_changed_replay_body_refused(self):
        self.bind()
        draft=deepcopy(self.draft);draft["body"]["price"]=99
        draft["fingerprint"]=sha(draft["body"])
        with self.assertRaisesRegex(ValueError,"ATOMIC_EXIT_BINDING_CONFLICT"):
            self.bind(draft=draft)

    def test_second_exit_for_parent_refused(self):
        ref=self.e.reference(exit_key="second-exit")
        self.bind()
        with self.assertRaisesRegex(ValueError,"PENDING_EXIT_REFERENCE_ALREADY_EXISTS"):
            self.bind(reference=ref,draft=self.make_draft(ref))

    def test_stale_exit_refused(self):
        with self.assertRaisesRegex(ValueError,"EXIT_REFERENCE_STALE_OR_FUTURE"):
            self.bind(as_of="2026-10-29T05:30:13+00:00")

    def test_parent_request_change_refused(self):
        with closing(sqlite3.connect(self.f.f.adapter)) as db,db:
            db.execute("UPDATE requests SET fingerprint='changed' WHERE id='p1'")
        with self.assertRaisesRegex(ValueError,"PARENT_REQUEST_CHANGED_OR_MISSING"):
            self.bind()

    def test_existing_separate_reference_not_silently_adopted(self):
        ReferenceStore(self.path,self.f.pin).record(self.reference,as_of=self.f.at)
        before=self.counts()
        with self.assertRaisesRegex(ValueError,"PENDING_EXIT_REFERENCE_ALREADY_EXISTS"):
            self.bind()
        self.assertEqual(self.counts(),before)

    def test_application_source_unchanged(self):
        before=self.f.f.app.read_bytes()
        self.bind()
        self.assertEqual(before,self.f.f.app.read_bytes())

    def test_symlink_rejected(self):
        link=self.path.parent/"linked.sqlite";link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,"REGULAR_EXISTING_SOURCE_REQUIRED"):
            self.bind(reference_path=link)


if __name__=="__main__":
    unittest.main()
