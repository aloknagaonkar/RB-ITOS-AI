import copy,json,sys,tempfile,unittest,uuid
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'files/backend'))
import market_lab
# Regular packages ignore earlier namespace-only directories on sys.path.
market_lab.__path__ = [str(HERE / "files" / "backend" / "market_lab")] + list(market_lab.__path__)
# Repo supplied on VM; fixture repo optional locally.
repo=Path.cwd()/'backend/market_lab'
if not repo.exists():repo=HERE.parent/'source/RB-ITOS-AI-feature-pcr-foundation/backend/market_lab'
market_lab.__path__.append(str(repo))
from market_lab import hilega_manual_exit_v1 as m
class Control:
 def __init__(self):self.c=dict(armed=True,kill_switch=False,sandbox_only=True,live_execution_enabled=False,session_date='2026-10-14',strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT')
 def read(self):return copy.deepcopy(self.c)
 def write(self,c):self.c=copy.deepcopy(c)
class Store:
 def __init__(self,path):self.path=path;self.rs=[]
 def rows(self):return copy.deepcopy(self.rs)
 def append(self,r):self.rs.append(copy.deepcopy(r))
 def open_legs(self):
  active={}
  for r in self.rs:
   if r.get('status')!='ACCEPTED':continue
   key=(r['trade_id'],r['role'])
   if r['event_type']=='ENTRY':active[key]=r
   else:active.pop(key,None)
  return copy.deepcopy(list(active.values()))
 def uncertain(self):
  done={r.get('request_id') for r in self.rs if r.get('status') in {'ACCEPTED','REQUEST_RESOLVED_NO_FILL'}}
  return copy.deepcopy([r for r in self.rs if r.get('status')=='REQUESTED' and r['request_id'] not in done])
class Transport:
 def __init__(self):self.orders={};self.calls=[];self.cancelled=[];self.timeout=False;self.auto_complete=True;self.bad=False
 def add(self,oid,instrument='K0',side='BUY',qty=50,filled=50,status='complete',tag=None):
  self.orders[oid]=dict(order_id=oid,instrument_token=instrument,transaction_type=side,quantity=qty,filled_quantity=filled,pending_quantity=qty-filled if status not in m.TERMINAL else 0,average_price=100 if side=='BUY' else 110,status=status,product='I',tag=tag)
 def order_details(self,*,order_id=None,tag=None):
  if self.bad:raise RuntimeError('unavailable')
  if order_id:return copy.deepcopy(self.orders[order_id])
  for d in self.orders.values():
   if d.get('tag')==tag:return copy.deepcopy(d)
  raise RuntimeError('unknown order; lookup cannot prove rejection')
 def place_market(self,**kw):
  self.calls.append(kw);oid='SELL'+str(len(self.calls));self.add(oid,kw['instrument_key'],'SELL',kw['quantity'],kw['quantity'] if self.auto_complete else 0,'complete' if self.auto_complete else 'open',kw['tag'])
  if self.timeout:raise TimeoutError()
  return oid
 def cancel_order(self,oid):
  self.cancelled.append(oid);self.orders[oid]['status']='cancelled';self.orders[oid]['pending_quantity']=0
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.at=datetime.fromisoformat('2026-10-14T11:00:00+05:30');self.w=SimpleNamespace(store=Store(Path(self.temp.name)/'basket-events.jsonl'),control=Control(),clock=lambda:self.at);self.tr=Transport();self.addleg()
 def addleg(self,role=0,status='ACCEPTED',oid=None):
  oid=oid or 'BUY'+str(role);rid='R'+str(role)
  self.w.store.append(dict(status=status,terminal=status=='ACCEPTED',request_id=rid,intent_id='I',event_id='E',trade_id='TRADE',event_type='ENTRY',direction='BULLISH',session_date='2026-10-14',strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',event_timestamp='2026-10-14T10:55:00+05:30',source_sequence=5,role=role,contract=dict(instrument_key='K'+str(role),strike=22000+role*50,option_type='CE',lot_size=50,expiry='2026-10-20'),quantity=50,transaction_type='BUY',broker_order_id=oid,observed_option_price=100))
  self.tr.add(oid,'K'+str(role),tag='HIL5_'+rid[:32])
 def request(self,req=None):return m.request_exit(self.w,request_id=req or str(uuid.uuid4()),session_date='2026-10-14',expected_trade_ids=['TRADE'])
 def pump(self):
  with m.worker_lock(self.w):return m.pump(self.w,self.tr)
 def ack(self):
  r=m.current(self.w);m.write(self.w.store.path.parent/'manual-reset-acks.json',{r['request_id']:{'applied_at':self.at.isoformat()}})
 def test_exit_requires_fill_then_reset(self):
  self.request();self.assertTrue(self.pump());self.assertEqual(m.current(self.w)['status'],'VERIFYING');self.assertEqual(len(self.w.store.open_legs()),1)
  self.assertTrue(self.pump());self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET');self.assertFalse(self.w.store.open_legs());self.assertTrue(self.pump());self.ack();self.assertFalse(self.pump());self.assertEqual(m.current(self.w)['status'],'READY_FOR_FRESH_SIGNAL')
 def test_double_click_and_request_retry_are_idempotent(self):
  r=self.request();self.assertEqual(self.request(r['request_id'])['request_id'],r['request_id']);self.assertEqual(self.request()['request_id'],r['request_id']);self.pump();self.pump();self.assertEqual(len(self.tr.calls),1)
 def test_acknowledged_open_sell_does_not_resume(self):
  self.tr.auto_complete=False;self.request();self.pump();self.pump();self.assertEqual(m.current(self.w)['status'],'VERIFYING');self.assertEqual(len(self.tr.calls),1)
 def test_timeout_lookup_recovers_without_duplicate_sell(self):
  self.tr.timeout=True;self.request();self.pump();self.pump();self.assertEqual(len(self.tr.calls),1);self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET')
 def test_missing_lookup_never_retries(self):
  self.tr.timeout=True;self.request();self.pump();self.tr.orders.pop('SELL1');self.pump();self.assertEqual(len(self.tr.calls),1);self.assertEqual(m.current(self.w)['status'],'RECONCILIATION_REQUIRED')
 def test_partial_buy_cancel_then_only_filled_quantity_sold(self):
  self.tr.orders['BUY0'].update(status='open',filled_quantity=25,pending_quantity=25);self.request();self.pump();self.assertFalse(self.tr.calls);self.assertEqual(self.tr.cancelled,['BUY0']);self.pump();self.assertEqual(self.tr.calls[0]['quantity'],25);self.pump();self.assertEqual(m.current(self.w)['legs'][0]['confirmed_pnl_rupees'],250)
 def test_partial_cancelled_sell_retries_only_residual(self):
  self.tr.auto_complete=False;self.request();self.pump();self.tr.orders['SELL1'].update(status='cancelled',filled_quantity=20,pending_quantity=0);self.pump();self.assertEqual(self.tr.calls[1]['quantity'],30)
 def test_unknown_buy_found_by_tag_and_closed(self):
  self.w.store.rs[0]['status']='REQUESTED';self.request();self.pump();self.pump();self.assertFalse(self.w.store.uncertain());self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET')
 def test_rejected_unknown_buy_needs_no_sell(self):
  self.w.store.rs[0]['status']='REQUESTED';self.tr.orders['BUY0'].update(status='rejected',filled_quantity=0,pending_quantity=0);self.request();self.pump();self.assertFalse(self.tr.calls);self.assertFalse(self.w.store.uncertain());self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET')
 def test_recovered_buy_crash_before_state_persist(self):
  self.w.store.rs[0]['status']='REQUESTED';self.request();self.w.store.append(dict(self.w.store.rs[0],status='ACCEPTED'));self.pump();self.assertEqual(len(self.tr.calls),1)
 def test_existing_auto_sell_is_reused(self):
  self.request();self.tr.add('AUTO','K0','SELL');self.w.store.append(dict(self.w.store.rs[0],status='ACCEPTED',event_type='EXIT',transaction_type='SELL',broker_order_id='AUTO',request_id='AUTO'));self.pump();self.assertFalse(self.tr.calls);self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET')
 def test_identity_mismatch_cannot_flatten(self):
  self.tr.orders['BUY0']['instrument_token']='OTHER';self.request();self.pump();self.assertFalse(self.tr.calls);self.assertEqual(m.current(self.w)['status'],'RECONCILIATION_REQUIRED')
 def test_other_known_legs_exit_despite_one_bad_leg(self):
  self.addleg(1);self.tr.orders['BUY0']['instrument_token']='OTHER';self.request();self.pump();self.assertEqual(len(self.tr.calls),1);self.assertEqual(self.tr.calls[0]['instrument_key'],'K1')
 def test_preserve_existing_safety_block(self):
  self.w.control.c.update(entries_blocked=True,failure_reason='OTHER');self.request();self.pump();self.pump();self.ack();self.assertTrue(self.pump());self.assertTrue(self.w.control.c['entries_blocked'])
 def test_stale_session_rejected(self):
  with self.assertRaisesRegex(ValueError,'STALE_SESSION'):m.request_exit(self.w,request_id=str(uuid.uuid4()),session_date='2026-10-13',expected_trade_ids=['TRADE'])
 def test_stale_trade_snapshot_rejected(self):
  with self.assertRaisesRegex(ValueError,'POSITION_CHANGED'):m.request_exit(self.w,request_id=str(uuid.uuid4()),session_date='2026-10-14',expected_trade_ids=['OTHER'])
 def test_live_mode_rejected(self):
  self.w.control.c['live_execution_enabled']=True
  with self.assertRaisesRegex(ValueError,'SANDBOX_ONLY'):self.request()
 def test_restart_reuses_durable_sell(self):
  self.request();self.pump();self.w=SimpleNamespace(store=self.w.store,control=self.w.control,clock=lambda:self.at);self.pump();self.assertEqual(len(self.tr.calls),1)
 def test_stale_trade_exit_is_consumed_and_fresh_entry_allowed(self):
  self.request();self.pump();self.pump();self.ack();self.pump();old=dict(trade_id='TRADE',event_type='EXIT',event_timestamp=self.at.isoformat());self.assertTrue(m.suppress_intent(self.w,old));fresh=dict(trade_id='NEW',event_type='ENTRY',event_timestamp=(self.at+timedelta(minutes=5)).isoformat());self.assertFalse(m.suppress_intent(self.w,fresh))
 def test_old_pending_signal_suppressed(self):
  self.request();self.pump();self.pump();self.ack();self.pump();self.assertTrue(m.suppress_intent(self.w,dict(trade_id='NEW',event_type='ENTRY',event_timestamp='2026-10-14T10:59:00+05:30')))
 def test_retries_bounded(self):
  self.tr.auto_complete=False;self.request();self.pump()
  for i in range(1,4):
   self.tr.orders['SELL'+str(i)].update(status='rejected',pending_quantity=0);self.pump()
  self.assertEqual(len(self.tr.calls),3);self.assertEqual(m.current(self.w)['status'],'RECONCILIATION_REQUIRED')
 def test_bad_complete_evidence_rejected(self):
  d=self.tr.order_details(order_id='BUY0');d['filled_quantity']=25
  with self.assertRaisesRegex(ValueError,'INCONSISTENT_COMPLETE'):m.order_evidence(d,instrument='K0',side='BUY',quantity=50)
 def test_stalled_known_sell_cancel_then_terminal_recovery(self):
  self.tr.auto_complete=False;self.request();self.pump();self.at+=timedelta(seconds=61);self.pump();self.assertEqual(self.tr.cancelled,['SELL1']);self.tr.auto_complete=True;self.pump();self.pump();self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET')
 def test_only_captured_resolved_uncertainty_block_cleared(self):
  self.w.control.c.update(entries_blocked=True,failure_reason='SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED',failed_at=self.at.isoformat());self.w.store.rs[0]['status']='REQUESTED';self.request();self.pump();self.pump();self.ack();self.assertFalse(self.pump());self.assertFalse(self.w.control.c['entries_blocked'])
 def test_new_block_not_cleared(self):
  self.w.control.c.update(entries_blocked=True,failure_reason='SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED',failed_at=self.at.isoformat());self.request();self.pump();self.pump();self.w.control.c['failed_at']='2026-10-14T11:01:00+05:30';self.ack();self.assertTrue(self.pump());self.assertTrue(self.w.control.c['entries_blocked'])
 def test_fill_quantity_regression_stops_recovery(self):
  self.tr.auto_complete=False;self.request();self.pump();self.tr.orders['SELL1'].update(filled_quantity=10,pending_quantity=40);self.pump();self.tr.orders['SELL1'].update(filled_quantity=0,pending_quantity=50);self.pump();self.assertEqual(m.current(self.w)['status'],'RECONCILIATION_REQUIRED');self.assertEqual(len(self.tr.calls),1)
 def test_count_does_not_count_synthetic_flat_marker_as_extra_order(self):
  self.request();self.pump();self.pump();self.assertEqual(m.accepted_order_count(self.w),2)
 def test_first_fresh_minute_after_confirmation_is_not_suppressed(self):
  from market_lab import hilega_manual_exit_strategy_v1 as sm
  from market_lab.hilega_milega_strategy_v1 import SessionState
  from market_lab.hilega_milega_bearish_strategy_v1 import BearishSessionState
  self.request();self.pump();self.pump()
  c=SimpleNamespace(strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',manual_exit_root=self.w.store.path.parent,gate=SimpleNamespace(owner='BULLISH',active={},pending={},locked=False),canonical=SimpleNamespace(bullish=SimpleNamespace(session=SessionState(active=True)),bearish=SimpleNamespace(session=BearishSessionState()),trade_owner='BULLISH'),episode={},warning_time=None)
  self.assertFalse(sm.apply_manual_control(c,self.at+timedelta(minutes=1),recovered=True));self.assertEqual(c.gate.owner,'NONE')
 def test_coordinator_reset_never_unlocks_cutoff(self):
  from market_lab import hilega_manual_exit_strategy_v1 as sm
  from market_lab.hilega_milega_strategy_v1 import SessionState
  from market_lab.hilega_milega_bearish_strategy_v1 import BearishSessionState
  self.request();self.pump();self.pump()
  c=SimpleNamespace(strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',manual_exit_root=self.w.store.path.parent,gate=SimpleNamespace(owner='BULLISH',active={},pending={},locked=True),canonical=SimpleNamespace(bullish=SimpleNamespace(session=SessionState(session_locked=True)),bearish=SimpleNamespace(session=BearishSessionState(session_locked=True)),trade_owner='BULLISH'),episode={},warning_time=None)
  sm.apply_manual_control(c,self.at,recovered=True);self.assertTrue(c.gate.locked);self.assertTrue(c.canonical.bullish.session.session_locked)
 def test_five_legs_fully_closed(self):
  for role in [-2,-1,1,2]:self.addleg(role)
  self.request();self.pump();self.pump();self.assertEqual(len(self.tr.calls),5);self.assertFalse(self.w.store.open_legs());self.assertEqual(m.current(self.w)['status'],'WAITING_FOR_STRATEGY_RESET')
 def test_coordinator_reset_preserves_indicators_and_replays_once(self):
  from market_lab import hilega_manual_exit_strategy_v1 as sm
  from market_lab.hilega_milega_strategy_v1 import SessionState
  from market_lab.hilega_milega_bearish_strategy_v1 import BearishSessionState
  self.request();self.pump();self.pump();indicator=object();prior=object()
  c=SimpleNamespace(strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',manual_exit_root=self.w.store.path.parent,gate=SimpleNamespace(owner='BULLISH',active={},pending={'BULLISH':{}},locked=False),canonical=SimpleNamespace(bullish=SimpleNamespace(session=SessionState(active=True),indicators=indicator,previous_indicators=prior),bearish=SimpleNamespace(session=BearishSessionState()),trade_owner='BULLISH'),episode={},warning_time='x')
  self.assertTrue(sm.apply_manual_control(c,self.at,recovered=True));self.assertEqual(c.gate.owner,'NONE');self.assertIs(c.canonical.bullish.indicators,indicator);self.assertIs(c.canonical.bullish.previous_indicators,prior);self.assertFalse(c.gate.pending);self.assertTrue(c.episode['BULLISH']);self.assertFalse(sm.apply_manual_control(c,self.at+timedelta(minutes=1),recovered=True))
if __name__=='__main__':unittest.main()
