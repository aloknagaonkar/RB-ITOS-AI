from market_lab.oi_pm2_directional_imbalance_persistence_v1 import sign, aligned

def test_sign():
    assert sign(5)==1
    assert sign(-5)==-1
    assert sign(0)==0

def test_alignment():
    assert aligned("BULLISH_TREND_DAY", 1)
    assert not aligned("BULLISH_TREND_DAY", -1)
    assert aligned("BEARISH_TREND_DAY", -1)
    assert not aligned("BEARISH_TREND_DAY", 1)
