from datetime import datetime,timedelta
from market_lab.hilega_v2_alignment_replay_v1 import WmaGapGate
from market_lab.hilega_milega_strategy_v1 import StrategyEvent,IndicatorSnapshot
from market_lab.domain import IST
T=datetime(2026,10,13,10,20,tzinfo=IST)
def event(side,arm=False):
 name=('PATH1_ARMED_RSI_CROSS_EMA3_UP' if side=='BULLISH' else 'BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN') if arm else ('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL')
 return StrategyEvent(name,T,None,'IDLE','ARMED')
def test_opposite_confirmed_setup_cancels_old_pending_and_resets_arm():
 g=WmaGapGate(True);g.signal(event('BEARISH'),T);g.pending['BEARISH']['armed_at']=T
 g.signal(event('BULLISH'),T+timedelta(minutes=2))
 assert set(g.pending)=={'BULLISH'} and g.pending['BULLISH']['armed_at'] is None
 assert g.pending['BULLISH']['available']==T+timedelta(minutes=2)
 assert g.take_switches()[0]['reason']=='OPPOSITE_CONFIRMED_SETUP'
def test_opposite_arm_cancels_old_but_does_not_enter_without_setup():
 g=WmaGapGate(True);g.signal(event('BEARISH'),T)
 g.observe_arms([event('BULLISH',True)],T+timedelta(minutes=5))
 assert not g.pending and g.owner=='NONE';assert g.watch_side=='BULLISH'
 assert not g.can_signal('BEARISH',T+timedelta(minutes=6))
 assert g.can_signal('BULLISH',T+timedelta(minutes=6))
def test_persistence_cannot_be_inherited_after_switch():
 g=WmaGapGate(True);g.signal(event('BEARISH'),T);g.pending['BEARISH']['armed_at']=T
 g.signal(event('BULLISH'),T+timedelta(minutes=1))
 minute=T+timedelta(minutes=1);g.previous={'minute':minute-timedelta(minutes=1),'snapshot':IndicatorSnapshot(60,55,50.8),'wma_change':.8}
 entries,checks=g.evaluate(minute=minute,current=IndicatorSnapshot(62,57,51),reference=IndicatorSnapshot(50,45,50),price=100)
 assert not entries and 'WAIT_LATER_PERSISTENCE' in checks[0]['reasons']
 entries,checks=g.evaluate(minute=minute+timedelta(minutes=1),current=IndicatorSnapshot(65,59,51.2),reference=IndicatorSnapshot(50,45,50),price=101)
 assert len(entries)==1 and g.owner=='BULLISH'
def test_actual_position_is_not_reversed_by_candidate():
 g=WmaGapGate(True);g.owner='BEARISH';g.active={'time':T,'price':100}
 g.observe_arms([event('BULLISH',True)],T);g.signal(event('BULLISH'),T)
 assert g.owner=='BEARISH' and not g.pending and not g.take_switches()
def test_arm_watch_expires_and_disabled_mode_preserves_original():
 g=WmaGapGate(True);g.signal(event('BEARISH'),T);g.observe_arms([event('BULLISH',True)],T)
 assert g.can_signal('BEARISH',T+timedelta(minutes=10))
 g=WmaGapGate(False);g.signal(event('BEARISH'),T);g.signal(event('BULLISH'),T)
 assert set(g.pending)=={'BULLISH','BEARISH'}
def test_confirmed_setup_beats_same_boundary_unconfirmed_arm():
 g=WmaGapGate(True);g.signal(event('BEARISH'),T)
 g.observe_arms([event('BULLISH',True),event('BEARISH')],T)
 assert 'BEARISH' in g.pending and not g.take_switches()

def test_new_opposite_arm_can_replace_arm_only_watch():
 g=WmaGapGate(True);g.signal(event('BEARISH'),T)
 g.observe_arms([event('BULLISH',True)],T+timedelta(minutes=1))
 g.observe_arms([event('BEARISH',True)],T+timedelta(minutes=2))
 assert g.watch_side=='BEARISH' and not g.pending
 assert len(g.take_switches())==2
