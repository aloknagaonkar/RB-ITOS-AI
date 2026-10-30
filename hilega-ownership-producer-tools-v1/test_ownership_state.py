from contextlib import closing,contextmanager,ExitStack
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace,ModuleType
import importlib
import unittest
from unittest.mock import patch
import test_ownership_review as base_tests
from signature_checks import aware,sign
from historical_receipt_checks import sha

RUNTIME=Path(__file__).parent/'reference_runtime'
NAMESPACE='_hilega_ownership_record_test_runtime'
package=ModuleType(NAMESPACE)
package.__path__=[str(RUNTIME/'market_lab/hilega_preparation_runtime_v1')]
sys.modules[NAMESPACE]=package
m=importlib.import_module(NAMESPACE+'.ownership_state')
dispatch_closed=importlib.import_module(NAMESPACE+'.exit_dispatch').dispatch_closed


class ApplicationStore:
    def __init__(self,path):self.path=path
    @contextmanager
    def lock(self):yield
    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path)) as db:
            try:yield db;db.commit()
            except BaseException:db.rollback();raise


class DispatchSource:
    def __init__(self,path,clock):
        self.s=SimpleNamespace(store=ApplicationStore(path),now=clock)
        self.checkpoint=lambda stage:None
    def _pause_in_transaction(self,db):
        row=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        row['mode']='PAUSED'
        db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(row),))
    def _audit(self,db,status,reasons):
        db.execute('INSERT INTO preparation_events(data) VALUES(?)',(json.dumps(dict(status=status,reasons=reasons)),))
    def _cursor(self,db,cursor):
        db.execute('INSERT OR REPLACE INTO preparation_source VALUES(1,?)',(json.dumps(cursor),))


class RuntimeRecordTests(unittest.TestCase):
    def setUp(self):
        self.b=base_tests.OwnershipTests();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.f=self.b.f;self.pin=self.b.pin
        self.now=aware(self.b.b.at)
        self.snapshot=deepcopy(self.b.b.snapshot)
        self.snapshot['signature']=sign(self.snapshot,self.pin)
        with closing(sqlite3.connect(self.f.app)) as db,db:
            db.execute('CREATE TABLE preparation_consumed(id TEXT PRIMARY KEY,fingerprint TEXT)')
        self.source=DispatchSource(self.f.app,lambda:self.now)
        self.event=dict(id='fixture-exit',role='EXIT',direction='BULLISH',
            event_at=self.f.request()['signal_at'],entry_reference_at=self.f.request()['signal_at'])
    def record(self,snapshot=None,**kwargs):
        return m.record_entry_review(self.f.app,self.f.adapter,
            self.snapshot if snapshot is None else snapshot,self.pin,
            clock=lambda:self.now,mode='OFFLINE_FIXTURE',**kwargs)
    def current(self):
        with closing(sqlite3.connect(self.f.app)) as db:
            return m.current_row(db,self.pin,'OFFLINE_FIXTURE')
    def count(self,table):
        with closing(sqlite3.connect(self.f.app)) as db:
            return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def context(self,event=None,now=None):
        with patch.dict(os.environ,{'HILEGA_PREPARATION_ADAPTER_DB':str(self.f.adapter)}), \
             closing(sqlite3.connect(self.f.app)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:return m.closed_exit_context(self.source,db,event or self.event,
                now=now or self.now,pin=self.pin,mode='OFFLINE_FIXTURE')
            finally:db.rollback()
    def signed(self,snap):
        snap.pop('signature',None);snap['signature']=sign(snap,self.pin);return snap
    def test_commit_survives_reopen(self):
        r=self.record();self.assertEqual(r['record_status'],'ENTRY_QUANTITY_RECONCILED')
        self.assertEqual(self.current()['reviewed_entry_quantity'],65)
        self.assertFalse(r['exit_submission_permission']);self.assertFalse(r['reservation_release_permission'])
    def test_idempotent_replay_no_audit_duplicate(self):
        self.record();before=self.current();r=self.record()
        self.assertTrue(r['idempotent_replay']);self.assertEqual(self.count(m.HISTORY),1)
        self.assertEqual(self.count(m.AUDIT),1);self.assertEqual(before,self.current())
    def test_invalid_later_review_invalidates_current(self):
        self.record();snap=deepcopy(self.snapshot)
        snap.update(snapshot_id='missing-position',positions=[]);self.signed(snap)
        self.assertEqual(self.record(snap)['record_status'],'BLOCKED')
        self.assertIsNone(self.current()['reviewed_entry_quantity'])
        self.assertEqual(self.context()['reason'],'OWNERSHIP_STATE_BLOCKED')
    def test_old_replay_cannot_restore_good_state(self):
        self.record();snap=deepcopy(self.snapshot)
        snap.update(snapshot_id='missing-position',positions=[]);self.signed(snap);self.record(snap)
        result=self.record()
        self.assertTrue(result['idempotent_replay']);self.assertEqual(result['current_status'],'BLOCKED')
        self.assertIsNone(self.current()['reviewed_entry_quantity'])
    def test_bad_current_capture_signature_invalidates(self):
        self.record();snap=deepcopy(self.snapshot);snap['snapshot_id']='tampered'
        self.record(snap)
        self.assertEqual(self.current()['status'],'BLOCKED')
        self.assertIn('SNAPSHOT_SIGNATURE_INVALID',self.current()['reasons'])
    def test_duplicate_snapshot_id_changed_payload_blocks(self):
        self.record();snap=deepcopy(self.snapshot);snap['positions']=[];self.signed(snap)
        self.record(snap)
        self.assertEqual(self.current()['status'],'BLOCKED')
        self.assertIn('CAPTURE_ID_REUSED_OR_LOCAL_SOURCE_CHANGED',self.current()['reasons'])
        self.assertEqual(self.count(m.HISTORY),1)
    def test_changed_reservation_replay_invalidates(self):
        self.record()
        v=self.f.get(self.f.app,'preparation_cash_reservations','p1')
        v['state']='UNKNOWN_HOLD_RETAINED';self.b.resign(v)
        self.f.put(self.f.app,'preparation_cash_reservations','p1',v)
        self.record();self.assertEqual(self.current()['status'],'BLOCKED')
    def test_stale_context_never_gives_quantity(self):
        self.record();r=self.context(now=self.now+timedelta(seconds=31))
        self.assertEqual(r['reason'],'OWNERSHIP_STATE_STALE_OR_FUTURE')
        self.assertIsNone(r['reviewed_entry_quantity'])
    def test_clock_regression_before_capture_end_is_rejected(self):
        self.record();r=self.context(now=aware(self.snapshot['generated_at']))
        self.assertEqual(r['reason'],'OWNERSHIP_STATE_STALE_OR_FUTURE')
    def test_context_direction_must_match(self):
        self.record();event=dict(self.event,direction='BEARISH')
        self.assertEqual(self.context(event)['reason'],'EXIT_PARENT_OR_DIRECTION_UNVERIFIED')
    def test_context_parent_time_must_match(self):
        self.record();event=dict(self.event,entry_reference_at=None)
        self.assertEqual(self.context(event)['reason'],'EXIT_PARENT_OR_DIRECTION_UNVERIFIED')
    def test_context_detects_current_source_drift(self):
        self.record()
        with closing(sqlite3.connect(self.f.app)) as db,db:
            db.execute('INSERT INTO preparation_source VALUES(1,?)',('{"sequence":2}',))
        self.assertEqual(self.context()['reason'],'OWNERSHIP_BOUND_SOURCE_CHANGED')
    def test_context_uses_no_live_permission(self):
        self.record();r=self.context()
        self.assertEqual(r['status'],'ENTRY_QUANTITY_CONTEXT_ONLY')
        self.assertEqual(r['reviewed_entry_quantity'],65)
        self.assertTrue(r['fixture_only']);self.assertFalse(r['exit_submission_permission'])
    def test_signature_tampered_state_not_used(self):
        self.record()
        with closing(sqlite3.connect(self.f.app)) as db,db:
            row=json.loads(db.execute('SELECT data FROM '+m.CURRENT).fetchone()[0])
            row['reviewed_entry_quantity']=999
            db.execute('UPDATE '+m.CURRENT+' SET data=?',(json.dumps(row),))
        self.assertEqual(self.context()['reason'],'OWNERSHIP_STATE_SIGNATURE_INVALID')
    def test_interrupt_rolls_back_history_and_current(self):
        self.record();before=self.current()
        snap=deepcopy(self.snapshot);snap['snapshot_id']='new-observation';self.signed(snap)
        class Interrupted(BaseException):pass
        def stop(stage):
            if stage=='BEFORE_OWNERSHIP_COMMIT':raise Interrupted()
        with self.assertRaises(Interrupted):self.record(snap,checkpoint=stop)
        self.assertEqual(before,self.current());self.assertEqual(self.count(m.HISTORY),1)
    def test_broker_and_cash_hold_untouched(self):
        before=self.f.adapter.read_bytes()
        hold=self.f.get(self.f.app,'preparation_cash_reservations','p1')
        self.record();self.assertEqual(before,self.f.adapter.read_bytes())
        self.assertEqual(hold,self.f.get(self.f.app,'preparation_cash_reservations','p1'))
    def test_changed_scope_cannot_write(self):
        with self.assertRaisesRegex(ValueError,'ADAPTER_PIN_SCOPE_OR_MODE_MISMATCH'):
            m.record_entry_review(self.f.app,self.f.adapter,self.snapshot,
                dict(self.pin,scope='FIXTURE:OTHER'),clock=lambda:self.now,mode='OFFLINE_FIXTURE')
        with closing(sqlite3.connect(self.f.app)) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(m.CURRENT,)).fetchone())
    def test_fixture_cannot_write_live_state(self):
        with self.assertRaisesRegex(ValueError,'LIVE_UPSTOX_PIN_SCOPE_REQUIRED'):
            m.record_entry_review(self.f.app,self.f.adapter,self.snapshot,self.pin,clock=lambda:self.now)
    def test_dispatch_links_context_but_stays_refused(self):
        self.record();original=m.closed_exit_context
        def fixture_context(source,db,event,*,now,resources):
            return original(source,db,event,now=now,pin=self.pin,mode='OFFLINE_FIXTURE',resources=resources)
        before=self.f.adapter.read_bytes()
        with patch.dict(os.environ,{'HILEGA_PREPARATION_ADAPTER_DB':str(self.f.adapter)}), \
             patch.object(m,'closed_exit_context',side_effect=fixture_context):
            r=dispatch_closed(self.source,[self.event],dict(sequence=1,hash='fixture'),fingerprint=sha)
        self.assertEqual(r['status'],'EXIT_DISPATCH_REFUSED_CLOSED')
        with closing(sqlite3.connect(self.f.app)) as db:
            row=json.loads(db.execute('SELECT data FROM preparation_exit_dispatch').fetchone()[0])
        self.assertEqual(row['entry_ownership_context']['reviewed_entry_quantity'],65)
        self.assertIsNone(row['exit_quantity']);self.assertIsNone(row['parent_request_id'])
        self.assertFalse(row['automatic_execution_eligible']);self.assertEqual(before,self.f.adapter.read_bytes())
    def test_dispatch_without_record_preserves_refusal(self):
        r=dispatch_closed(self.source,[self.event],dict(sequence=1),fingerprint=sha)
        self.assertFalse(r['orders_sent'])
        with closing(sqlite3.connect(self.f.app)) as db:
            row=json.loads(db.execute('SELECT data FROM preparation_exit_dispatch').fetchone()[0])
        self.assertEqual(row['entry_ownership_context']['status'],'NO_CURRENT_ENTRY_OWNERSHIP_CONTEXT')
    def test_broker_snapshot_denies_writes(self):
        with ExitStack() as resources:
            db=m.broker_snapshot(self.f.adapter,resources)
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE meta SET data='tampered'")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute('DROP TABLE requests')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],1)
    def test_broker_read_snapshot_held_through_dispatch_commit(self):
        self.record();original=m.closed_exit_context;original_db=self.source.s.store.db
        committed=[]
        @contextmanager
        def checking_db():
            with original_db() as db:yield db
            with closing(sqlite3.connect(self.f.adapter,timeout=0)) as writer:
                with self.assertRaises(sqlite3.OperationalError):writer.execute('BEGIN EXCLUSIVE')
            committed.append(True)
        def fixture_context(source,db,event,*,now,resources):
            return original(source,db,event,now=now,pin=self.pin,
                            mode='OFFLINE_FIXTURE',resources=resources)
        self.source.s.store.db=checking_db
        with patch.dict(os.environ,{'HILEGA_PREPARATION_ADAPTER_DB':str(self.f.adapter)}), \
             patch.object(m,'closed_exit_context',side_effect=fixture_context):
            dispatch_closed(self.source,[self.event],dict(sequence=1),fingerprint=sha)
        self.assertEqual(committed,[True])
        with closing(sqlite3.connect(self.f.adapter,timeout=0)) as writer:
            writer.execute('BEGIN EXCLUSIVE');writer.rollback()
    def test_source_reader_rejects_write_statements(self):
        with closing(sqlite3.connect(self.f.app)) as app,ExitStack() as resources:
            reader=m.SourceReader(app,m.broker_snapshot(self.f.adapter,resources))
            with self.assertRaisesRegex(ValueError,'SOURCE_READER_SELECT_ONLY'):
                reader.execute("UPDATE broker.meta SET data='tampered'")
    def test_final_freshness_recheck_rolls_back_candidate(self):
        snap=deepcopy(self.snapshot)
        initial=self.now
        def stop(stage):
            if stage=='BEFORE_OWNERSHIP_COMMIT':self.now=initial+timedelta(seconds=31)
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_STALE_OR_FUTURE'):
            self.record(snap,checkpoint=stop)
        with closing(sqlite3.connect(self.f.app)) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(m.CURRENT,)).fetchone())
    def test_old_snapshot_time_cannot_replace_later_state(self):
        later=deepcopy(self.snapshot)
        later.update(snapshot_id='later',generated_at='2026-10-29T05:30:01+00:00',
                     completed_at='2026-10-29T05:30:02+00:00')
        self.signed(later);self.record(later)
        old=deepcopy(self.snapshot);old['snapshot_id']='new-id-old-time';self.signed(old)
        self.record(old)
        self.assertEqual(self.current()['status'],'BLOCKED')
        self.assertEqual(self.current()['high_water_capture_at'],later['generated_at'])
    def test_no_record_context_reads_no_pin(self):
        with patch.object(m,'load_pin',side_effect=AssertionError('No key needed')):
            with closing(sqlite3.connect(self.f.app)) as db:
                r=m.closed_exit_context(self.source,db,self.event,now=self.now)
        self.assertEqual(r['status'],'NO_CURRENT_ENTRY_OWNERSHIP_CONTEXT')
    def test_input_snapshot_not_modified(self):
        before=deepcopy(self.snapshot);self.record();self.assertEqual(before,self.snapshot)

if __name__=='__main__':unittest.main()
