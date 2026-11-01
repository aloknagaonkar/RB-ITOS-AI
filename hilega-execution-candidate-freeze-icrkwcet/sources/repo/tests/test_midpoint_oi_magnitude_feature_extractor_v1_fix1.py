from market_lab.midpoint_oi_magnitude_feature_extractor_v1_fix1 import outcome_group, floor_5m
from datetime import datetime, timezone

def test_outcome_group():
    assert outcome_group(12) == "WINNER"
    assert outcome_group(5) == "WINNER"
    assert outcome_group(1) == "SMALL_WIN"
    assert outcome_group(-2) == "LOSER"
    assert outcome_group(-8) == "LOSER"

def test_floor_5m():
    ts=datetime(2026,8,25,13,53,tzinfo=timezone.utc)
    out=floor_5m(ts)
    assert out.minute == 50
