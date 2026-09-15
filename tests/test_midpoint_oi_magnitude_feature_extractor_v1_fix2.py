from market_lab.midpoint_oi_magnitude_feature_extractor_v1_fix2 import (
    outcome_from_event, net5_from_event
)

def test_quality_bucket_winner():
    e={"quality_bucket":"EXCELLENT_5M_GE_10","option_economics":{"net_5m_pct":12.3}}
    assert outcome_from_event(e)=="WINNER"
    assert net5_from_event(e)==12.3

def test_quality_bucket_good_winner():
    e={"quality_bucket":"GOOD_5M_3_TO_10","option_economics":{"net_5m_pct":5.0}}
    assert outcome_from_event(e)=="WINNER"

def test_small_win_excluded():
    e={"quality_bucket":"SMALL_WIN_5M_0_TO_3","option_economics":{"net_5m_pct":1.0}}
    assert outcome_from_event(e)=="SMALL_WIN"

def test_loss_groups():
    assert outcome_from_event({"quality_bucket":"LOSS_5M_0_TO_MINUS5"})=="LOSER"
    assert outcome_from_event({"quality_bucket":"LARGE_LOSS_5M_LE_MINUS5"})=="LOSER"

def test_nested_fallback():
    e={"option_economics":{"net_5m_pct":7.0}}
    assert outcome_from_event(e)=="WINNER"
