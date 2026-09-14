from market_lab.midpoint_v2_red_midpoint_structural_stop_v1 import (
    metric_summary,
    replay_midpoint_stop,
)

def _ts(hm):
    return f"2026-09-07T{hm}:00+05:30"

def test_midpoint_close_reclaim_exits_next_open():
    underlying = {
        ("2026-09-07", _ts("09:29")): {"close": 23840.0, "high": 23845.0, "low": 23835.0},
        ("2026-09-07", _ts("09:30")): {"close": 23851.0, "high": 23855.0, "low": 23840.0},
        ("2026-09-07", _ts("09:31")): {"close": 23852.0, "high": 23856.0, "low": 23845.0},
    }
    option = {
        ("PE", _ts("09:29")): {"open": 100.0, "high": 103.0, "low": 95.0, "close": 98.0},
        ("PE", _ts("09:30")): {"open": 98.0, "high": 99.0, "low": 93.0, "close": 94.0},
        ("PE", _ts("09:31")): {"open": 92.0, "high": 94.0, "low": 90.0, "close": 91.0},
    }
    r = replay_midpoint_stop(
        underlying, option, "2026-09-07", "PE", _ts("09:29"), 100.0, 23849.775
    )
    assert r["available"] is True
    assert r["exit_reason"] == "MIDPOINT_CLOSE_RECLAIM_NEXT_OPEN"
    assert r["exit_timestamp"] == _ts("09:31")
    assert r["exit_price"] == 92.0

def test_wick_above_midpoint_does_not_invalidate():
    underlying = {}
    option = {}
    start_h = 9
    start_m = 29
    for i in range(16):
        total = start_h * 60 + start_m + i
        hm = f"{total//60:02d}:{total%60:02d}"
        underlying[("2026-09-07", _ts(hm))] = {
            "close": 23845.0,
            "high": 23860.0,  # wick above midpoint
            "low": 23830.0,
        }
        option[("PE", _ts(hm))] = {
            "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0
        }
    r = replay_midpoint_stop(
        underlying, option, "2026-09-07", "PE", _ts("09:29"), 100.0, 23849.775
    )
    assert r["available"] is True
    assert r["exit_reason"] == "TIME15_NO_MIDPOINT_RECLAIM"
    assert r["net_return_pct"] == 4.5

def test_metric_summary_profit_factor():
    s = metric_summary([10.0, -5.0, -5.0])
    assert s["trade_count"] == 3
    assert s["profit_factor"] == 1.0
