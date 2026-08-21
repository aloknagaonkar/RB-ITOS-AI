from datetime import datetime, timedelta

import pandas as pd

from red_bar_lab.services.red_bar_v2_current_session import (
    _live_market_snapshot_fields,
)


def _candles(start: datetime, count: int, base: float, volume: float = 1000.0):
    rows = []
    for index in range(count):
        close = base + index
        rows.append({
            "timestamp": start + timedelta(minutes=index),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume + index,
        })
    return pd.DataFrame(rows)


def test_live_market_snapshot_populates_before_any_replay_event():
    start = datetime(2026, 8, 21, 9, 15)
    index = _candles(start, 20, 24000.0)
    futures = _candles(start, 20, 24020.0)

    fields = _live_market_snapshot_fields(
        index_candles=index,
        futures_candles=futures,
    )

    assert fields["index_close"] == 24019.0
    assert fields["index_rsi"] is not None
    assert fields["futures_close"] == 24039.0
    assert fields["futures_vwap"] is not None
    assert fields["index_timestamp"].startswith("2026-08-21T09:34:00")
    assert fields["futures_timestamp"].startswith("2026-08-21T09:34:00")


def test_live_market_snapshot_recovers_reference_high_low_and_midpoint():
    start = datetime(2026, 8, 21, 9, 15)
    index = _candles(start, 20, 24000.0)
    futures = _candles(start, 20, 24020.0)
    reference_time = start + timedelta(minutes=6)

    fields = _live_market_snapshot_fields(
        index_candles=index,
        futures_candles=futures,
        reference_timestamp=reference_time,
    )

    assert fields["reference_high"] == 24007.0
    assert fields["reference_low"] == 24005.0
    assert fields["reference_midpoint"] == 24006.0
    assert fields["reference_timestamp"].startswith("2026-08-21T09:21:00")
