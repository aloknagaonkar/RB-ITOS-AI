from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
import sqlite3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from hilega_daily_loss_latch_v1 import FixtureLatch,MODEL
from hilega_daily_loss_review_v1 import POLICY,ReviewBlocked

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'isolated-fixture.sqlite'
        self.at=datetime.fromisoformat('2026-10-29T11:00:00+05:30')
        self.config=dict(account_scope='FIXTURE:A',session_date='2026-10-29',loss_accounting_policy=POLICY,
            policy_approved=True,daily_loss_limit_paise=100000,max_entry_cost_paise=50000,max_pnl_age_seconds=30)
        self.evidence=dict(account_scope='FIXTURE:A',session_date='2026-10-29',pnl_attribution_verified=True,
            fees_complete=True,positions_reconciled=True,requests_reconciled=True,daily_stop_latched=False,
            open_position_count=0,pending_request_count=0,unresolved_outcome=False,observed_at=self.at.isoformat(),
            realized_net_pnl_paise=-10000,open_net_pnl_paise=0)
        self.candidate=dict(account_scope='FIXTURE:A',session_date='2026-10-29',transaction_type='BUY',
            instrument_type='CE',pricing_policy_approved=True,cost_includes_fees=True,max_loss_cost_paise=20000)
        self.store=FixtureLatch.create(self.path);self.store.initialize(self.config,as_of=self.at)
    def record(self,rid='review-1',store=None):
        return (store or self.store).record(self.config,self.evidence,self.candidate,as_of=self.at,request_id=rid)
    def trip(self):
        self.evidence['realized_net_pnl_paise']=-100000
        return self.record('trip')
    def closure(self):
        return dict(account_scope='FIXTURE:A',previous_session_date='2026-10-29',
            previous_session_reconciled=True,positions_reconciled=True,requests_reconciled=True,
            fees_complete=True,open_position_count=0,pending_request_count=0,unresolved_outcome=False,
            observed_at=(self.at+timedelta(days=1)).isoformat())
    def new_config(self):return dict(self.config,session_date='2026-10-30')
    def test_review_never_grants_authority(self):
        result=self.record();self.assertEqual(result['status'],'REVIEWED_ONLY')
        for k in ('entry_permission','production_ready','production_execution_enabled','orders_sent','evidence_authenticated_by_this_module'):
            self.assertIs(result[k],False)
    def test_latch_persists_after_reopen(self):
        self.trip();self.assertTrue(FixtureLatch(self.path).state('FIXTURE:A')['latched'])
    def test_recovered_pnl_does_not_clear_latch(self):
        self.trip();self.evidence['realized_net_pnl_paise']=50000
        result=self.record('recovered');self.assertTrue(result['current_durable_stop_latched'])
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['remaining_loss_budget_paise'],0)
    def test_highwater_does_not_restore_budget_before_trip(self):
        self.evidence['realized_net_pnl_paise']=-70000;self.record('loss')
        self.evidence['realized_net_pnl_paise']=0
        self.assertEqual(self.record('recovered')['remaining_loss_budget_paise'],30000)
    def test_candidate_cost_uses_persisted_highwater(self):
        self.evidence['realized_net_pnl_paise']=-90000;self.record('loss')
        self.evidence['realized_net_pnl_paise']=0
        self.assertIn('REMAINING_LOSS_BUDGET_EXCEEDED',self.record('next')['reasons'])
    def test_no_same_session_reinitialize(self):
        self.trip()
        with self.assertRaisesRegex(ReviewBlocked,'ACCOUNT_ALREADY_INITIALIZED'):self.store.initialize(self.config,as_of=self.at)
        self.assertTrue(self.store.state('FIXTURE:A')['latched'])
    def test_policy_cannot_be_raised_after_trip(self):
        self.trip();self.config['daily_loss_limit_paise']=999999
        with self.assertRaisesRegex(ReviewBlocked,'SESSION_POLICY_IMMUTABLE'):self.record('changed')
        self.assertTrue(self.store.state('FIXTURE:A')['latched'])
    def test_day_change_needs_explicit_rollover(self):
        self.trip();self.at+=timedelta(days=1);self.config['session_date']='2026-10-30'
        with self.assertRaisesRegex(ReviewBlocked,'EXPLICIT_SESSION_ROLLOVER_REQUIRED'):self.record('tomorrow')
    def test_rollover_reconciled_fixture_is_explicit_and_keeps_history(self):
        self.trip();state=self.store.rollover(self.new_config(),self.closure(),as_of=self.at+timedelta(days=1))
        self.assertFalse(state['latched']);self.assertEqual(state['highwater'],0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT latched FROM sessions WHERE session=?',('2026-10-29',)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],2)
    def test_same_session_rollover_rejected(self):
        with self.assertRaisesRegex(ReviewBlocked,'SAME_OR_PRIOR_SESSION_RESET_FORBIDDEN'):
            self.store.rollover(self.config,self.closure(),as_of=self.at)
    def test_nonflat_rollover_rejected(self):
        closure=self.closure();closure['open_position_count']=1
        with self.assertRaisesRegex(ReviewBlocked,'CLOSURE_NOT_FLAT'):
            self.store.rollover(self.new_config(),closure,as_of=self.at+timedelta(days=1))
    def test_unknown_reconciliation_rollover_rejected(self):
        closure=self.closure();closure['previous_session_reconciled']=None
        with self.assertRaisesRegex(ReviewBlocked,'CLOSURE_RECONCILIATION_REQUIRED'):
            self.store.rollover(self.new_config(),closure,as_of=self.at+timedelta(days=1))
    def test_pending_rollover_rejected(self):
        closure=self.closure();closure['pending_request_count']=1
        with self.assertRaisesRegex(ReviewBlocked,'CLOSURE_PENDING_REQUEST'):
            self.store.rollover(self.new_config(),closure,as_of=self.at+timedelta(days=1))
    def test_stale_rollover_rejected(self):
        closure=self.closure();closure['observed_at']=(self.at+timedelta(days=1,seconds=-31)).isoformat()
        with self.assertRaisesRegex(ReviewBlocked,'CLOSURE_NOT_FRESH_NEW_SESSION'):
            self.store.rollover(self.new_config(),closure,as_of=self.at+timedelta(days=1))
    def test_wrong_closure_account_rejected(self):
        closure=self.closure();closure['account_scope']='FIXTURE:B'
        with self.assertRaisesRegex(ReviewBlocked,'CLOSURE_SCOPE_OR_SESSION_MISMATCH'):
            self.store.rollover(self.new_config(),closure,as_of=self.at+timedelta(days=1))
    def test_unverified_loss_blocks_without_fabricating_verified_trip(self):
        self.evidence['pnl_attribution_verified']=False;self.evidence['realized_net_pnl_paise']=-200000
        result=self.record();self.assertEqual(result['status'],'BLOCKED')
        self.assertFalse(self.store.state('FIXTURE:A')['latched'])
        self.assertEqual(self.store.state('FIXTURE:A')['highwater'],0)
    def test_stale_loss_does_not_advance_highwater(self):
        self.evidence['observed_at']=(self.at-timedelta(seconds=31)).isoformat()
        self.evidence['realized_net_pnl_paise']=-200000
        self.assertEqual(self.record()['status'],'BLOCKED')
        self.assertEqual(self.store.state('FIXTURE:A')['highwater'],0)
    def test_latch_can_trip_with_an_open_position(self):
        self.evidence['open_position_count']=1
        self.trip();self.assertTrue(self.store.state('FIXTURE:A')['latched'])
    def test_candidate_rejection_does_not_suppress_loss_trip(self):
        self.candidate['pricing_policy_approved']=False
        self.trip();self.assertTrue(self.store.state('FIXTURE:A')['latched'])
    def test_external_stop_claim_is_sticky_for_same_account_session(self):
        self.evidence['daily_stop_latched']=True;self.record('reported')
        self.evidence['daily_stop_latched']=False
        self.assertTrue(self.record('later')['current_durable_stop_latched'])
    def test_wrong_account_cannot_latch_this_account(self):
        self.evidence.update(account_scope='FIXTURE:B',daily_stop_latched=True,realized_net_pnl_paise=-999999)
        self.assertEqual(self.record()['status'],'BLOCKED')
        self.assertFalse(self.store.state('FIXTURE:A')['latched'])
    def test_idempotent_review_does_not_duplicate_audit(self):
        self.record();count=self.store.state('FIXTURE:A')['audit_count']
        self.assertTrue(self.record()['idempotent_replay'])
        self.assertEqual(self.store.state('FIXTURE:A')['audit_count'],count)
    def test_changed_payload_same_id_rejected(self):
        self.record();self.evidence['realized_net_pnl_paise']=-20000
        with self.assertRaisesRegex(ReviewBlocked,'REQUEST_ID_CONFLICT'):self.record()
    def test_old_review_replay_reports_current_latch(self):
        self.record('old');old=deepcopy(self.evidence);self.trip();self.evidence=old
        replay=self.record('old');self.assertTrue(replay['current_durable_stop_latched'])
        self.assertEqual(replay['status'],'BLOCKED');self.assertFalse(replay['entry_permission'])
    def test_transaction_rollback_keeps_latch_and_audit_consistent(self):
        before=self.store.state('FIXTURE:A')
        def fail():raise RuntimeError('INJECTED_BEFORE_COMMIT')
        faulty=FixtureLatch(self.path,checkpoint=fail)
        self.evidence['realized_net_pnl_paise']=-100000
        with self.assertRaisesRegex(RuntimeError,'INJECTED_BEFORE_COMMIT'):self.record(store=faulty)
        self.assertEqual(FixtureLatch(self.path).state('FIXTURE:A'),before)
    def test_concurrent_reviews_serialize_after_trip(self):
        self.trip();old=deepcopy(self.evidence);old['realized_net_pnl_paise']=0
        def work(i):
            return FixtureLatch(self.path).record(self.config,old,self.candidate,as_of=self.at,request_id='parallel-'+str(i))
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(work,range(16)))
        self.assertTrue(all(r['current_durable_stop_latched'] and r['status']=='BLOCKED' and not r['entry_permission'] for r in results))
        self.assertEqual(self.store.state('FIXTURE:A')['audit_count'],18)
    def test_concurrent_mixed_losses_keep_maximum_and_latch(self):
        def work(i):
            evidence=dict(self.evidence,realized_net_pnl_paise=-i*10000)
            return FixtureLatch(self.path).record(self.config,evidence,self.candidate,as_of=self.at,request_id='loss-'+str(i))
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(work,range(16)))
        state=self.store.state('FIXTURE:A');self.assertTrue(state['latched']);self.assertEqual(state['highwater'],150000)
        self.assertTrue(all(not r['entry_permission'] for r in results))
    def test_nonfixture_account_rejected(self):
        self.config['account_scope']='live-account'
        with self.assertRaisesRegex(ReviewBlocked,'FIXTURE_SCOPE_REQUIRED'):self.store.initialize(self.config,as_of=self.at)
    def test_existing_unrelated_database_untouched(self):
        path=Path(self.tmp.name)/'unrelated.sqlite'
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(id INTEGER)')
        before=path.read_bytes()
        with self.assertRaisesRegex(ReviewBlocked,'NOT_A_FIXTURE_LATCH_DATABASE'):FixtureLatch(path)
        self.assertEqual(path.read_bytes(),before)
    def test_create_never_overwrites_existing_database(self):
        before=self.path.read_bytes()
        with self.assertRaises(FileExistsError):FixtureLatch.create(self.path)
        self.assertEqual(self.path.read_bytes(),before)
    def test_symlink_database_rejected(self):
        path=Path(self.tmp.name)/'link.sqlite';path.symlink_to(self.path)
        with self.assertRaises(ReviewBlocked):FixtureLatch(path)
    def test_wrong_model_rejected(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE meta SET model=?',('OTHER',))
        with self.assertRaisesRegex(ReviewBlocked,'FIXTURE_MODEL_MISMATCH'):FixtureLatch(self.path)
    def test_wal_database_rejected_without_conversion(self):
        with closing(sqlite3.connect(self.path)) as db:db.execute('PRAGMA journal_mode=WAL')
        with self.assertRaisesRegex(ReviewBlocked,'FIXTURE_DELETE_JOURNAL_REQUIRED'):FixtureLatch(self.path)
    def test_commit_survives_writer_process_exit_and_separate_reader(self):
        evidence=dict(self.evidence,realized_net_pnl_paise=-100000)
        payload=json.dumps(dict(config=self.config,evidence=evidence,candidate=self.candidate,at=self.at.isoformat()))
        code="import json,sys; from hilega_daily_loss_latch_v1 import FixtureLatch; v=json.load(sys.stdin); FixtureLatch(sys.argv[1]).record(v['config'],v['evidence'],v['candidate'],as_of=v['at'],request_id='child-trip')"
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parent))
        subprocess.run([sys.executable,'-c',code,str(self.path)],input=payload,text=True,capture_output=True,env=env,check=True)
        read="import json,sys; from hilega_daily_loss_latch_v1 import FixtureLatch; print(json.dumps(FixtureLatch(sys.argv[1]).state('FIXTURE:A')))"
        result=subprocess.run([sys.executable,'-c',read,str(self.path)],text=True,capture_output=True,env=env,check=True)
        value=json.loads(result.stdout);self.assertTrue(value['latched']);self.assertEqual(value['highwater'],100000)
    def test_rollover_rollback_preserves_active_session_and_trip(self):
        self.trip();before=self.store.state('FIXTURE:A')
        def fail():raise RuntimeError('INJECTED_ROLLOVER_ROLLBACK')
        faulty=FixtureLatch(self.path,checkpoint=fail)
        with self.assertRaisesRegex(RuntimeError,'INJECTED_ROLLOVER_ROLLBACK'):
            faulty.rollover(self.new_config(),self.closure(),as_of=self.at+timedelta(days=1))
        self.assertEqual(self.store.state('FIXTURE:A'),before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],1)
    def test_old_session_writer_cannot_update_new_session(self):
        self.trip();self.store.rollover(self.new_config(),self.closure(),as_of=self.at+timedelta(days=1))
        before=self.store.state('FIXTURE:A')
        with self.assertRaisesRegex(ReviewBlocked,'EXPLICIT_SESSION_ROLLOVER_REQUIRED'):self.record('late-old-session')
        self.assertEqual(self.store.state('FIXTURE:A'),before)
    def test_all_inputs_unchanged(self):
        original=deepcopy((self.config,self.evidence,self.candidate));self.record()
        self.assertEqual(original,(self.config,self.evidence,self.candidate))

if __name__=='__main__':unittest.main()
