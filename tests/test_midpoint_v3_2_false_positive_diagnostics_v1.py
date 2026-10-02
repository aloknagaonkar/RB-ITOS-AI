from market_lab.midpoint_v3_2_false_positive_diagnostics_v1 import (
    stats,
    economic_summary,
)

def test_stats():
    x = stats([1.0, 2.0, 3.0])
    assert x["count"] == 3
    assert x["median"] == 2.0
    assert x["mean"] == 2.0

def test_economic_summary():
    rows = [
        {
            "gross_returns_pct": {"1m": 2.0, "3m": 3.0, "5m": 4.0, "10m": 5.0, "15m": 6.0},
            "net_returns_pct": {"1m": 1.5, "3m": 2.5, "5m": 3.5, "10m": 4.5, "15m": 5.5},
            "mfe_pct_15m": 10.0,
            "mae_pct_15m": -3.0,
        },
        {
            "gross_returns_pct": {"1m": -2.0, "3m": -3.0, "5m": -4.0, "10m": -5.0, "15m": -6.0},
            "net_returns_pct": {"1m": -2.5, "3m": -3.5, "5m": -4.5, "10m": -5.5, "15m": -6.5},
            "mfe_pct_15m": 4.0,
            "mae_pct_15m": -8.0,
        },
    ]
    out = economic_summary(rows)
    assert out["count"] == 2
    assert out["gross_1m"]["median"] == 0.0
    assert out["mfe_15m"]["median"] == 7.0
    assert out["mae_15m"]["median"] == -5.5
