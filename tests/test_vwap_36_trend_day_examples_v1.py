
from market_lab.vwap_36_trend_day_examples_v1 import aligned_side, aligned_slope, is_aligned

def test_bull_alignment():
    assert aligned_side("BULLISH_TREND_DAY")=="ABOVE"
    assert aligned_slope("BULLISH_TREND_DAY")=="RISING"
    assert is_aligned("BULLISH_TREND_DAY",{"side":"ABOVE"})

def test_bear_alignment():
    assert aligned_side("BEARISH_TREND_DAY")=="BELOW"
    assert aligned_slope("BEARISH_TREND_DAY")=="FALLING"
    assert is_aligned("BEARISH_TREND_DAY",{"side":"BELOW"})
