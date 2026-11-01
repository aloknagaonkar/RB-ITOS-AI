from datetime import datetime, timezone, timedelta

from market_lab.midpoint_v3_2_exit_management_research_v1 import (
    Policy,
    replay_policy,
)

IST = timezone(timedelta(hours=5, minutes=30))

def series(entry_ts, bars):
    out = {}
    for i, b in enumerate(bars):
        ts = entry_ts + timedelta(minutes=i)
        out[ts.isoformat()] = {
            "timestamp": ts,
            "open": b[0],
            "high": b[1],
            "low": b[2],
            "close": b[3],
        }
    return out

def test_gap_through_stop_uses_open():
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=IST)
    p = Policy("X", 10.0, None, None, None, 15)
    s = series(ts, [(89, 91, 88, 90)] + [(90, 91, 89, 90)] * 14)
    r = replay_policy(entry=100, entry_ts=ts, series=s, policy=p)
    assert r["exit_reason"] == "STOP_GAP"
    assert r["exit_price"] == 89

def test_stop_touch_uses_stop_price():
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=IST)
    p = Policy("X", 10.0, None, None, None, 15)
    s = series(ts, [(100, 101, 89, 95)] + [(95, 96, 94, 95)] * 14)
    r = replay_policy(entry=100, entry_ts=ts, series=s, policy=p)
    assert r["exit_reason"] == "STOP_TOUCH"
    assert r["exit_price"] == 90

def test_trailing_update_only_active_next_bar():
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=IST)
    p = Policy("X", 10.0, None, 5.0, 5.0, 15)
    bars = [(100, 110, 94, 108), (108, 109, 103, 104)] + [(104, 105, 103, 104)] * 13
    r = replay_policy(entry=100, entry_ts=ts, series=series(ts, bars), policy=p)
    # bar1 high=110 creates next-bar trail at 104.5; bar1 low 94 cannot use that new trail.
    assert r["exit_reason"] == "STOP_TOUCH"
    assert abs(r["exit_price"] - 104.5) < 1e-9

def test_time_exit():
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=IST)
    p = Policy("X", None, None, None, None, 15)
    bars = [(100, 102, 99, 101)] * 15
    r = replay_policy(entry=100, entry_ts=ts, series=series(ts, bars), policy=p)
    assert r["exit_reason"] == "TIME_EXIT"
    assert r["exit_price"] == 101
