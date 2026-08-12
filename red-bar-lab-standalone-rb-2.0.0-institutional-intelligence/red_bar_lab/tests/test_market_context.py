import pandas as pd

from red_bar_lab.context.market_context import (
    build_market_context_snapshot,
)


def _candles(day="2026-08-07", rows=120, base=100.0):
    ts = pd.date_range(
        f"{day} 09:15",
        periods=rows,
        freq="1min",
        tz="Asia/Kolkata",
    )
    data = []
    price = base
    for stamp in ts:
        close = price + 0.1
        data.append({
            "timestamp": stamp,
            "open": price,
            "high": close + 0.2,
            "low": price - 0.2,
            "close": close,
            "volume": 0,
        })
        price = close
    return pd.DataFrame(data)


def test_context_uses_only_data_at_or_before_entry():
    current = _candles(rows=120, base=100.0)
    previous = _candles(day="2026-08-06", rows=120, base=95.0)

    signal = {
        "signal_id": "RB-CTX",
        "trading_date": "2026-08-07",
        "confirmation_timestamp": "2026-08-07T10:00:00+05:30",
        "underlying_entry": 104.6,
    }

    result = build_market_context_snapshot(
        signal=signal,
        instrument_key="NIFTY",
        current_day=current,
        previous_day=previous,
    )

    assert result["minutes_from_open"] == 45
    assert result["opening_range_15_high"] is not None
    assert result["session_high_so_far"] < 106.0
    assert 0 <= result["session_range_position"] <= 1


def test_opening_range_is_not_available_before_0930():
    current = _candles(rows=20)
    signal = {
        "signal_id": "RB-EARLY",
        "trading_date": "2026-08-07",
        "confirmation_timestamp": "2026-08-07T09:25:00+05:30",
        "underlying_entry": 101.1,
    }

    result = build_market_context_snapshot(
        signal=signal,
        instrument_key="NIFTY",
        current_day=current,
        previous_day=None,
    )

    assert result["opening_range_15_high"] is None
    assert result["opening_range_15_position"] == "UNAVAILABLE"
