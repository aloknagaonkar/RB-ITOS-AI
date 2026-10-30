from copy import deepcopy
from datetime import timedelta,datetime,timezone
from contextlib import closing
from pathlib import Path
import os
import stat
import importlib
import json
import sqlite3
import unittest
from unittest.mock import Mock
import producer as p
import test_ownership_state as fixture


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.b=fixture.RuntimeRecordTests();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.m=fixture.m;self.pin=self.b.pin
        checks=importlib.import_module(self.m.__package__+'.ownership_checks.risk_evidence_audit')
        rules=importlib.import_module(self.m.__package__+'.ownership_checks.ownership_review')
        self.kw=dict(pin_reader=Mock(side_effect=lambda:deepcopy(self.pin)),
            reader=Mock(side_effect=lambda pin:checks.read_sources(self.b.f.app,self.b.f.adapter,pin['scope'],expected_mode='OFFLINE_FIXTURE')),
            capture=Mock(side_effect=lambda pin:deepcopy(self.b.snapshot)),
            reviewer=Mock(side_effect=lambda source,snapshot,pin,*,as_of:rules.reconcile_entry(source,snapshot,pin,as_of=as_of,mode='OFFLINE_FIXTURE')),
            writer=Mock(side_effect=lambda snapshot,pin:self.m.record_entry_review(
                self.b.f.app,self.b.f.adapter,snapshot,pin,clock=lambda:self.b.now,mode='OFFLINE_FIXTURE')),
            state_reader=Mock(side_effect=self.read_state),clock=lambda:self.b.now)
    def read_state(self,pin):
        with closing(sqlite3.connect(self.b.f.app.as_uri()+'?mode=ro',uri=True)) as db:
            return self.m.current_row(db,pin,'OFFLINE_FIXTURE')
    def run_once(self,action='record'):return p.run_once(action,**self.kw)
    def test_check_reads_without_persisting(self):
        before=self.b.f.app.read_bytes();r=self.run_once('check')
        self.assertEqual(r['status'],'OWNERSHIP_PRODUCER_CHECK_COMPLETE')
        self.kw['writer'].assert_not_called();self.assertFalse(r['database_modified'])
        self.assertEqual(before,self.b.f.app.read_bytes())
    def test_record_current_state_and_verify_readback(self):
        r=self.run_once();self.assertEqual(r['status'],'OWNERSHIP_PRODUCER_RECORDED_ENTRY_QUANTITY_RECONCILED')
        self.assertTrue(r['ownership_record_persisted']);self.assertTrue(r['current_state_signature_verified'])
        self.assertEqual(self.read_state(self.pin)['reviewed_entry_quantity'],65)
        self.assertFalse(r['current_entry_ownership_verified'])
    def test_get_failure_invalidates_previous_current_state(self):
        self.b.record();self.kw['capture'].side_effect=ValueError('BROKER_READ_FAILED')
        r=self.run_once();self.assertEqual(r['status'],'OWNERSHIP_PRODUCER_FAILED_CURRENT_INVALIDATED')
        self.assertEqual(self.read_state(self.pin)['status'],'BLOCKED')
        self.assertEqual(self.kw['writer'].call_count,1)
        failure=self.kw['writer'].call_args.args[0]
        self.assertEqual(failure['model'],'HILEGA_OWNERSHIP_PRODUCER_FAILURE_V1')
        self.assertNotIn('orders',failure)
    def test_bad_signature_invalidates_current(self):
        self.b.record();snap=deepcopy(self.b.snapshot);snap['snapshot_id']='tampered'
        self.kw['capture'].side_effect=lambda pin:snap
        r=self.run_once();self.assertEqual(r['status'],'OWNERSHIP_PRODUCER_FAILED_CURRENT_INVALIDATED')
        self.assertIsNone(self.read_state(self.pin)['reviewed_entry_quantity'])
    def test_pin_change_skips_write_and_invalidation(self):
        changed=dict(self.pin,key='22'*32)
        self.kw['pin_reader'].side_effect=[self.pin,changed,changed]
        r=self.run_once();self.assertEqual(r['reason'],'ACCOUNT_PIN_CHANGED_DURING_CAPTURE')
        self.kw['writer'].assert_not_called()
    def test_local_source_change_invalidates_current(self):
        self.b.record();before=self.kw['reader'](self.pin);after=deepcopy(before)
        after['source_cursors']=[(1,'changed')];self.kw['reader'].side_effect=[before,after]
        r=self.run_once();self.assertEqual(r['reason'],'LOCAL_SOURCES_CHANGED_DURING_CAPTURE')
        self.assertEqual(self.read_state(self.pin)['status'],'BLOCKED')
    def test_writer_failure_does_not_retry(self):
        self.kw['writer'].side_effect=ValueError('RECORD_WRITE_FAILED')
        r=self.run_once();self.assertEqual(r['persistence_outcome'],'UNKNOWN_REVIEW_REQUIRED')
        self.assertIsNone(r['database_modified']);self.assertEqual(self.kw['writer'].call_count,1)
    def test_lost_record_response_does_not_retry(self):
        original=self.kw['writer'].side_effect
        def lost(snapshot,pin):
            original(snapshot,pin);raise ValueError('RECORD_RESPONSE_LOST')
        self.kw['writer'].side_effect=lost
        r=self.run_once();self.assertEqual(self.kw['writer'].call_count,1)
        self.assertEqual(r['persistence_outcome'],'UNKNOWN_REVIEW_REQUIRED')
        self.assertEqual(self.read_state(self.pin)['status'],'ENTRY_QUANTITY_RECONCILED')
        self.assertFalse(r['exit_submission_permission'])
    def test_readback_mismatch_does_not_retry_or_grant_quantity(self):
        self.kw['state_reader'].side_effect=lambda pin:dict(account_capture_fingerprint='wrong')
        r=self.run_once();self.assertEqual(r['reason'],'PERSISTED_CAPTURE_READBACK_MISMATCH')
        self.assertEqual(self.kw['writer'].call_count,1);self.assertIsNone(r['verified_owned_quantity'])
    def test_capture_is_called_once(self):
        self.run_once();self.assertEqual(self.kw['capture'].call_count,1)
    def test_raw_private_ids_and_key_not_in_report(self):
        r=self.run_once();raw=json.dumps(r)
        for value in (self.pin['key'],self.pin['scope'],'FIXTURE-ORDER','fixture-fill'):
            self.assertNotIn(value,raw)
    def test_unbounded_error_message_is_suppressed(self):
        self.kw['capture'].side_effect=RuntimeError('private broker token: not-for-output')
        raw=json.dumps(self.run_once())
        self.assertNotIn('not-for-output',raw);self.assertNotIn('private broker token',raw)
    def test_failed_check_never_invalidates(self):
        self.kw['capture'].side_effect=ValueError('BROKER_READ_FAILED')
        r=self.run_once('check');self.kw['writer'].assert_not_called()
        self.assertEqual(r['status'],'OWNERSHIP_PRODUCER_STOPPED_FOR_REVIEW')
    def test_invalid_action_performs_no_io(self):
        with self.assertRaisesRegex(ValueError,'PRODUCER_ACTION_INVALID'):self.run_once('start')
        self.kw['pin_reader'].assert_not_called()
    def test_pin_read_failure_never_writes(self):
        self.kw['pin_reader'].side_effect=ValueError('PIN_UNAVAILABLE')
        r=self.run_once();self.kw['writer'].assert_not_called();self.assertFalse(r['database_modified'])
    def test_capture_input_not_modified(self):
        snap=deepcopy(self.b.snapshot);before=deepcopy(snap)
        self.kw['capture'].side_effect=lambda pin:snap
        self.run_once();self.assertEqual(before,snap)
    def test_empty_account_persists_blocked_not_zero_pnl(self):
        with closing(sqlite3.connect(self.b.f.app)) as db,db:
            for table in ('preparation_plans','preparation_shadow_holds','preparation_outbox',
                          'preparation_request_bindings','preparation_evidence','preparation_cash_reservations'):
                db.execute('DELETE FROM '+table)
        with closing(sqlite3.connect(self.b.f.adapter)) as db,db:
            for table in ('requests','attempts','receipts'):db.execute('DELETE FROM '+table)
        snap=deepcopy(self.b.snapshot);snap.update(orders=[],trades=[],positions=[])
        self.b.signed(snap);self.kw['capture'].side_effect=lambda pin:snap
        r=self.run_once();self.assertEqual(r['status'],'OWNERSHIP_PRODUCER_RECORDED_BLOCKED')
        self.assertIsNone(r['verified_owned_quantity'])
        row=self.read_state(self.pin);self.assertIsNone(row['realized_net_pnl_paise'])
    def test_failed_invalidation_is_reported_without_second_attempt(self):
        self.kw['capture'].side_effect=ValueError('BROKER_READ_FAILED')
        self.kw['writer'].side_effect=ValueError('DATABASE_BUSY')
        r=self.run_once();self.assertEqual(self.kw['writer'].call_count,1)
        self.assertEqual(r['invalidation_reason'],'DATABASE_BUSY')
        self.assertEqual(r['persistence_outcome'],'UNKNOWN_REVIEW_REQUIRED')
    def test_pin_change_after_write_is_not_retried(self):
        changed=dict(self.pin,key='22'*32)
        self.kw['pin_reader'].side_effect=[self.pin,self.pin,self.pin,changed]
        r=self.run_once();self.assertEqual(r['reason'],'ACCOUNT_PIN_CHANGED_AFTER_PERSISTENCE')
        self.assertEqual(self.kw['writer'].call_count,1)
    def test_all_execution_and_release_flags_stay_false(self):
        r=self.run_once()
        for key in ('orders_sent','production_execution_enabled','entry_permission',
                    'exit_submission_permission','reservation_release_permission','production_ready'):
            self.assertIs(r[key],False)
    def test_read_only_status_without_record(self):
        source=self.kw['reader'](self.pin)
        r=p.status_report(self.pin,source,None,clock=lambda:self.b.now,digest=self.m.sha)
        self.assertEqual(r['status'],'NO_OWNERSHIP_RECORD');self.assertFalse(r['database_modified'])
    def test_status_current_fixture_is_not_live_ownership(self):
        self.b.record();row=self.read_state(self.pin);source=self.kw['reader'](self.pin)
        r=p.status_report(self.pin,source,row,clock=lambda:self.b.now,digest=self.m.sha)
        self.assertEqual(r['status'],'CURRENT_ENTRY_CONTEXT_AVAILABLE')
        self.assertFalse(r['current_entry_ownership_verified'])
    def test_status_stale_record_hides_quantity(self):
        self.b.record();row=self.read_state(self.pin);source=self.kw['reader'](self.pin)
        r=p.status_report(self.pin,source,row,clock=lambda:self.b.now+timedelta(seconds=31),digest=self.m.sha)
        self.assertEqual(r['status'],'STALE_OR_LOCAL_SOURCE_CHANGED');self.assertIsNone(r['verified_owned_quantity'])
    def test_status_source_drift_hides_quantity(self):
        self.b.record();row=self.read_state(self.pin);source=self.kw['reader'](self.pin)
        source['source_cursors']=[(1,'changed')]
        r=p.status_report(self.pin,source,row,clock=lambda:self.b.now,digest=self.m.sha)
        self.assertEqual(r['status'],'STALE_OR_LOCAL_SOURCE_CHANGED')


    def test_first_write_backup_is_consistent_and_private(self):
        root=self.b.f.app.parent;(root/'backups').mkdir()
        before=self.b.f.app.read_bytes()
        target=Path(p.first_write_backup(self.b.f.app,root))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode),0o700)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0],1)
        self.assertEqual(before,self.b.f.app.read_bytes())
    def test_existing_ownership_table_avoids_repeated_backup(self):
        self.b.record();root=self.b.f.app.parent
        self.assertIsNone(p.first_write_backup(self.b.f.app,root))
    def test_symlink_backup_parent_is_rejected(self):
        root=self.b.f.app.parent;outside=root/'outside';outside.mkdir()
        (root/'backups').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'PRIVATE_BACKUP_PARENT_REQUIRED'):
            p.first_write_backup(self.b.f.app,root)
        self.assertEqual(list(outside.iterdir()),[])
    def test_unknown_fees_and_pnl_remain_unknown(self):
        r=self.run_once();self.assertIsNone(r['realized_net_pnl_paise'])
        self.assertIsNone(r['open_net_pnl_paise']);self.assertFalse(r['fees_complete'])


    def test_status_rejects_ist_session_rollover(self):
        self.b.record();row=self.read_state(self.pin);source=self.kw['reader'](self.pin)
        row.update(account_capture_generated_at='2026-10-29T18:29:59+00:00',
            account_capture_completed_at='2026-10-29T18:29:59+00:00',
            assessed_at='2026-10-29T18:29:59+00:00')
        now=datetime(2026,10,29,18,30,1,tzinfo=timezone.utc)
        r=p.status_report(self.pin,source,row,clock=lambda:now,digest=self.m.sha)
        self.assertEqual(r['status'],'STALE_OR_LOCAL_SOURCE_CHANGED')
    def test_initial_pin_is_frozen_against_mutation(self):
        shared=deepcopy(self.pin);self.kw['pin_reader'].side_effect=lambda:shared
        def change(pin):
            shared['key']='22'*32
            return deepcopy(self.b.snapshot)
        self.kw['capture'].side_effect=change
        r=self.run_once();self.assertEqual(r['reason'],'ACCOUNT_PIN_CHANGED_DURING_CAPTURE')
        self.kw['writer'].assert_not_called()
    def test_before_source_snapshot_is_frozen(self):
        shared=self.kw['reader'](self.pin);self.kw['reader'].side_effect=lambda pin:shared
        def change(pin):
            shared['source_cursors']=[(1,'changed')]
            return deepcopy(self.b.snapshot)
        self.kw['capture'].side_effect=change
        r=self.run_once();self.assertEqual(r['reason'],'LOCAL_SOURCES_CHANGED_DURING_CAPTURE')
        self.kw['reviewer'].assert_not_called()


    def test_status_reads_current_record_and_sources_in_one_read_only_snapshot(self):
        self.b.record();before=self.b.f.app.read_bytes()
        source,row=p.read_status_snapshot(self.b.f.app,self.b.f.adapter,self.pin,
                                         self.m,mode='OFFLINE_FIXTURE')
        self.assertEqual(row['status'],'ENTRY_QUANTITY_RECONCILED')
        self.assertEqual(row['source_fingerprint'],self.m.sha(source))
        self.assertEqual(before,self.b.f.app.read_bytes())

if __name__=='__main__':unittest.main()
