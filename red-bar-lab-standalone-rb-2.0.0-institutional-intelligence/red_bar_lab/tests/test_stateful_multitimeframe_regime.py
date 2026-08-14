import pandas as pd

from red_bar_lab.intelligence.stateful_multitimeframe_regime import (
    StatefulMultiTimeframeRegimeEngine,
)
from red_bar_lab.services.stateful_regime_store import StatefulRegimeStore


def candles(count=80, step=1.0):
    price = 100.0
    rows = []
    for ts in pd.date_range("2026-08-13 09:15", periods=count, freq="1min"):
        close = price + step
        rows.append({
            "timestamp": ts,
            "open": price,
            "high": max(price, close) + 0.3,
            "low": min(price, close) - 0.3,
            "close": close,
            "volume": 0,
        })
        price = close
    return pd.DataFrame(rows)


def test_bullish_multitimeframe_regime():
    snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
        candles(100, 1.0),
        candles(80, 2.0),
    )
    assert snapshot.current_regime in {"BULLISH", "TRANSITION_BULLISH"}
    assert snapshot.bullish_score > snapshot.bearish_score
    assert snapshot.execution_allowed is False


def test_bearish_multitimeframe_regime():
    snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
        candles(100, -1.0),
        candles(80, -2.0),
    )
    assert snapshot.current_regime in {"BEARISH", "TRANSITION_BEARISH"}
    assert snapshot.bearish_score > snapshot.bullish_score


def test_store_deduplicates(tmp_path):
    store = StatefulRegimeStore(tmp_path / "state.jsonl")
    record = {
        "instrument_key": "NIFTY",
        "timestamp": "2026-08-13T10:00:00",
        "current_regime": "BULLISH",
    }
    assert store.append_once(record) is True
    assert store.append_once(record) is False
    assert store.latest()["execution_allowed"] is False
