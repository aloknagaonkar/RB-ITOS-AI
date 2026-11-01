from market_lab.midpoint_v2_nifty_futures_vwap_v1 import add_session_vwap
from market_lab.midpoint_v2_oi_futures_vwap_confluence_v1 import metric_summary


def test_vwap_is_prospective_cumulative_only():
    rows = [
        {"timestamp": "2026-08-24T09:15:00+05:30", "open": 99, "high": 101, "low": 99, "close": 100, "volume": 10, "open_interest": 1},
        {"timestamp": "2026-08-24T09:16:00+05:30", "open": 100, "high": 103, "low": 99, "close": 101, "volume": 20, "open_interest": 2},
    ]
    out = add_session_vwap(rows)
    tp1 = (101 + 99 + 100) / 3
    tp2 = (103 + 99 + 101) / 3
    assert out[0]["session_vwap"] == tp1
    assert out[1]["session_vwap"] == (tp1 * 10 + tp2 * 20) / 30


def test_metric_summary():
    s = metric_summary([10.0, -5.0, -5.0])
    assert s["trade_count"] == 3
    assert s["profit_factor"] == 1.0
