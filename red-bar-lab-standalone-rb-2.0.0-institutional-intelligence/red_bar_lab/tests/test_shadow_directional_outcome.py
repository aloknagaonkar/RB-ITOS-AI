import pandas as pd

from red_bar_lab.services.shadow_directional_outcome import evaluate_shadow_outcome


def candles(count=20, step=1.0):
    price = 100.0
    rows = []
    for ts in pd.date_range("2026-08-13 09:15", periods=count, freq="5min"):
        close = price + step
        rows.append({
            "timestamp": ts,
            "open": price,
            "high": max(price, close) + 0.5,
            "low": min(price, close) - 0.5,
            "close": close,
            "volume": 1000,
        })
        price = close
    return pd.DataFrame(rows)


def test_bullish_outcome_measures_future_checkpoints_and_excursions():
    frame = candles()
    transition = {
        "timestamp": str(frame.iloc[5]["timestamp"]),
        "direction": "BULLISH",
    }
    result = evaluate_shadow_outcome(frame, transition)
    assert result.move_after_5m > 0
    assert result.move_after_15m > 0
    assert result.move_after_30m > 0
    assert result.direction_correct_30m is True
    assert result.maximum_favorable_excursion > 0
    assert result.execution_allowed if hasattr(result, "execution_allowed") else True


def test_unfinished_future_window_stays_unresolved():
    frame = candles(count=10)
    transition = {
        "timestamp": str(frame.iloc[7]["timestamp"]),
        "direction": "BULLISH",
    }
    result = evaluate_shadow_outcome(frame, transition)
    assert result.price_after_5m is not None
    assert result.price_after_30m is None
    assert result.direction_correct_30m is None
    assert result.fully_resolved is False


def test_bearish_direction_normalizes_down_move_as_positive():
    frame = candles(step=-1.0)
    transition = {
        "timestamp": str(frame.iloc[5]["timestamp"]),
        "direction": "BEARISH",
    }
    result = evaluate_shadow_outcome(frame, transition)
    assert result.move_after_30m > 0
    assert result.direction_correct_30m is True
