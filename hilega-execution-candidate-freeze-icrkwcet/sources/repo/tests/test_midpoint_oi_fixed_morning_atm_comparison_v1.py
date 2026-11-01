from market_lab.midpoint_oi_fixed_morning_atm_feature_extractor_v1 import pct
from market_lab.midpoint_oi_fixed_vs_moving_atm_comparison_v1 import qtile

def test_pct():
    assert pct(105,100)==5.0

def test_qtile():
    assert qtile([1,2,3,4],.5)==2.5
