from datetime import datetime,timedelta
from types import SimpleNamespace
import pytest
from market_lab import hilega_combined_policy_v1 as p
from market_lab.hilega_v2_alignment_replay_v1 import StrategyEvent

def snap(r=58,e=54,w=51):
    return SimpleNamespace(ready=True,rsi9=r,ema3_rsi=e,wma21_rsi=w)

def fixture():
    at=datetime.fromisoformat('2026-10-16T10:00:00+05:30');frames={}
    g=p.make_gate(frames)
    def frame(t,**updates):
        values=dict(open=100,high=105,low=99,close=102,ema10=99,previous_ema10=98,
            rsi9=58,previous_rsi9=55,ema3_rsi=54,wma21_rsi=51,previous_ema3_rsi=52,previous_wma21_rsi=50,
            available_at=t.isoformat(),rsi_available_at=t.isoformat())
        values.update(updates);frames[t]=values
    frame(at)
    event=StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at,None,'IDLE','ARMED',details={})
    g.signal(event,at)
    return g,at,frames,frame

def evaluate(g,at,current=None,reference=None):
    return g.evaluate(minute=at-timedelta(minutes=1),current=current or snap(),reference=reference or snap(55,52,50),price=102)

def test_signal_is_not_entry_and_has_followup_identity():
    g,at,frames,frame=fixture();entries,checks=evaluate(g,at)
    assert not entries and g.owner=='NONE'
    assert g.followup_signal['time']==at
    assert checks[0]['ema10_entry']['bullish_signal_gap_pass'] is True
    assert checks[0]['persistence_required'] is False

def test_confirmed_followup_passes_bullish_magnitude():
    g,at,frames,frame=fixture();evaluate(g,at);later=at+timedelta(minutes=5)
    frame(later,open=102,close=104,rsi9=62,previous_rsi9=58,ema3_rsi=56,wma21_rsi=52.5,previous_wma21_rsi=51)
    entries,checks=evaluate(g,later,snap(62,56,52.5),snap())
    assert len(entries)==1 and g.owner=='BULLISH'
    assert checks[0]['ema10_entry']['full_wma_magnitude']==2.5

def test_red_followup_never_enters_even_on_price_route():
    g,at,frames,frame=fixture();evaluate(g,at);later=at+timedelta(minutes=5)
    frame(later,open=105,close=104,rsi9=62,previous_rsi9=58,ema3_rsi=56,wma21_rsi=52.5)
    entries,_=evaluate(g,later,snap(62,56,52.5),snap())
    assert not entries and g.owner=='NONE'

def test_touch_retains_original_reference():
    g,at,frames,frame=fixture();evaluate(g,at);later=at+timedelta(minutes=5)
    frame(later,open=102,close=100,low=98,high=103,ema10=99,previous_rsi9=58,rsi9=54)
    entries,_=evaluate(g,later,snap(54,54.5,52.5),snap())
    assert not entries and g.followup_signal['time']==at
    assert g.followup_signal['due']==later+timedelta(minutes=5)

def test_no_touch_discards_reference_but_candidate_survives():
    g,at,frames,frame=fixture();evaluate(g,at);later=at+timedelta(minutes=5)
    frame(later,open=102,close=100,low=100,high=103,ema10=99,previous_rsi9=58,rsi9=54)
    evaluate(g,later,snap(54,54.5,52.5),snap())
    assert g.followup_signal is None and 'BULLISH' in g.pending

def test_manual_reset_clears_reference_without_changing_ema_frames():
    g,at,frames,frame=fixture();evaluate(g,at);p.reset_pending(g)
    assert not g.pending and g.followup_signal is None and at in frames

def test_no_minute_confirmation():
    g,at,frames,frame=fixture();assert evaluate(g,at+timedelta(minutes=1))==([],[])

def test_cutoff_never_opens():
    g,at,frames,frame=fixture();late=at.replace(hour=14,minute=55);frame(late)
    entries,_=evaluate(g,late);assert not entries

def test_only_qualified_opposite_replaces_watch():
    g,at,frames,frame=fixture();g.observe_arms([SimpleNamespace(event_type='BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN')],at)
    assert 'BULLISH' in g.pending
    opposite=StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
    g.signal(opposite,at);assert 'BULLISH' in g.pending and 'BEARISH' not in g.pending

def test_strength_and_gap_reference_is_five_minutes():
    g,at,frames,frame=fixture();_,checks=evaluate(g,at)
    assert checks[0]['previous_timestamp']==(at-timedelta(minutes=6)).isoformat()
    assert checks[0]['gap_reference']=='PREVIOUS_COMPLETED_FIVE_MINUTE'

def test_inspection_has_no_ten_minute_or_persistence_veto():
    from market_lab.hilega_combined_policy_inspection_v1 import inspection
    g,at,frames,frame=fixture();_,checks=evaluate(g,at)
    rows=inspection(dict(checks=checks,policy_events=g.policy_events))
    assert any('bullish signal gap' in row['label'] for row in rows)
    assert not any('Ten-minute window' in row['requirement'] for row in rows)

def test_shared_module_has_no_runtime_research_import_or_source_compilation():
    import inspect
    source=inspect.getsource(p)
    assert 'exec(' not in source and 'inspect.getsource' not in source
    assert 'import hilega_bullish_gap_magnitude_stateful' not in source
