import pandas as pd

from red_bar_lab.services.shadow_directional_replay import ShadowDirectionalReplayService
from red_bar_lab.services.shadow_directional_comparison import compare_shadow_to_current_engine


def candles(count=80, step=1.0):
    price = 100.0
    rows = []
    for i, ts in enumerate(pd.date_range("2026-08-13 09:15", periods=count, freq="5min")):
        close = price + step
        rows.append({
            "timestamp": ts,
            "open": price,
            "high": max(price, close) + 0.5,
            "low": min(price, close) - 0.5,
            "close": close,
            "volume": 1000 + i,
        })
        price = close
    return pd.DataFrame(rows)


def test_replay_is_walk_forward_and_produces_summary():
    service = ShadowDirectionalReplayService()
    rows = service.replay(candles())
    summary = service.summarize(rows)
    assert summary.evaluated > 0
    assert summary.resolved_5m > 0
    assert summary.accuracy_5m is not None
    assert all(row["execution_allowed"] is False for row in rows)


def test_regime_summary_groups_results():
    service = ShadowDirectionalReplayService()
    rows = service.replay(candles())
    regimes = service.summarize_by_regime(rows)
    assert regimes
    assert "regime" in regimes[0]


def test_comparison_calculates_shadow_lead_minutes():
    shadow = [{
        "timestamp": "2026-08-13 10:00:00",
        "direction": "BULLISH",
    }]
    current = [{
        "confirmation_timestamp": "2026-08-13 10:10:00",
        "direction": "BULLISH",
    }]
    rows = compare_shadow_to_current_engine(shadow, current)
    assert rows[0]["shadow_lead_minutes"] == 10.0
    assert rows[0]["shadow_was_earlier"] is True
