import pandas as pd

from red_bar_lab.intelligence.directional_features import latest_directional_features


def _candles(count=80, volume=0.0):
    rows = []
    price = 100.0
    for i, timestamp in enumerate(
        pd.date_range("2026-08-13 09:15", periods=count, freq="5min")
    ):
        close = price + 1.0
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": close + 0.4,
                "low": price - 0.3,
                "close": close,
                "volume": volume,
            }
        )
        price = close
    return pd.DataFrame(rows)


def test_zero_index_volume_does_not_block_directional_snapshot():
    snapshot = latest_directional_features(_candles(volume=0.0))
    assert snapshot.volume_ratio == 1.0
    assert snapshot.atr > 0
    assert snapshot.ema_fast_slope_atr > 0


def test_missing_volume_baseline_falls_back_to_neutral_ratio():
    frame = _candles(volume=1000.0)
    frame.loc[frame.index[-15:], "volume"] = 0.0
    snapshot = latest_directional_features(frame)
    assert snapshot.volume_ratio == 1.0
