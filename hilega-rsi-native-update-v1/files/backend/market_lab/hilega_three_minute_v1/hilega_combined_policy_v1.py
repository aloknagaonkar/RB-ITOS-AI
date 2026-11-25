"""Native Hilega policy; existing option lifecycle/dispatch contracts are retained."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,time
from types import SimpleNamespace
from ..hilega_rsi_two_route_v1.engine import Engine
from ..hilega_rsi_two_route_v1.reference import Indicators
from .hilega_v2_alignment_replay_v1 import WmaGapGate, direction, ENTRY_TYPES, EXIT_TYPES
from .hilega_milega_strategy_v1 import StrategyEvent

POLICY_ID='RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
VERSION='rsi-two-route-1.0.0-3m-native-confirmed-midpoint'
RULES=dict(version=VERSION,policy_id=POLICY_ID,decision_interval_minutes=3,indicator_timeframe='3m',
    session_end_IST='15:30',cutoff_IST='15:30',same_candle_exit_first=True,
    setup='Normal Route: directional candle colour and close beyond EMA30 High/Low; any 2 of RSI5/9/14/21/28 above55 CE / below45 PE; WMA21(RSI9) above50 CE / below50 PE. WMA_bypass: all5 RSI; WMA available but threshold bypassed.',
    exit='Any: confirmed original signal range midpoint breach AND RSI5/RSI9 opposite50; original ALL_THREE momentum/WMA/EMA30 exit; fully qualified opposite entry; session close15:30.',
    candle_strength_filter=False,followup_filter=False,first_last_15min_filter=False,
    entry_fill_basis='NEXT_MINUTE_OPEN_REFERENCE',option_execution='EXISTING_CONFIGURED_HILEGA_PIPELINE')

def bar_dict(bar):
    return dict(start=bar.ts.isoformat(),open=float(bar.open),high=float(bar.high),low=float(bar.low),close=float(bar.close))

class PriceFrames:
    def __init__(self):
        self.frames={};self.tracker=Indicators();self.count=0;self.engine=None
        self.minute_rows=[];self.sequence=0;self.entry_block_reason=None
    def seed(self,bar):
        self.tracker.update(bar_dict(bar));self.count+=1

class NativeGate(WmaGapGate):
    def __init__(self):
        super().__init__(opposite_switch=False)
        self.policy_events=[];self.native_engine=None;reset_pending(self)
    def close(self,event,at,price):
        closed=super().close(event,at,price)
        if closed and self.native_engine:self.native_engine.active=None
        return closed

def make_gate(frames):return NativeGate()

def reset_pending(gate):
    gate.pending.clear();gate.followup_signal=None;gate.followup_price_permission=None
    gate.followup_failed_at=None;gate.watch_side=None;gate.watch_at=None;gate._bullish_exit_monitor=None

ENTRY={'CE':'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21','PE':'ENTRY_BEARISH_ROUTE_B_STRUCTURAL'}
EXIT={'CE':'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21','PE':'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'}
SIDE={'CE':'BULLISH','PE':'BEARISH'}

def check_payload(a,side):
    ev=a['entry_evaluation'][side];f=a['frame'];at=a['decision_time']
    return dict(ev,direction=SIDE[side],side=side,policy_name=POLICY_ID,policy_id=POLICY_ID,strategy_version=VERSION,
        confirmation_interval_minutes=3,signal_timestamp=f['start'],signal_available_at=at,
        minute_timestamp=(datetime.fromisoformat(at)-timedelta(minutes=1)).isoformat(),decision_timestamp=at,
        status=ev['status'],reasons=ev['blockers'],route_name=ev['selected_route'],passed=ev['status']=='ENTRY',
        frame=deepcopy(f),current_rsi9=f['rsi9'],current_wma21=f['wma21_rsi9'])

def advance_boundary(c,g,bar,reference,tracker,manual_block=False):
    at=bar.ts+timedelta(minutes=3)
    if tracker.engine is None:
        tracker.engine=Engine(str(at.date()));tracker.engine.tracker=tracker.tracker
    e=tracker.engine;g.native_engine=e
    # Existing manual reset clears the gate owner. Retire the matching model
    # owner without fabricating a market fill or changing option ledgers.
    if g.owner=='NONE' and e.active is not None:e.active=None
    indexed={r['timestamp']:r for r in tracker.minute_rows}
    mark=indexed[(at-timedelta(minutes=1)).isoformat()]['close'] if at.time()==time(15,30) else indexed[at.isoformat()]['open']
    from math import isfinite
    if not isfinite(float(mark)) or float(mark)<=0:raise ValueError('INVALID_REFERENCE_MARK')
    dec=c.on_bar(bar)
    a=e.advance(bar_dict(bar),tracker.minute_rows,
        entry_block_reason='MANUAL_EXIT_OR_SESSION_ENTRY_BLOCK' if manual_block else tracker.entry_block_reason)
    tracker.count+=1;frame=a['frame'];frame.update(available_at=at.isoformat(),candle_label=bar.ts.isoformat(),rsi_available_at=at.isoformat(),seeded_bar_count=tracker.count)
    tracker.frames[at]=frame
    checks=[check_payload(a,s) for s in ('CE','PE')];events=[];entries=[]
    for event in a['events']:
        side=event['side'];bull=side=='CE'
        if event['event']=='EXIT':
            trade=e.trades[-1]
            ev=StrategyEvent(EXIT[side],at,trade['route_name'],'ACTIVE','IDLE',price=event['fill'],
                entry_time=datetime.fromisoformat(trade['entry_time']),entry_price=trade['entry_price'],
                exit_reason='; '.join(event['reasons']),points=trade['points'],
                details=dict(policy_id=POLICY_ID,strategy_version=VERSION,native_trade_id=trade['trade_id']))
            events.append(ev)
        else:
            tracker.sequence+=1
            native_id=str(at.date())+'-'+str(tracker.sequence).zfill(3)
            e.active['trade_id']=native_id;event['trade_id']=native_id
            evidence=checks[0 if bull else 1]
            ev=StrategyEvent(ENTRY[side],at,event['route_name'],'IDLE','ACTIVE',price=event['fill'],
                entry_time=at,entry_price=event['fill'],details=dict(policy_id=POLICY_ID,strategy_version=VERSION,
                    native_trade_id=native_id,route_name=event['route_name'],qualified_signal_time=at.isoformat(),
                    wma_gap=deepcopy(evidence),combined_entry=deepcopy(evidence)))
            entries.append(ev)
    g.owner=SIDE[e.active['side']] if e.active else 'NONE'
    g.active=dict(time=datetime.fromisoformat(e.active['entry_time']),price=e.active['entry_price'],route_name=e.active['route_name']) if e.active else None
    if at.time()>=time(15,30):g.locked=True
    reset_pending(g)
    policy_events=[dict(event='RSI_TWO_ROUTE_CHECK',time=at.isoformat(),direction=v['direction'],
        passed=v['passed'],reasons=v['reasons'],route_name=v['route_name'],policy_id=POLICY_ID,strategy_version=VERSION) for v in checks]
    g.policy_events.extend(deepcopy(policy_events))
    exit_validation=a['exit_evaluation']
    if exit_validation is not None:
        exit_validation=dict(exit_validation,direction=SIDE[a['owner_before']],policy_id=POLICY_ID,
            strategy_version=VERSION,decision_interval_minutes=3,session_end_IST='15:30',
            rsi9=frame['rsi9'],rsi5=frame['rsi5'],wma21=frame['wma21_rsi9'],
            rsi_opposite=exit_validation['momentum_exit'],normal_exit_pass=bool(events),
            action='EXIT_AND_REVERSE' if events and entries else 'EXIT' if events else 'HOLD')
    old=c.bullish.previous_indicators
    current=SimpleNamespace(rsi9=frame['rsi9'],wma21_rsi=frame['wma21_rsi9'],ema3_rsi=old.ema3_rsi,
        ready=all(frame.get(k) is not None for k in ('rsi5','rsi9','rsi14','rsi21','rsi28','wma21_rsi9')))
    return dict(decision=replace(dec,accepted_events=tuple(events+entries),suppressed_events=(),trade_owner_after=g.owner),
        current=current,entries=entries,exits=events,checks=checks,
        setups=[dict(time=at.isoformat(),direction=v['direction'],source=v['route_name']) for v in checks if v['selected_route']],
        signals=[],exit_validation=exit_validation,policy_events=policy_events,frame=frame,pending_switches=[],
        opposite_confirmation=None,native_audit=a)
