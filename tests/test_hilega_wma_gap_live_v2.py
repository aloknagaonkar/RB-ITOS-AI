from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from market_lab.hilega_wma_gap_live_v2 import WmaGapGate, ExitFirstCanonical, HilegaWmaGapLiveCoordinatorV2, STRATEGY_ID
from market_lab.hilega_directional_coordinator_v1 import DirectionalDecision
from market_lab.hilega_milega_strategy_v1 import StrategyEvent, IndicatorSnapshot, FiveMinuteBar
from market_lab.domain import IST
from market_lab.hilega_sandbox_event_bridge_v1 import BridgeConfig,HilegaSandboxEventBridgeV1,IntentStore,BridgeError
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

T=datetime(2026,10,9,10,0,tzinfo=IST)
BE='ENTRY_PATH1_ROUTE_B_STRUCTURAL';SE='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'
BX='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21';SX='STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'
def ev(name,at=T):return StrategyEvent(name,at,'PATH1_ROUTE_B','ARMED','ACTIVE',price=100,entry_time=at,entry_price=100)
def obs(e,w):return IndicatorSnapshot(e+1,e,w)
def test_fresh_signal_arms_then_later_minute_confirms():
 g=WmaGapGate();g.signal(ev(BE),T)
 g.previous={'minute':T-timedelta(minutes=1),'snapshot':obs(45,40.8),'wma_change':.8}
 events,checks=g.evaluate(minute=T,current=obs(46,41),reference=obs(40,40),price=101)
 assert not events and checks[0]['previous_gap'] is not None and not checks[0]['persistence_pass']
 events,checks=g.evaluate(minute=T+timedelta(minutes=1),current=obs(47,41.1),reference=obs(40,40),price=102)
 assert len(events)==1 and g.owner=='BULLISH' and checks[0]['persistence_pass']
 assert events[0].entry_time==T+timedelta(minutes=2)

def test_exit_boundary_can_reverse_only_with_two_strong_minutes():
 g=WmaGapGate();g.owner='BULLISH';g.active={'time':T-timedelta(minutes=10),'price':100}
 g.previous={'minute':T-timedelta(minutes=1),'snapshot':obs(35,40),'wma_change':-.9}
 closed=g.close(ev(BX),T+timedelta(minutes=1),99);assert closed.points==-1
 g.signal(ev(SE),T+timedelta(minutes=1))
 events,checks=g.evaluate(minute=T,current=obs(33,39),reference=obs(41,40),price=99,exit_boundary=True)
 assert len(events)==1 and g.owner=='BEARISH'
 assert checks[0]['same_exit_boundary_confirmation'] and checks[0]['persistence_pass']

@pytest.mark.parametrize('previous_change,previous_minute',[(.9,T-timedelta(minutes=1)),(-.2,T-timedelta(minutes=1)),(-.9,T-timedelta(minutes=2))])
def test_exit_boundary_does_not_bypass_strength_or_contiguity(previous_change,previous_minute):
 g=WmaGapGate();g.previous={'minute':previous_minute,'snapshot':obs(35,40),'wma_change':previous_change};g.signal(ev(SE),T+timedelta(minutes=1))
 events,checks=g.evaluate(minute=T,current=obs(33,39),reference=obs(41,40),price=99,exit_boundary=True)
 assert not events and not checks[0]['persistence_pass'] and 'BEARISH' in g.pending

def test_equality_waits_and_window_expires():
 g=WmaGapGate();g.signal(ev(BE),T);g.pending['BULLISH']['armed_at']=T-timedelta(minutes=2)
 g.previous={'minute':T-timedelta(minutes=1),'snapshot':obs(46,41),'wma_change':1}
 events,checks=g.evaluate(minute=T,current=obs(46,41),reference=obs(40,40),price=101)
 assert not events and not checks[0]['gap_expanding_pass']
 g.evaluate(minute=T+timedelta(minutes=10),current=obs(47,41),reference=obs(40,40),price=102)
 assert not g.pending

def test_exit_candle_canonical_reversal_v1_invariants_preserved():
 c=ExitFirstCanonical();c.session_date=T.date();c.trade_owner='BULLISH';c.bullish.session.active=False;c.bearish.session.active=True
 bar=FiveMinuteBar(T,100,101,99,100,None)
 decision=c._coordinate(bar=bar,bullish_events=[ev(BX)],bearish_events=[ev(SE)])
 assert [e.event_type for e in decision.accepted_events][:2]==[BX,SE]
 assert c.trade_owner=='BEARISH' and c.bearish.session.active

def test_bridge_exit_before_entry_and_strategy_isolation(tmp_path):
 source=tmp_path/'audit.jsonl';out=tmp_path/'intents.jsonl';store=ShadowStepAuditStoreV1(source)
 def record(names,strategy=STRATEGY_ID):
  store.append(event_time=T,checkpoint=T,stage='DIRECTIONAL_DECISION',status='PROCESSED',payload={'strategy_id':strategy,'decision_timestamp':(T+timedelta(minutes=5)).isoformat(),'accepted_events':names})
 record([BE],'HILEGA_DIRECTIONAL_SHADOW_V1')
 record([BE]);record([BX,SE]);record([SX,BE])
 bridge=HilegaSandboxEventBridgeV1(BridgeConfig(True,source,out));bridge.run_once();rows=IntentStore(out).rows()
 assert len(rows)==6 and all(r['decision']=='WOULD_SUBMIT' for r in rows)
 assert [r['event_type'] for r in rows]==['ENTRY','ENTRY','EXIT','ENTRY','EXIT','ENTRY']
 assert rows[1]['trade_id']!=rows[0]['trade_id']
 assert rows[-1]['event_timestamp']==(T+timedelta(minutes=5)).isoformat()
 assert bridge.run_once()['written']==0

def test_bridge_rejects_two_entries(tmp_path):
 source=tmp_path/'audit';store=ShadowStepAuditStoreV1(source)
 store.append(event_time=T,checkpoint=T,stage='DIRECTIONAL_DECISION',status='PROCESSED',payload={'accepted_events':[BE,SE]})
 with pytest.raises(BridgeError):HilegaSandboxEventBridgeV1(BridgeConfig(True,source,tmp_path/'out')).run_once()

def test_missing_minute_waits_no_synthetic_candles(tmp_path):
 sources=SimpleNamespace();c=HilegaWmaGapLiveCoordinatorV2(market_sources=sources,option_expiry=None,step_audit_path=tmp_path/'audit',health_path=tmp_path/'health')
 c._last_minute=T-timedelta(minutes=1);c._advance=Mock()
 minute=SimpleNamespace(timestamp=T+timedelta(minutes=1),open=100,high=100,low=100,close=100)
 assert c._consume([minute],T+timedelta(minutes=2),recovered=False)==0
 c._advance.assert_not_called()

def test_day_rollover_resets_owner_and_pending(tmp_path):
 sources=SimpleNamespace(warmup_candles=lambda *a:[],nifty_intraday_1m=lambda **k:[])
 c=HilegaWmaGapLiveCoordinatorV2(market_sources=sources,option_expiry=None,step_audit_path=tmp_path/'audit',health_path=tmp_path/'health',warmup_calendar_days=0)
 c._restore_audited_option_state=Mock(return_value={})
 c.gate.owner='BEARISH';c.gate.locked=True;c.gate.signal(ev(BE),T)
 c.bootstrap(T+timedelta(days=1))
 assert c.gate.owner=='NONE' and not c.gate.locked and not c.gate.pending

def test_recovered_decisions_never_submit_or_resolve_options(tmp_path):
 sources=SimpleNamespace();c=HilegaWmaGapLiveCoordinatorV2(market_sources=sources,option_expiry=T.date(),step_audit_path=tmp_path/'audit',health_path=tmp_path/'health')
 c.canonical.bullish.indicators=SimpleNamespace(update=lambda close:obs(47,41))
 c.canonical.bullish.previous_indicators=obs(40,40)
 c.gate.signal(ev(BE),T);c.gate.pending['BULLISH']['armed_at']=T-timedelta(minutes=2)
 c.gate.previous={'minute':T-timedelta(minutes=1),'snapshot':obs(45,40.9),'wma_change':.9}
 c._start_option=Mock();c._close_option=Mock()
 c._advance(SimpleNamespace(timestamp=T,open=100,high=100,low=100,close=100),{},recovered=True)
 assert c.gate.owner=='BULLISH';c._start_option.assert_not_called();c._close_option.assert_not_called()
 rows=c.step_audit.read_all();assert all(r['status']=='RECOVERED' for r in rows)

@pytest.mark.parametrize('fail',[None,7])
def test_sandbox_run_once_exit_acknowledgements_precede_replacement_buys(tmp_path,monkeypatch,fail):
 from market_lab import hilega_upstox_sandbox_basket_v2 as m
 source=tmp_path/'audit';out=tmp_path/'intents';audit=ShadowStepAuditStoreV1(source)
 for names in ([BE],[SE,BX]):
  audit.append(event_time=T,checkpoint=T,stage='DIRECTIONAL_DECISION',status='PROCESSED',payload={'strategy_id':STRATEGY_ID,'accepted_events':names})
 class Broker:
  def __init__(self):self.calls=[]
  def resolve_five(self,side,day):
   return [dict(role=i,instrument_key=f'{side}-{i}',lot_size=65,expiry='2026-10-13',strike=22300+i*50,option_type='CE' if side=='BULLISH' else 'PE') for i in range(-2,3)]
  def instrument_ltp(self,key):return 100
  def place_market(self,**kwargs):
   self.calls.append(kwargs)
   if len(self.calls)==fail:raise TimeoutError()
   return str(len(self.calls))
 broker=Broker();cfg=SimpleNamespace(lots=1,assert_ready=lambda _:None)
 monkeypatch.setattr(m.SandboxConfig,'from_env',lambda _:cfg)
 monkeypatch.setattr(m,'strategy',lambda _:STRATEGY_ID)
 monkeypatch.setenv('HILEGA_SANDBOX_BRIDGE_SOURCE',str(source));monkeypatch.setenv('HILEGA_SANDBOX_BRIDGE_OUTPUT',str(out))
 w=m.BasketWorker(control=tmp_path/'control',journal=tmp_path/'orders',transport=broker,clock=lambda:T)
 w.control.write({'armed':True,'kill_switch':False,'session_date':T.date().isoformat(),'strategy_id':STRATEGY_ID,'baseline_source_sequence':0})
 w.run_once()
 if fail is None:
  assert [r['transaction_type'] for r in broker.calls]==['BUY']*5+['SELL']*5+['BUY']*5
  assert all(r['direction']=='BEARISH' for r in w.store.open_legs())
 else:
  assert len(broker.calls)==10 and w.control.read()['entries_blocked']
 count=len(broker.calls);w.run_once();assert len(broker.calls)==count

def test_no_entry_at_cutoff_even_when_all_market_conditions_pass():
 t=T.replace(hour=14,minute=54);g=WmaGapGate();g.signal(ev(BE),t-timedelta(minutes=1))
 g.pending['BULLISH']['armed_at']=t-timedelta(minutes=1)
 g.previous={'minute':t-timedelta(minutes=1),'snapshot':obs(45,40.8),'wma_change':.8}
 events,checks=g.evaluate(minute=t,current=obs(46,41),reference=obs(40,40),price=101)
 assert not events and 'SESSION_CUTOFF' in checks[0]['reasons']

def test_delayed_option_boundary_and_retry_preserve_canonical_signal_label():
 from test_hilega_milega_option_shadow_lifecycle_v1 import _candidate_set,_minute_source
 from market_lab.hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
 label=datetime(2026,9,23,10,15,tzinfo=IST);boundary=label+timedelta(minutes=8)
 tracker=HilegaMilegaOptionShadowLifecycleV1()
 s=tracker.start(signal_bar_ts=label,signal_boundary_ts=boundary,signal_spot=23393.25,source='V2',candidate_set=_candidate_set(),option_minutes=lambda _:[])
 assert s.status=='INCOMPLETE' and s.signal_bar==label.isoformat() and s.signal_boundary==boundary.isoformat()
 s=tracker.retry_missing_entry(option_minutes=_minute_source(boundary))
 assert s.active and s.signal_boundary==boundary.isoformat()

def test_live_adapter_emits_same_boundary_exit_then_entry_with_exact_times(tmp_path):
 c=HilegaWmaGapLiveCoordinatorV2(market_sources=SimpleNamespace(),option_expiry=None,step_audit_path=tmp_path/'audit',health_path=tmp_path/'health')
 t=T+timedelta(minutes=4);at=t+timedelta(minutes=1)
 c.canonical.bullish.indicators=SimpleNamespace(update=lambda close:obs(33,40))
 c.canonical.bullish.previous_indicators=obs(45,41)
 c.canonical.on_bar=Mock(return_value=DirectionalDecision(T.isoformat(),'BULLISH','BEARISH',(ev(BX),ev(SE)),(),'IDLE','ACTIVE',False,False))
 c.gate.owner='BULLISH';c.gate.active={'time':T-timedelta(minutes=5),'price':100}
 c.gate.previous={'minute':t-timedelta(minutes=1),'snapshot':obs(35,41),'wma_change':-.9}
 calls=Mock();c._close_option=calls.close;c._start_option=calls.start
 bar=FiveMinuteBar(T,100,101,99,99,None)
 c._advance(SimpleNamespace(timestamp=t,open=99,high=99,low=99,close=99),{T:bar},recovered=False)
 assert [call[0] for call in calls.mock_calls]==['close','start']
 assert calls.close.call_args.kwargs['exit_boundary']==at
 assert calls.start.call_args.kwargs['bar'].ts==T
 assert calls.start.call_args.kwargs['event'].entry_time==at
 records=c.step_audit.read_all();p=next(r['payload'] for r in records if r['stage']=='DIRECTIONAL_DECISION')
 assert p['accepted_events']==[BX,SE] and p['decision_timestamp']==at.isoformat()
 assert c.gate.owner=='BEARISH'

def test_new_live_policy_cannot_be_relabelled_as_old_forward_control(tmp_path):
 from market_lab.hilega_wma_gap_live_v2 import assert_forward_control_strategy
 source=tmp_path/'audit';store=ShadowStepAuditStoreV1(source)
 store.append(event_time=T,checkpoint=T,stage='DIRECTIONAL_DECISION',status='PROCESSED',payload={'strategy_id':STRATEGY_ID})
 with pytest.raises(ValueError,match='SEPARATE_FORWARD_COHORT'):assert_forward_control_strategy(T.date().isoformat(),source)
 assert_forward_control_strategy((T-timedelta(days=1)).date().isoformat(),source)

def test_cutoff_state_is_explicitly_locked_in_current_session_audit(tmp_path):
 sources=SimpleNamespace();c=HilegaWmaGapLiveCoordinatorV2(market_sources=sources,option_expiry=None,step_audit_path=tmp_path/'audit',health_path=tmp_path/'health')
 t=T.replace(hour=14,minute=55);minute=SimpleNamespace(timestamp=t,open=100)
 c.process_cutoff(t,intraday=[minute])
 p=c.step_audit.read_all()[-1]['payload']
 assert p['bullish_state']==p['bearish_state']=='SESSION_LOCKED' and p['trade_owner_after']=='NONE'
 assert c.process_cutoff(t,intraday=[minute]) is None
