"""Run on the Ubuntu VM against the staged backend, never a running service."""
from datetime import datetime,timedelta,time,date
from types import SimpleNamespace as Obj
from itertools import product
import math
import pytest
from market_lab.hilega_three_minute_v1 import session as timing
from market_lab.hilega_three_minute_v1 import hilega_combined_policy_v1 as policy
from market_lab.hilega_three_minute_v1.hilega_milega_strategy_v1 import IndicatorSnapshot,StrategyEvent,FiveMinuteBar
from market_lab.hilega_three_minute_v1.hilega_v2_alignment_replay_v1 import dual_exit
from market_lab.domain import IST

def at(s):return datetime.fromisoformat('2026-10-26T'+s+':00+05:30')
def minute(stamp,close=100):return Obj(timestamp=stamp,open=100.0,high=max(101.,close),low=min(99.,close),close=float(close),volume=10)
def frame(stamp,side='BULLISH'):
    bull=side=='BULLISH'
    return dict(available_at=stamp.isoformat(),rsi_available_at=stamp.isoformat(),open=100.,high=110.,low=90.,close=105. if bull else 95.,
        ema10=100.,previous_ema10=99. if bull else 101.,previous_rsi9=50.,rsi9=52. if bull else 48.,
        ema3_rsi=49. if bull else 51.,wma21_rsi=46. if bull else 54.,previous_wma21_rsi=45. if bull else 55.,previous_ema3_rsi=47. if bull else 53.)

@pytest.mark.parametrize('gap,strength,previous_gap,count,passes',[
    (2.,.75,1.,3,True),(2.,.2,1.,2,True),(2.,.75,3.,2,True),
    (-1.,.75,-2.,2,True),(2.,.2,3.,1,False),(-1.,.2,-2.,1,False),
    (-1.,.75,0.,1,False),(-1.,.2,0.,0,False)])
def test_vote_combinations(gap,strength,previous_gap,count,passes):
    ev=timing.strength_gap_evidence(gap,previous_gap,strength,True)
    assert ev['strength_gap_pass_count']==count
    assert ev['strength_gap_pass'] is passes

@pytest.mark.parametrize('bad',[None,float('nan'),float('inf'),True])
def test_missing_evidence_cannot_be_bypassed(bad):
    assert timing.strength_gap_evidence(2.,1.,bad,True)['strength_gap_pass'] is False

def test_three_of_three_control():
    assert timing.strength_gap_evidence(2.,1.,.2,True,minimum=3)['strength_gap_pass'] is False
    assert timing.strength_gap_evidence(2.,1.,.75,True,minimum=3)['strength_gap_pass'] is True

@pytest.mark.parametrize('clock,expected',[('09:15',False),('09:18',True),('09:20',False),('09:21',True),('14:54',True),('14:55',False),('14:57',True),('15:27',True),('15:30',True),('15:33',False)])
def test_boundaries(clock,expected):assert timing.is_boundary(at(clock)) is expected

def test_full_session_has_125_bars_and_includes_last_minute():
    rows=[minute(at('09:15')+timedelta(minutes=i),100+i/10) for i in range(375)]
    bars=timing.aggregate_exact_3m(rows,date(2026,10,26),require_full_session=True)
    assert len(bars)==125 and bars[0].ts==at('09:15') and bars[-1].ts==at('15:27')
    assert bars[-1].close==rows[-1].close and bars[-1].volume==30

def test_partial_duplicate_and_missing_candles_block():
    with pytest.raises(ValueError,match='INCOMPLETE'):timing.aggregate_exact_3m([minute(at('09:15'))],date(2026,10,26))
    with pytest.raises(ValueError,match='DUPLICATE'):timing.exact_rows([minute(at('09:15'))]*2,at('09:18'))
    with pytest.raises(ValueError,match='MISSING'):timing.aggregate_exact_3m([],date(2026,10,26),require_full_session=True)

def test_unfinished_minutes_not_visible():
    assert not timing.exact_rows([minute(at('09:17'))],at('09:17'))
    assert len(timing.exact_rows([minute(at('09:17'))],at('09:18')))==1

@pytest.mark.parametrize('side',['BULLISH','BEARISH'])
def test_followup_is_next_three_minute_candle(side):
    waiting=dict(time=at('10:00'),due=at('10:03'),close=100.,midpoint=100.)
    assert policy.followup_check(side,waiting,frame(at('10:03'),side),at('10:03'),require_direction=True)['passed']
    assert not policy.followup_check(side,waiting,frame(at('10:05'),side),at('10:05'),require_direction=True)['passed']

def test_continued_followup_keeps_original_reference():
    waiting=dict(time=at('10:00'),due=at('10:06'),close=100.,midpoint=100.)
    ev=policy.followup_check('BULLISH',waiting,frame(at('10:06')),at('10:06'),require_direction=True,continued=True)
    assert ev['passed'] and ev['signal_time']==at('10:00').isoformat()

def test_followup_still_checks_direction():
    waiting=dict(time=at('10:00'),due=at('10:03'),close=100.,midpoint=100.)
    f=frame(at('10:03'));f['rsi9']=49.
    assert not policy.followup_check('BULLISH',waiting,f,at('10:03'),require_direction=True)['passed']

def test_bullish_extra_minima_remain_separate():
    f=frame(at('10:00'));f['ema3_rsi']=47.;f['wma21_rsi']=46.
    ev=dict(passed=True,reasons=[]);policy.apply_gap(ev,f,2)
    assert not ev['passed']
    frames={at('10:00'):frame(at('10:00')),at('10:03'):frame(at('10:03'))}
    frames[at('10:03')]['wma21_rsi']=46.9
    ev=dict(passed=True,reasons=[]);policy.apply_magnitude(ev,dict(time=at('10:00')),frames,at('10:03'),2)
    assert not ev['passed']
    frames[at('10:03')]['wma21_rsi']=47.
    ev=dict(passed=True,reasons=[]);policy.apply_magnitude(ev,dict(time=at('10:00')),frames,at('10:03'),2)
    assert ev['passed']

@pytest.mark.parametrize('side',['BULLISH','BEARISH'])
def test_gate_accepts_strength_failure_when_other_two_pass(side):
    gate=policy.DirectFive(opposite_switch=True)
    event=StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at('10:00'),None,'IDLE','ARMED')
    gate.signal(event,at('10:00'))
    ref=IndicatorSnapshot(55,51,50) if side=='BULLISH' else IndicatorSnapshot(45,49,50)
    current=IndicatorSnapshot(56,52.2,50.2) if side=='BULLISH' else IndicatorSnapshot(44,47.8,49.8)
    entries,checks=gate.evaluate(minute=at('10:00')-timedelta(minutes=1),current=current,reference=ref,price=100.)
    assert len(entries)==1 and checks[0]['strength_gap_pass_count']==2
    assert checks[0]['wma_threshold_pass'] is False

def test_no_1455_cutoff_and_no_entry_at_session_close():
    for clock,allowed in [('14:57',True),('15:27',True),('15:30',False)]:
        gate=policy.DirectFive(opposite_switch=True)
        e=StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at(clock),None,'IDLE','ARMED')
        gate.signal(e,at(clock))
        entries,checks=gate.evaluate(minute=at(clock)-timedelta(minutes=1),current=IndicatorSnapshot(55,53,51),reference=IndicatorSnapshot(54,51,50),price=100.)
        assert bool(entries) is allowed

def test_exit_equality_and_dual_requirement():
    assert dual_exit('BULLISH',IndicatorSnapshot(48,49,50))
    assert not dual_exit('BULLISH',IndicatorSnapshot(48,50,50))
    assert dual_exit('BEARISH',IndicatorSnapshot(52,51,50))

def test_close_uses_last_completed_minute_not_nonexistent_1530_open():
    rows=[minute(at('15:29'),123.),minute(at('15:30'),999.)]
    assert timing.session_close_price(rows,at('15:30'))==123.
    assert timing.session_close_price([],at('15:30')) is None

def test_pending_and_monitor_reset():
    gate=policy.make_gate({});gate._bullish_exit_monitor=object();gate.pending={'BULLISH':{}}
    gate.followup_signal={'due':at('15:30')};gate.watch_side='BULLISH'
    policy.reset_pending(gate)
    assert not gate.pending and gate.followup_signal is None and gate._bullish_exit_monitor is None

def test_live_cutoff_is_idempotent_and_uses_final_close():
    from market_lab.hilega_three_minute_v1.hilega_alignment_dual_exit_live_v1 import HilegaAlignmentDualExitLiveCoordinator as Live
    gate=policy.make_gate({});gate.owner='BULLISH';gate.active=dict(time=at('15:00'),price=100.)
    closed=[];audits=[]
    live=Obj(gate=gate,_cutoff_done_date=None,canonical=Obj(on_session_cutoff=lambda *args:None),
        _last_bar_ts=at('15:27'),directional=Obj(bullish=Obj(session=Obj(name='IDLE')),bearish=Obj(session=Obj(name='IDLE'))),
        _decision=lambda *args:args,_audit=lambda *args,**kwargs:audits.append(args),
        _close_option=lambda **kwargs:closed.append(kwargs))
    cutoff=getattr(Live,'_process_cutoff_from_rows',Live.process_cutoff)
    assert cutoff(live,at('14:57'),intraday=[]) is None
    assert cutoff(live,at('15:30'),intraday=[]) is None
    assert gate.owner=='BULLISH' and live._cutoff_done_date is None
    cutoff(live,at('15:30'),intraday=[minute(at('15:29'),110.)])
    assert gate.owner=='NONE' and gate.locked and len(closed)==1
    assert closed[0]['exit_reason']=='SESSION_END_1530'
    assert cutoff(live,at('15:31'),intraday=[minute(at('15:29'),110.)]) is None
    assert len(closed)==1

def test_live_consume_uses_three_minute_buckets_after_old_cutoff():
    seen=[]
    def advance(row,bars,**kwargs):
        live._last_minute=row.timestamp
        if timing.is_boundary(row.timestamp+timedelta(minutes=1)):seen.append((row.timestamp,tuple(bars)))
    live=Obj(_last_minute=at('14:53'),_advance=advance,_health=lambda *args,**kwargs:None)
    rows=[minute(at('14:54')+timedelta(minutes=i)) for i in range(6)]
    assert timing.consume_minutes(live,rows,at('15:00'),recovered=False)==6
    assert [r[0] for r in seen]==[at('14:56'),at('14:59')]
    assert at('14:54') in seen[0][1] and at('14:57') in seen[1][1]

@pytest.mark.parametrize('price_route',[False,True])
def test_real_gate_followup_routes_and_recovery(price_route):
    frames={at('10:00'):dict(frame(at('10:00'),'BEARISH'),rsi9=45.,previous_rsi9=46.,
            ema3_rsi=47.,wma21_rsi=50.,previous_ema3_rsi=49.,previous_wma21_rsi=51.)}
    if price_route:
        frames[at('10:03')]=dict(frame(at('10:03'),'BEARISH'),open=95.,close=94.,
            rsi9=44.,previous_rsi9=45.,ema3_rsi=47.2,wma21_rsi=50.1,previous_ema3_rsi=47.,previous_wma21_rsi=50.)
    else:
        frames[at('10:03')]=dict(frame(at('10:03'),'BEARISH'),open=102.,high=103.,close=101.,
            rsi9=44.,previous_rsi9=45.,ema3_rsi=45.8,wma21_rsi=49.8,previous_ema3_rsi=47.,previous_wma21_rsi=50.)
    def run():
        gate=policy.make_gate(frames)
        gate.signal(StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at('10:00'),None,'IDLE','ARMED'),at('10:00'))
        entries,checks=gate.evaluate(minute=at('09:59'),current=IndicatorSnapshot(45,47,50),reference=IndicatorSnapshot(46,49,51),price=95.)
        assert not entries and gate.followup_signal['due']==at('10:03')
        f=frames[at('10:03')]
        entries,checks=gate.evaluate(minute=at('10:02'),current=IndicatorSnapshot(f['rsi9'],f['ema3_rsi'],f['wma21_rsi']),reference=IndicatorSnapshot(45,47,50),price=f['close'])
        assert len(entries)==1 and gate.owner=='BEARISH'
        ev=checks[0]['ema10_entry']
        assert ev['entry_confirmation_route']==('PRICE' if price_route else 'FRESH_CHECKS')
        assert checks[0]['strength_gap_pass_count']==(1 if price_route else 2)
        return [(e.event_time,e.entry_price) for e in entries]
    assert run()==run()  # Fresh reconstruction reproduces the same decision.

@pytest.mark.parametrize('wma,closed',[(40.,False),(39.,False),(40.1,True)])
def test_bearish_normal_exit_keeps_strict_wma40_permission(wma,closed):
    current=IndicatorSnapshot(wma+2,wma+1,wma)
    canonical=Obj(on_bar=lambda bar:Obj(accepted_events=[]),bullish=Obj(previous_indicators=current))
    gate=policy.make_gate({});gate.owner='BEARISH';gate.active=dict(time=at('10:00'),price=100.)
    tracker=Obj(complete=lambda *args:{})
    result=policy._advance_standard(canonical,gate,FiveMinuteBar(at('10:03'),100,101,99,100,1),current,tracker)
    assert bool(result['exits']) is closed
    assert result['exit_validation']['normal_exit_pass'] is closed
