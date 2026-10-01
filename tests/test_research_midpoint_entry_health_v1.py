from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT = Path("scripts/research_midpoint_entry_health_v1.py")
if not SCRIPT.exists():
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / SCRIPT.name
SPEC = importlib.util.spec_from_file_location("entry_health_tested", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def candle(close, *, open_=None, high=None, low=None, volume=100, vwap=None):
    return {
        "open": close if open_ is None else open_,
        "high": close + 1 if high is None else high,
        "low": close - 1 if low is None else low,
        "close": close,
        "volume": volume,
        "vwap": close if vwap is None else vwap,
    }


def session(prices):
    underlying, futures = {}, {}
    start = datetime.fromisoformat("2026-09-30T09:15:00+05:30")
    for offset, price in enumerate(prices):
        timestamp = (start + timedelta(minutes=offset)).isoformat()
        underlying[timestamp] = candle(price)
        futures[timestamp] = candle(price + 10, vwap=price + 8)
    return {"2026-09-30": {"underlying": underlying, "futures": futures}}


def test_indicator_series_is_causal_for_earlier_timestamp():
    base = session([100 + index for index in range(30)])
    first = MODULE.build_indicator_series(base)
    key = "2026-09-30T09:30:00+05:30"
    observed = dict(first["2026-09-30"][key])
    changed = session([100 + index for index in range(16)] + [1000] * 14)
    second = MODULE.build_indicator_series(changed)
    assert second["2026-09-30"][key] == observed


def test_closed_five_minute_value_does_not_change_inside_bucket():
    state = MODULE.FiveMinuteState()
    values = []
    for minute in range(15, 26):
        values.append(state.update(
            f"2026-09-30T09:{minute:02d}:00+05:30", float(minute)
        )["rsi5m_closed"])
    assert values[5:10].count(values[5]) == 5


def test_bullish_and_bearish_edges_are_symmetric():
    rows = session([100 + index for index in range(80)])
    raw = MODULE.build_indicator_series(rows)["2026-09-30"]
    latest = raw[sorted(raw)[-1]]
    bull = MODULE.directional_health(latest, "BULLISH")
    bear = MODULE.directional_health(latest, "BEARISH")
    assert round(bull["precision_edge"], 10) == round(-bear["precision_edge"], 10)
    assert round(bull["community_edge"], 10) == round(-bear["community_edge"], 10)


def test_uptrend_produces_supportive_ema_structure():
    rows = session([100 + index * 0.5 for index in range(100)])
    raw = MODULE.build_indicator_series(rows)["2026-09-30"]
    health = MODULE.directional_health(raw[sorted(raw)[-1]], "BULLISH")
    assert health["ema_5_13_support"] == 1.0
    assert health["ema_9_21_support"] == 1.0
    assert health["ema_9_21_50_stack"] == 1.0


def test_future_snapshot_after_structural_exit_is_unavailable():
    raw = candle(100)
    indicators = {
        "2026-09-30": {
            "2026-09-30T09:30:00+05:30": {
                **raw,
                "ema5": 99, "ema9": 99, "ema13": 98, "ema21": 98,
                "ema34": 97, "ema50": 96, "rsi8": 60, "rsi14": 60,
                "macd": 1, "macd_signal": 0, "macd_hist": 1,
                "macd_hist_change": 0.1, "atr10": 2, "atr14": 2,
                "atr10_mean42": 2, "plus_di": 30, "minus_di": 10,
                "adx": 25, "rsi5m_closed": 55, "ema9_5m_closed": 100,
                "ema21_5m_closed": 99, "futures_volume_ratio20": 1.3,
                "futures_open": 100, "futures_close": 101,
                "futures_vwap": 99,
            }
        }
    }
    trade = {
        "session_date": "2026-09-30", "family": "E", "direction": "BULLISH",
        "entry_timestamp": "2026-09-30T09:30:00+05:30", "plus20": False,
        "selected_exit_policy": "STRUCTURAL_BASELINE",
        "selected_exit_timestamp": "2026-09-30T09:31:00+05:30",
        "selected_exit_points": -10,
    }
    row = MODULE.trade_health_row(trade, "MORNING", [], indicators, "IS")
    assert row["t1_available"] is False
    assert row["t3_available"] is False


def test_reported_safety_is_hard_coded_observation_only():
    source = SCRIPT.read_text()
    assert '"execution_enabled": False' in source
    assert '"paper_order_enabled": False' in source
    assert '"quantity": None' in source
    assert '"order_sent": False' in source
