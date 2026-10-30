from contextlib import closing
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from allocation import POLICY,ReservationBook,sizing
from signature_checks import sign


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"book.sqlite"
        self.pin=dict(scope="FIXTURE:HALF-CASH",key="11"*32)
        self.now=datetime(2026,10,29,5,30,2,tzinfo=timezone.utc)
        self.proposal=dict(instrument="NSE_FO|FIXTURE",limit_price_paise=100,
            lot_size=100,freeze_quantity=1000,fee_buffer_paise=1000)
        self.capture=dict(model="HILEGA_READ_ONLY_CASH_OBSERVATION_V1",
            evidence_mode="LIVE_READ_ONLY_ACCOUNT_PINNED",account_scope=self.pin["scope"],
            status="READ_ONLY_CAPTURED",account_identity_verified=True,
            account_position_rows_complete=True,snapshot_id="fixture-cash",
            started_at="2026-10-29T05:30:00+00:00",
            completed_at="2026-10-29T05:30:01+00:00",session_date="2026-10-29",
            funds_before=dict(field="data.available_to_trade.cash_available_to_trade.total",
                              cash_available_to_trade="1000",cash_margin_used="0"),
            funds_after=dict(field="data.available_to_trade.cash_available_to_trade.total",
                             cash_available_to_trade="1000",cash_margin_used="0"),
            funds_changed_during_capture=False,orders=[],trades=[],positions=[],
            diagnostics=dict(issues=[]),production_execution_enabled=False,
            orders_sent=False,entry_permission=False)

    def signed(self,capture=None):
        value=deepcopy(self.capture if capture is None else capture)
        value.pop("signature",None);value["signature"]=sign(value,self.pin)
        return value

    def sized(self,capture=None,**kwargs):
        proposal=dict(self.proposal);proposal.update(kwargs)
        return sizing(self.signed(capture),self.pin,as_of=self.now.isoformat(),**proposal)

    def book(self):return ReservationBook.create(self.path,self.pin)
    def reserve(self,book,key="plan",**kwargs):
        proposal=dict(self.proposal);proposal.update(kwargs)
        return book.reserve(key,self.signed(),clock=lambda:self.now,**proposal)

    def test_daily_loss_limit_deliberately_unconfigured(self):
        r=self.sized()
        self.assertIsNone(r["policy"]["daily_loss_limit_paise"])
        self.assertFalse(r["daily_loss_limit_required"])
        self.assertTrue(r["within_half_cash_cap"])

    def test_cap_is_exactly_half_cash(self):
        r=self.sized()
        self.assertEqual(r["available_cash_paise"],100000)
        self.assertEqual(r["half_cash_cap_paise"],50000)

    def test_fee_buffer_is_included(self):
        self.assertEqual(self.sized()["proposed_total_paise"],11000)

    def test_exact_cap_boundary_fits(self):
        c=deepcopy(self.capture)
        for k in ("funds_before","funds_after"):c[k]["cash_available_to_trade"]="220"
        self.assertTrue(self.sized(c)["within_half_cash_cap"])

    def test_one_paise_short_blocks(self):
        c=deepcopy(self.capture)
        for k in ("funds_before","funds_after"):c[k]["cash_available_to_trade"]="219.99"
        self.assertFalse(self.sized(c)["within_half_cash_cap"])

    def test_odd_cash_paise_floors_half_cap(self):
        c=deepcopy(self.capture)
        for k in ("funds_before","funds_after"):c[k]["cash_available_to_trade"]="1000.01"
        self.assertEqual(self.sized(c)["half_cash_cap_paise"],50000)

    def test_zero_cash_blocks(self):
        c=deepcopy(self.capture)
        for k in ("funds_before","funds_after"):c[k]["cash_available_to_trade"]="0"
        r=self.sized(c)
        self.assertEqual(r["quantity"],0)
        self.assertIn("NO_CASH_CAPACITY",r["reasons"])

    def test_whole_lot_only(self):
        r=self.sized()
        self.assertEqual(r["quantity"]%self.proposal["lot_size"],0)

    def test_current_one_lot_limit_preserved(self):
        r=self.sized()
        self.assertEqual(r["lots"],1)
        with self.assertRaisesRegex(ValueError,"INITIAL_ONE_LOT_POLICY_REQUIRED"):
            self.sized(max_lots=2)

    def test_freeze_below_one_lot_blocks(self):
        self.assertFalse(self.sized(freeze_quantity=99)["within_half_cash_cap"])

    def test_boolean_and_noninteger_inputs_rejected(self):
        for field in ("limit_price_paise","lot_size","freeze_quantity","fee_buffer_paise"):
            for value in (True,0,-1,1.5,"100"):
                with self.subTest(field=field,value=value):
                    with self.assertRaises(ValueError):self.sized(**{field:value})

    def test_stale_cash_rejected(self):
        self.now=datetime(2026,10,29,5,30,32,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):self.sized()

    def test_old_sweep_start_with_recent_end_rejected(self):
        c=deepcopy(self.capture);c["started_at"]="2026-10-29T05:29:32+00:00"
        self.now=datetime(2026,10,29,5,30,30,tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError,"CASH_SWEEP_START_STALE_OR_FUTURE"):
            self.sized(c)

    def test_cash_drift_blocks(self):
        c=deepcopy(self.capture);c["funds_after"]["cash_available_to_trade"]="900"
        self.assertFalse(self.sized(c)["within_half_cash_cap"])

    def test_account_activity_remains_blocked_without_ownership(self):
        c=deepcopy(self.capture);c["orders"]=[{"fixture":True}]
        self.assertFalse(self.sized(c)["within_half_cash_cap"])

    def test_wrong_account_rejected(self):
        c=deepcopy(self.capture);c["account_scope"]="FIXTURE:OTHER"
        with self.assertRaisesRegex(ValueError,"ACCOUNT_SCOPE_UNVERIFIED"):self.sized(c)

    def test_signature_tamper_rejected(self):
        c=self.signed();c["snapshot_id"]="changed"
        with self.assertRaisesRegex(ValueError,"CAPTURE_SIGNATURE_INVALID"):
            sizing(c,self.pin,as_of=self.now.isoformat(),**self.proposal)

    def test_hold_survives_reopen(self):
        self.reserve(self.book())
        r=self.reserve(ReservationBook(self.path,self.pin))
        self.assertTrue(r["idempotent_replay"])
        self.assertEqual(r["held_paise"],11000)

    def test_replay_does_not_duplicate(self):
        b=self.book();self.reserve(b);self.reserve(b)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM holds").fetchone()[0],1)

    def test_changed_same_plan_conflicts(self):
        b=self.book();self.reserve(b)
        with self.assertRaisesRegex(ValueError,"RESERVATION_PLAN_CONFLICT"):
            self.reserve(b,limit_price_paise=101)

    def test_second_active_entry_blocked(self):
        b=self.book();self.reserve(b)
        with self.assertRaisesRegex(ValueError,"EXISTING_LOCAL_RESERVATION_REQUIRES_REVIEW"):
            self.reserve(b,key="second")

    def test_unknown_outcome_retains_hold(self):
        b=self.book();self.reserve(b)
        r=b.mark_unknown("plan");self.assertEqual(r["held_paise"],11000)
        with self.assertRaisesRegex(ValueError,"EXISTING_LOCAL_RESERVATION_REQUIRES_REVIEW"):
            self.reserve(b,key="second")

    def test_fault_rolls_back_hold_and_audit(self):
        b=self.book()
        def fail(stage):
            if stage=="AFTER_HOLD_INSERT":raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):
            b.reserve("plan",self.signed(),clock=lambda:self.now,
                      checkpoint=fail,**self.proposal)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM holds").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM allocation_events").fetchone()[0],0)

    def test_concurrent_entries_cannot_overlap(self):
        self.book()
        def attempt(key):
            try:
                self.reserve(ReservationBook(self.path,self.pin),key=key)
                return "reserved"
            except ValueError:return "blocked"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,("first","second")))
        self.assertEqual(sorted(results),["blocked","reserved"])

    def test_freshness_rechecked_after_database_wait(self):
        b=self.book()
        old=datetime(2026,10,29,5,30,40,tzinfo=timezone.utc)
        times=iter([self.now,old])
        with self.assertRaises(ValueError):
            b.reserve("plan",self.signed(),clock=lambda:next(times),**self.proposal)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM holds").fetchone()[0],0)

    def test_existing_file_never_overwritten(self):
        self.path.write_bytes(b"unrelated")
        with self.assertRaises(FileExistsError):self.book()
        self.assertEqual(self.path.read_bytes(),b"unrelated")

    def test_wrong_book_scope_rejected(self):
        self.book()
        with self.assertRaisesRegex(ValueError,"BOOK_SCOPE_OR_POLICY_MISMATCH"):
            ReservationBook(self.path,dict(self.pin,scope="FIXTURE:OTHER"))

    def test_tampered_hold_cannot_free_capacity(self):
        b=self.book();self.reserve(b)
        with closing(sqlite3.connect(self.path)) as db,db:
            row=json.loads(db.execute("SELECT data FROM holds").fetchone()[0])
            row["held_paise"]=0
            db.execute("UPDATE holds SET data=?",(json.dumps(row),))
        with self.assertRaisesRegex(ValueError,"LOCAL_HOLD_SIGNATURE_INVALID"):
            self.reserve(b,key="second")

    def test_no_broker_or_release_authority(self):
        r=self.reserve(self.book())
        for field in ("broker_cash_locked","entry_permission",
                      "production_execution_enabled","reservation_release_permission"):
            self.assertIs(r[field],False)

    def test_inputs_unchanged(self):
        before=deepcopy((self.capture,self.pin,self.proposal))
        self.sized()
        self.assertEqual((self.capture,self.pin,self.proposal),before)


if __name__=="__main__":
    unittest.main()
