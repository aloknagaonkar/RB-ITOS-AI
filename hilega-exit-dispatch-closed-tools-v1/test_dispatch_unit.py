"""SQLite transaction tests; no application services, broker or credentials."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE=Path(__file__).parent/'runtime/market_lab/hilega_preparation_runtime_v1/exit_dispatch.py'
spec=importlib.util.spec_from_file_location('closed_exit_module',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fp(event):
    return hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self,path):self.path=path
    @contextmanager
    def lock(self):yield
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()


class Source:
    def __init__(self,path):
        self.s=self;self.store=Store(path);self.checkpoint=lambda stage:None
        with self.store.db() as db:
            db.executescript('CREATE TABLE preparation_consumed(id TEXT PRIMARY KEY,fingerprint TEXT);'
                'CREATE TABLE cursor(data TEXT);CREATE TABLE control(mode TEXT);'
                'INSERT INTO control VALUES("ARMED");CREATE TABLE audit(data TEXT);'
                'CREATE TABLE holds(data TEXT);INSERT INTO holds VALUES("retained");')
    def now(self):return datetime(2026,10,29,10,tzinfo=timezone.utc)
    def _pause_in_transaction(self,db):db.execute('UPDATE control SET mode="PAUSED"')
    def _audit(self,db,status,reasons):db.execute('INSERT INTO audit VALUES(?)',(json.dumps(reasons),))
    def _cursor(self,db,cursor):
        db.execute('DELETE FROM cursor');db.execute('INSERT INTO cursor VALUES(?)',(json.dumps(cursor),))


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Source(Path(self.tmp.name)/'application.sqlite')
        self.events=[dict(id='exit-1',role='EXIT',direction='BULLISH',event_at='2026-10-29T15:30:00+05:30')]
        self.cursor=dict(sequence=12,hash='synthetic')
    def run_dispatch(self,events=None):
        return m.dispatch_closed(self.source,self.events if events is None else events,self.cursor,fingerprint=fp)
    def count(self,table):
        with self.source.store.db() as db:return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def test_persisted_closed_and_hold_retained(self):
        result=self.run_dispatch();self.assertFalse(result['orders_sent'])
        with self.source.store.db() as db:
            row=json.loads(db.execute('SELECT data FROM preparation_exit_dispatch').fetchone()[0])
            self.assertEqual(db.execute('SELECT mode FROM control').fetchone()[0],'PAUSED')
            self.assertEqual(db.execute('SELECT data FROM holds').fetchone()[0],'retained')
        self.assertIsNone(row['exit_quantity']);self.assertFalse(row['automatic_execution_eligible'])
        self.assertFalse(row['executable_request_created']);self.assertFalse(row['reservation_release_permission'])
    def test_replay_no_duplicate(self):
        self.run_dispatch();self.assertTrue(self.run_dispatch()['idempotent_replay'])
        self.assertEqual(self.count('preparation_exit_dispatch'),1);self.assertEqual(self.count('audit'),1)
    def test_reopen_survives(self):
        self.run_dispatch();self.source.store=Store(self.source.store.path)
        self.assertTrue(self.run_dispatch()['idempotent_replay'])
    def test_reversal_consumes_both_without_entry(self):
        self.events.append(dict(id='entry-2',role='ENTRY',direction='BEARISH'))
        self.run_dispatch();self.assertEqual(self.count('preparation_consumed'),2)
        with self.source.store.db() as db:
            row=json.loads(db.execute('SELECT data FROM preparation_exit_dispatch').fetchone()[0])
        self.assertTrue(row['reversal_entry_suppressed'])
    def test_changed_exit_rejected(self):
        self.run_dispatch();self.events[0]['direction']='BEARISH'
        with self.assertRaisesRegex(ValueError,'EXIT_DISPATCH_RECORD_CONFLICT'):self.run_dispatch()
    def test_changed_boundary_rejected(self):
        self.run_dispatch();self.events.append(dict(id='entry-2',role='ENTRY'))
        with self.assertRaisesRegex(ValueError,'EXIT_DISPATCH_RECORD_CONFLICT'):self.run_dispatch()
    def test_missing_exit_rejected(self):
        with self.assertRaisesRegex(ValueError,'EXACTLY_ONE_CONFIRMED_EXIT_REQUIRED'):
            self.run_dispatch([dict(id='entry',role='ENTRY')])
    def test_interrupt_rolls_back_cursor_and_consumption(self):
        self.run_dispatch()  # Establish schema before rollback test.
        with self.source.store.db() as db:
            for table in ('preparation_exit_dispatch','preparation_consumed','cursor','audit'):
                db.execute('DELETE FROM '+table)
            db.execute('UPDATE control SET mode="ARMED"')
        class Interrupted(BaseException):pass
        def stop(stage):raise Interrupted()
        self.source.checkpoint=stop
        with self.assertRaises(Interrupted):self.run_dispatch()
        for table in ('preparation_exit_dispatch','preparation_consumed','cursor','audit'):
            self.assertEqual(self.count(table),0)
        with self.source.store.db() as db:
            self.assertEqual(db.execute('SELECT mode FROM control').fetchone()[0],'ARMED')
    def test_consumed_conflict_rolls_back_exit(self):
        with self.source.store.db() as db:
            db.execute('INSERT INTO preparation_consumed VALUES("exit-1","changed")')
        with self.assertRaisesRegex(ValueError,'CONFIRMED_EVENT_CONFLICT'):self.run_dispatch()
        with self.source.store.db() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_exit_dispatch'").fetchone()
        self.assertIsNone(exists)
    def test_inputs_not_modified(self):
        before=deepcopy((self.events,self.cursor));self.run_dispatch()
        self.assertEqual(before,(self.events,self.cursor))

if __name__=='__main__':unittest.main()
