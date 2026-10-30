from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest
import test_bridge as bridge_tests
from ownership_review import reconcile_entry
from reservation_checks import POLICY
from risk_evidence_audit import FLAGS, read_sources
from signature_checks import sign
from historical_receipt_checks import sha


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.b=bridge_tests.BridgeTests();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.f=self.b.f;self.pin=self.b.pin
        plan=self.f.get(self.f.app,'preparation_plans','p1')
        plan.update(signal_at=self.f.request()['signal_at'],direction='BULLISH')
        self.f.put(self.f.app,'preparation_plans','p1',plan)
        bundle=self.b.bundle()
        funds=dict(field='data.available_to_trade.cash_available_to_trade.total',cash_available_to_trade='400')
        cash=dict(model='HILEGA_READ_ONLY_CASH_OBSERVATION_V1',
            evidence_mode='LIVE_READ_ONLY_ACCOUNT_PINNED',account_scope=self.pin['scope'],
            account_identity_verified=True,account_position_rows_complete=True,
            status='READ_ONLY_CAPTURED',started_at=bundle['started_at'],
            completed_at=bundle['completed_at'],session_date=bundle['session_date'],
            funds_before=deepcopy(funds),funds_after=deepcopy(funds),
            funds_changed_during_capture=False,orders=[],trades=[],positions=[],
            diagnostics=dict(issues=[]),orders_sent=False,entry_permission=False,
            production_execution_enabled=False)
        cash['signature']=sign(cash,self.pin)
        bundle.update(cash_capture=cash,cash_before_market=deepcopy(funds),cash_after_market=deepcopy(funds))
        self.b.replace_bundle(bundle)
        source=self.b.source();binding=source['bindings']['p1']
        reservation=dict({k:False for k in FLAGS},
            model='HILEGA_APPLICATION_LOCAL_CASH_RESERVATION_V1',id='p1',
            account_scope=self.pin['scope'],session_date='2026-10-29',
            state='RESERVED_DISABLED_REQUEST',policy=deepcopy(POLICY),
            amount_cents=10000,held_cents=10000,cash_cap_cents=20000,
            premium_cents=9000,fee_buffer_cents=1000,
            fee_buffer_approved_for_production=False,
            request_fingerprint=binding['request_fingerprint'],
            plan_fingerprint=binding['plan_fingerprint'],
            shadow_hold_fingerprint=binding['hold_fingerprint'],
            outbox_fingerprint=binding['outbox_fingerprint'],
            created_at=self.f.request()['signal_at'],
            local_reference_reserved=True,broker_cash_locked=False)
        reservation['signature']=sign(reservation,self.pin)
        self.f.put(self.f.app,'control',1,dict(mode='PAUSED',production_execution_enabled=False))
        with closing(sqlite3.connect(self.f.app)) as db,db:
            db.executescript('CREATE TABLE preparation_cash_policy(id INTEGER,data TEXT);'
                'CREATE TABLE preparation_cash_reservations(id TEXT PRIMARY KEY,data TEXT);'
                'CREATE TABLE sim_stop_state(id INTEGER,generation INTEGER,handled INTEGER);'
                'INSERT INTO sim_stop_state VALUES(1,0,0);')
            db.execute('INSERT INTO preparation_cash_policy VALUES(1,?)',(json.dumps(dict(
                scope=self.pin['scope'],mode='APPLICATION_LOCAL_REFERENCE_ONLY',policy=POLICY)),))
        self.f.put(self.f.app,'preparation_cash_reservations','p1',reservation)

    def source(self):return self.b.source()
    def review(self,source=None,snapshot=None,at=None):
        s=deepcopy(snapshot if snapshot is not None else self.b.snapshot)
        s.pop('signature',None);s['signature']=sign(s,self.pin)
        return reconcile_entry(self.source() if source is None else source,s,self.pin,
            as_of=at or self.b.at,mode='OFFLINE_FIXTURE')
    def resign(self,row):
        row.pop('signature',None);row['signature']=sign(row,self.pin);return row
    def test_full_entry_quantity_fixture_only(self):
        r=self.review();self.assertEqual(r['reviewed_remaining_entry_quantity'],65)
        self.assertTrue(r['fixture_entry_quantity_reconciled'])
        self.assertTrue(r['historical_nested_cash_authenticated'])
        for k in ('current_entry_ownership_verified','exit_submission_permission',
            'reservation_release_permission','production_ready','risk_gate_input_ready',
            'live_evidence_assessed','strategy_ownership_verified','fees_complete'):
            self.assertIs(r[k],False)
    def test_source_databases_byte_identical(self):
        paths=(self.f.app,self.f.adapter);before=[p.read_bytes() for p in paths]
        self.review();self.assertEqual(before,[p.read_bytes() for p in paths])
    def test_inputs_unchanged(self):
        source=self.source();snapshot=deepcopy(self.b.snapshot);before=deepcopy((source,snapshot))
        self.review(source,snapshot);self.assertEqual(before,(source,snapshot))
    def test_missing_reservation_blocks(self):
        s=self.source();s['cash_reservations']={}
        r=self.review(s);self.assertIn('LOCAL_RESERVATION_BINDING_SET_MISMATCH',r['reasons'])
        self.assertIsNone(r['reviewed_remaining_entry_quantity'])
    def test_reservation_tamper_rejected(self):
        s=self.source();s['cash_reservations']['p1']['amount_cents']=1
        with self.assertRaisesRegex(ValueError,'LOCAL_CASH_RESERVATION_SIGNATURE_INVALID'):self.review(s)
    def test_unknown_hold_rejected(self):
        s=self.source();v=s['cash_reservations']['p1'];v['state']='UNKNOWN_HOLD_RETAINED';self.resign(v)
        with self.assertRaisesRegex(ValueError,'UNKNOWN_OUTCOME_HOLD_RETAINED'):self.review(s)
    def test_recovered_policy_still_requires_half_cash(self):
        s=self.source();v=s['cash_reservations']['p1'];v['policy']['allocation_denominator']=1;self.resign(v)
        with self.assertRaisesRegex(ValueError,'LOCAL_CASH_RESERVATION_SCOPE_OR_POLICY_CHANGED'):self.review(s)
    def test_missing_policy_blocks(self):
        s=self.source();s['cash_policy']=None
        self.assertIn('LOCAL_CASH_POLICY_NOT_BOUND',self.review(s)['reasons'])
    def test_no_daily_limit_required(self):
        self.assertFalse(self.review()['daily_loss_limit_required'])
    def test_signed_reservation_wrong_reference_rejected(self):
        s=self.source();v=s['cash_reservations']['p1'];v['plan_fingerprint']='changed';self.resign(v)
        with self.assertRaisesRegex(ValueError,'SIGNED_RESERVATION_BINDING_MISMATCH'):self.review(s)
    def test_pending_stop_blocks(self):
        s=self.source();s['stop_state']=[1,0]
        with self.assertRaisesRegex(ValueError,'UNHANDLED_OR_UNKNOWN_STOP_STATE'):self.review(s)
    def test_unknown_stop_blocks(self):
        s=self.source();s['stop_state']=None
        with self.assertRaisesRegex(ValueError,'UNHANDLED_OR_UNKNOWN_STOP_STATE'):self.review(s)
    def test_controller_authority_claim_blocks(self):
        s=self.source();s['control']['production_execution_enabled']=True
        with self.assertRaisesRegex(ValueError,'CLOSED_CONTROLLER_REQUIRED'):self.review(s)
    def test_missing_position_not_flat(self):
        snap=deepcopy(self.b.snapshot);snap['positions']=[]
        r=self.review(snapshot=snap);self.assertIn('MISSING_POSITION_ROW_IS_NOT_FLAT',r['reasons'])
    def test_position_mismatch_blocks(self):
        snap=deepcopy(self.b.snapshot);snap['positions'][0]['quantity']=64
        self.assertIn('BOUND_BUY_FILL_POSITION_QUANTITY_MISMATCH',self.review(snapshot=snap)['reasons'])
    def test_partial_entry_blocks(self):
        snap=deepcopy(self.b.snapshot);snap['orders'][0].update(filled=30,pending=35,status='PARTIAL')
        snap['trades'][0]['quantity']=30;snap['positions'][0]['quantity']=30
        self.assertIn('FULLY_FILLED_ENTRY_REQUIRED',self.review(snapshot=snap)['reasons'])
    def test_extra_same_symbol_order_not_owned(self):
        snap=deepcopy(self.b.snapshot);extra=deepcopy(snap['orders'][0]);extra.update(order_id='UNRELATED',filled=0,pending=0,status='CANCELLED')
        snap['orders'].append(extra)
        r=self.review(snapshot=snap)
        self.assertIn('UNLINKED_ACCOUNT_ORDER_PREVENTS_POSITION_RECONCILIATION',r['reasons'])
    def test_fixture_cannot_pass_live_mode(self):
        snap=deepcopy(self.b.snapshot);snap['signature']=sign(snap,self.pin)
        with self.assertRaisesRegex(ValueError,'OWNERSHIP_EVIDENCE_MODE_MISMATCH'):
            reconcile_entry(self.source(),snap,self.pin,as_of=self.b.at)
    def test_fees_and_net_pnl_remain_unknown(self):
        r=self.review();self.assertIsNone(r['realized_net_pnl_paise']);self.assertIsNone(r['open_net_pnl_paise'])
    def test_stale_current_account_rejected(self):
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_STALE_OR_FUTURE'):
            self.review(at='2026-10-29T05:30:31+00:00')
    def test_nested_cash_tamper_rejected_even_after_outer_resign(self):
        bundle=self.b.bundle();bundle['cash_capture']['funds_before']['cash_available_to_trade']='999'
        self.b.replace_bundle(bundle)
        # Update the signed reservation to match the newly persisted outer bundle.
        s=self.source();binding=s['bindings']['p1'];v=s['cash_reservations']['p1']
        v.update(plan_fingerprint=binding['plan_fingerprint'],outbox_fingerprint=binding['outbox_fingerprint']);self.resign(v)
        with self.assertRaisesRegex(ValueError,'NESTED_CASH_SIGNATURE_INVALID'):self.review(s)
    def test_empty_account_stays_blocked_without_zero_pnl(self):
        s=self.source()
        for key in ('plans','holds','outbox','bindings','receipts','cash_reservations','evidence'):
            s[key]={}
        s['requests']=[];s['attempts']=[];s['cash_policy']=None
        for key in s['counts']:s['counts'][key]=0
        snap=deepcopy(self.b.snapshot)
        snap.update(orders=[],trades=[],positions=[])
        r=self.review(s,snap)
        self.assertEqual(r['status'],'BLOCKED_ENTRY_OWNERSHIP_GAPS')
        self.assertIn('NO_BOUND_APPLICATION_ENTRY',r['reasons'])
        self.assertIsNone(r['reviewed_remaining_entry_quantity'])
        self.assertIsNone(r['realized_net_pnl_paise'])
    def test_capture_barrier_rejects_changed_reservation(self):
        from check import consistent_review
        before=self.source();after=deepcopy(before)
        after['cash_reservations']['p1']['state']='UNKNOWN_HOLD_RETAINED'
        readings=iter([before,after])
        snap=deepcopy(self.b.snapshot);snap['signature']=sign(snap,self.pin)
        with self.assertRaisesRegex(ValueError,'LOCAL_SOURCES_CHANGED_DURING_CAPTURE'):
            consistent_review(lambda:next(readings),lambda:snap,self.pin,
                              clock=lambda:self.b.at,mode='OFFLINE_FIXTURE')
    def test_capture_barrier_valid_fixture(self):
        from check import consistent_review
        s=self.source();snap=deepcopy(self.b.snapshot);snap['signature']=sign(snap,self.pin)
        r=consistent_review(lambda:deepcopy(s),lambda:snap,self.pin,
                            clock=lambda:self.b.at,mode='OFFLINE_FIXTURE')
        self.assertTrue(r['fixture_entry_quantity_reconciled'])
    def test_barrier_includes_changed_cursor(self):
        from check import consistent_review
        before=self.source();after=deepcopy(before);after['source_cursors']=[(1,'changed')]
        readings=iter([before,after]);snap=deepcopy(self.b.snapshot)
        with self.assertRaisesRegex(ValueError,'LOCAL_SOURCES_CHANGED_DURING_CAPTURE'):
            consistent_review(lambda:next(readings),lambda:snap,self.pin,
                              clock=lambda:self.b.at,mode='OFFLINE_FIXTURE')
    def test_armed_controller_rejected(self):
        s=self.source();s['control']['mode']='ARMED'
        with self.assertRaisesRegex(ValueError,'CLOSED_CONTROLLER_REQUIRED'):self.review(s)
    def test_unknown_adapter_state_blocks_even_with_ack_reference(self):
        request=self.f.request();request['state']='UNKNOWN';self.f.set_request(request)
        self.assertIn('ADAPTER_OUTCOME_NOT_ACKNOWLEDGED',self.review()['reasons'])
    def test_reservation_session_mismatch_rejected(self):
        s=self.source();v=s['cash_reservations']['p1'];v['session_date']='2026-10-28';self.resign(v)
        with self.assertRaisesRegex(ValueError,'ENTRY_SESSION_OR_SIGNAL_LINK_INVALID'):self.review(s)
