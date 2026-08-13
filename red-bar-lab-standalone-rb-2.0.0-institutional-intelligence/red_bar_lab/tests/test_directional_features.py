import pandas as pd
import pytest

from red_bar_lab.intelligence.directional_features import (
    build_directional_feature_frame,
    latest_directional_features,
)


def candles(count=80, step=1.0):
    rows = []
    price = 100.0
    for index, timestamp in enumerate(
        pd.date_range("2026-08-13 09:15", periods=count, freq="5min")
    ):
        open_price = price
        close = price + step
        rows.append(
            {
                "timestamp": timestamp,
                "open": open_price,
                "high": max(open_price, close) + 0.4,
                "low": min(open_price, close) - 0.3,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
        price = close
    return pd.DataFrame(rows)


def test_feature_builder_produces_normalized_trend_features():
    snapshot = latest_directional_features(candles())
    assert snapshot.atr > 0
    assert snapshot.ema_fast_slope_atr > 0
    assert snapshot.plus_di > snapshot.minus_di
    assert snapshot.displacement_atr > 0
    assert snapshot.price_above_fast is True
    assert snapshot.price_above_slow is True


def test_feature_builder_rejects_incomplete_schema():
    with pytest.raises(ValueError, match="Missing required candle columns"):
        build_directional_feature_frame(pd.DataFrame({"close": [1.0]}))


def test_feature_builder_requires_enough_completed_history():
    with pytest.raises(ValueError, match="Insufficient completed candle history"):
        latest_directional_features(candles(count=10))
