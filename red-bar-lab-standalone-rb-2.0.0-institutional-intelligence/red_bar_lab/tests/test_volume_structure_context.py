import pandas as pd

from red_bar_lab.context.volume_structure import (
    build_volume_structure_snapshot,
)


def _candles(rows=90, base=100.0):
    ts = pd.date_range(
        "2026-08-07 09:15",
        periods=rows,
        freq="1min",
        tz="Asia/Kolkata",
    )
    data = []
    price = base
    for i, stamp in enumerate(ts):
        close = price + 0.1
        data.append({
            "timestamp": stamp,
            "open": price,
            "high": close + 0.2,
            "low": price - 0.2,
            "close": close,
            "volume": 100 + i,
        })
        price = close
    return pd.DataFrame(data)


def test_volume_structure_is_pre_entry_only():
    current = _candles()
    signal = {
        "signal_id": "RB-VS",
        "trading_date": "2026-08-07",
        "confirmation_timestamp": "2026-08-07T10:30:00+05:30",
        "underlying_entry": 107.6,
    }

    result = build_volume_structure_snapshot(
        signal=signal,
        instrument_key="NIFTY",
        current_day=current,
    )

    assert result["relative_volume_20m"] is not None
    assert result["volume_trend_5m"] in {
        "RISING", "FALLING", "STABLE", "UNKNOWN"
    }
    assert result["price_volume_state"] in {
        "BULLISH_ACCUMULATION",
        "BEARISH_DISTRIBUTION",
        "WEAK_RALLY",
        "WEAK_DECLINE",
        "NEUTRAL",
        "UNKNOWN",
    }
    assert result["structure_state"] in {
        "COMPRESSION",
        "EXPANSION",
        "RANGE",
        "BULLISH_BREAKOUT",
        "BEARISH_BREAKOUT",
        "UNKNOWN",
    }
    assert result["range_width_20m"] is not None
    assert 0 <= result["bullish_structure_score"] <= 1
    assert 0 <= result["bearish_structure_score"] <= 1
