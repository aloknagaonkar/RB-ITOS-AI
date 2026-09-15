from market_lab.midpoint_oi_pm5_feature_extractor_v1 import pct
from market_lab.midpoint_oi_band_comparison_v1 import qtile

def test_pct():
    assert pct(110,100)==10.0

def test_qtile():
    assert qtile([1,2,3,4],.5)==2.5
