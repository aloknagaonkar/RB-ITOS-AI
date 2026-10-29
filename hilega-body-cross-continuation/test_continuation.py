"""VM-only rule-boundary tests; no local execution claimed."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import rules,strict_rules

def frame(**kw):
    f=dict(open=110,high=111,low=95,close=96,ema10=112,previous_ema10=113)
    f.update(kw);return f

def test_below_falling_qualifies_only_extended():
    assert strict_rules.qualify('BEARISH',frame()) is None
    assert rules.qualify('BEARISH',frame())['qualification_route']=='BEARISH_ALREADY_BELOW'

def test_original_bear_cross_preserved():
    q=rules.qualify('BEARISH',frame(ema10=105,previous_ema10=106))
    assert q['qualification_route']=='BODY_CROSS'

def test_bear_continuation_requires_red():
    assert rules.qualify('BEARISH',frame(open=96,close=110)) is None

def test_bear_continuation_rejects_flat_or_rising_ema():
    for previous in [112,111]:assert rules.qualify('BEARISH',frame(previous_ema10=previous)) is None

def test_continuation_strict_body_ratio_above_sixty():
    assert rules.qualify('BEARISH',frame(open=110,close=98,high=110,low=90)) is None

def test_bear_body_above_ema_rejected():
    assert rules.qualify('BEARISH',frame(ema10=94,previous_ema10=95)) is None

def test_open_equal_ema_rejected():
    assert rules.qualify('BEARISH',frame(ema10=110,previous_ema10=111)) is None

def test_bullish_already_above_not_added():
    assert rules.qualify('BULLISH',frame(open=96,close=110,ema10=94,previous_ema10=93)) is None

def test_bullish_cross_unchanged():
    f=frame(open=96,close=110,ema10=103,previous_ema10=102)
    assert rules.qualify('BULLISH',f)['qualification_route']=='BODY_CROSS'
    assert strict_rules.qualify('BULLISH',f)

def test_oct26_0915_now_arms_but_next_close_cancels():
    f=dict(open=22524.4,high=22524.4,low=22470.05,close=22480.05,
        ema10=22531.762995871428,previous_ema10=22543.254772731743)
    q=rules.qualify('BEARISH',f)
    assert q and q['qualification_route']=='BEARISH_ALREADY_BELOW'
    # Observed 09:16-labelled candle close, available 09:17: no entry.
    assert rules.decision(q,22510.5)=='CANCEL_MIDPOINT'

def test_oct26_0917_can_form_new_bearish_reference():
    f=dict(open=22510.55,high=22511.15,low=22458.3,close=22463.25,
        ema10=22516.142997236242,previous_ema10=22527.896996622076)
    q=rules.qualify('BEARISH',f)
    assert q and q['qualification_route']=='BEARISH_ALREADY_BELOW'
    assert rules.decision(q,22446.8)=='ENTRY'

def test_pending_and_protection_equality_hold():
    q=rules.qualify('BEARISH',frame())
    assert rules.decision(q,q['midpoint'])=='WAIT'
    assert not rules.midpoint_exit('BEARISH',q['midpoint'],q['midpoint'])
