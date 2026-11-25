import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).parent))
import rules,baseline_rules
from profit_protection import profit_check

def frame(**kw):
    f=dict(open=110,high=126,low=109,close=125,ema10=108,previous_ema10=107);f.update(kw);return f

def test_continuation_opt_in():
    assert rules.qualify('BULLISH',frame()) is None
    assert rules.qualify('BULLISH',frame(),True)['qualification_route']=='BULLISH_ALREADY_ABOVE'

def test_strict_bull_cross_remains():
    assert rules.qualify('BULLISH',frame(ema10=115,previous_ema10=114),False)['qualification_route']=='BODY_CROSS'

def test_green_and_rising_required():
    assert rules.qualify('BULLISH',frame(open=125,close=110),True) is None
    assert rules.qualify('BULLISH',frame(previous_ema10=108),True) is None
    assert rules.qualify('BULLISH',frame(previous_ema10=109),True) is None

def test_body_threshold_and_endpoint_equality():
    assert rules.qualify('BULLISH',frame(open=110,close=122,high=125,low=105),True) is None
    assert rules.qualify('BULLISH',frame(ema10=110,previous_ema10=109),True) is None

def test_bear_rule_unchanged():
    f=frame(open=125,close=110,ema10=127,previous_ema10=128)
    assert rules.qualify('BEARISH',f,True)==baseline_rules.qualify('BEARISH',f)
    f.update(ema10=120,previous_ema10=121)
    assert rules.qualify('BEARISH',f,True)==baseline_rules.qualify('BEARISH',f)

def at(t):return datetime.fromisoformat('2026-10-26T'+t+':00+05:30')
def active(**kw):
    x=dict(direction='BULLISH',route='INDEPENDENT_BODY60_1M_BREAKOUT',entry_time=at('10:00').isoformat(),entry_price=100);x.update(kw);return x

def test_activation_does_not_exit_on_same_new_high():
    p=profit_check(active(),at('10:01'),125,at('14:55'),'TRAIL20_10')
    assert not p['passed'] and p['updated_peak_points']==25

def test_after_activation_uses_observed_close():
    p=profit_check(active(profit_peak_points=25),at('10:02'),114,at('14:55'),'TRAIL20_10')
    assert p['passed'] and p['pnl']==14 and p['close']==114

def test_equal_giveback_threshold_triggers():
    assert profit_check(active(profit_peak_points=25),at('10:02'),115,at('14:55'),'TRAIL20_10')['passed']

def test_no_activation_no_profit_exit():
    assert not profit_check(active(profit_peak_points=19),at('10:02'),90,at('14:55'),'TRAIL20_10')['passed']

def test_larger_profile_and_overshoot():
    p=profit_check(active(profit_peak_points=45),at('10:02'),95,at('14:55'),'TRAIL40_20')
    assert p['passed'] and p['pnl']==-5

def test_no_entry_boundary_or_cutoff_check():
    for t in ['10:00','14:55']:
        assert profit_check(active(profit_peak_points=50),at(t),90,at('14:55'),'TRAIL20_10') is None

def test_no_new_bear_or_existing_trade_exit():
    for x in [active(direction='BEARISH'),active(route='EXISTING')]:
        assert profit_check(x,at('10:02'),90,at('14:55'),'TRAIL20_10') is None

def test_baseline_has_no_profit_check():
    assert profit_check(active(),at('10:02'),90,at('14:55'),'MIDPOINT_ONLY') is None

def test_midpoint_equality_holds():
    q=rules.qualify('BULLISH',frame(),True)
    assert not rules.midpoint_exit('BULLISH',q['midpoint'],q['midpoint'])
    assert rules.decision(q,q['midpoint'])=='WAIT'
