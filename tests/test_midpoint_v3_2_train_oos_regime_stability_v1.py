from market_lab.midpoint_v3_2_train_oos_regime_stability_v1 import (
    entry_hour_bucket,
    compare_share,
)

def test_hour_bucket_open():
    assert entry_hour_bucket({
        "entry_timestamp": "2026-09-08T09:45:00+05:30"
    }) == "OPEN_TO_10_29"

def test_hour_bucket_midday():
    assert entry_hour_bucket({
        "entry_timestamp": "2026-09-08T12:10:00+05:30"
    }) == "12_00_TO_13_29"

def test_composition_shift():
    t = {"A": {"count": 3, "share_pct": 75.0}}
    o = {"A": {"count": 2, "share_pct": 40.0}}
    x = compare_share(t, o)
    assert x["A"]["share_difference_train_minus_oos_pct_points"] == 35.0
