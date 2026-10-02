from datetime import datetime
from market_lab.midpoint_aug25_same_day_window_replay_v1 import aggregate_5m, floor_5m, in_window

def test_floor_5m():
    t = datetime.fromisoformat("2026-08-25T09:34:00+05:30")
    assert floor_5m(t).isoformat() == "2026-08-25T09:30:00+05:30"

def test_in_window():
    t = datetime.fromisoformat("2026-08-25T13:50:00+05:30")
    assert in_window(t, "13:40", "14:30")
    assert not in_window(t, "09:15", "09:55")

def test_aggregate_5m():
    rows = [
        {"timestamp": datetime.fromisoformat("2026-08-25T09:15:00+05:30"), "open":100.0,"high":101.0,"low":99.0,"close":100.5,"volume":10},
        {"timestamp": datetime.fromisoformat("2026-08-25T09:16:00+05:30"), "open":100.5,"high":102.0,"low":100.0,"close":101.5,"volume":20},
    ]
    out = aggregate_5m(rows)
    assert len(out) == 1
    assert out[0]["open"] == 100.0
    assert out[0]["high"] == 102.0
    assert out[0]["low"] == 99.0
    assert out[0]["close"] == 101.5
    assert out[0]["volume"] == 30
