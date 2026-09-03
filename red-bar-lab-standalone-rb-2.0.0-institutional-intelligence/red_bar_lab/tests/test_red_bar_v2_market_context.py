from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from red_bar_lab.intelligence.market_context import (
    MarketContextError,
    add_market_indicators,
    aggregate_completed_5m,
    build_latest_snapshot,
    completed_candles,
    session_vwap,
    wilder_rsi,
)


IST = timezone(timedelta(hours=5, minutes=30))


def _candles(
    count: int,
    *,
    start: datetime = datetime(2026, 8, 20, 9, 15, tzinfo=IST),
    step: float = 1.0,
    volume: float = 100.0,
) -> pd.DataFrame:
    timestamps = pd.date_range(start=start, periods=count, freq="1min")
    closes = [100.0 + (position * step) for position in range(count)]
    return pd.DataFrame(
        {
            "open": [value - 0.25 for value in closes],
            "high": [value + 0.50 for value in closes],
            "low": [value - 0.50 for value in closes],
            "close": closes,
            "volume": [volume] * count,
        },
        index=timestamps,
    )


def test_wilder_rsi_reports_strong_rising_momentum() -> None:
    frame = _candles(20)
    result = wilder_rsi(frame["close"], period=14)

    assert result.iloc[:14].isna().all()
    assert result.iloc[-1] == pytest.approx(100.0)


def test_session_vwap_uses_typical_price_and_resets_each_day() -> None:
    first = _candles(2)
    second_start = datetime(2026, 8, 21, 9, 15, tzinfo=IST)
    second = _candles(1, start=second_start, step=0.0)
    second.loc[:, ["open", "high", "low", "close"]] = [199.75, 200.5, 199.5, 200.0]
    frame = pd.concat([first, second])

    vwap = session_vwap(frame)

    expected_first = (100.5 + 99.5 + 100.0) / 3.0
    expected_second_day = (200.5 + 199.5 + 200.0) / 3.0
    assert vwap.iloc[0] == pytest.approx(expected_first)
    assert vwap.iloc[-1] == pytest.approx(expected_second_day)


def test_completed_candles_excludes_still_forming_one_minute_bar() -> None:
    frame = _candles(3)
    evaluated_at = datetime(2026, 8, 20, 9, 17, 30, tzinfo=IST)

    completed = completed_candles(frame, evaluation_time=evaluated_at)

    assert list(completed.index.minute) == [15, 16]


def test_aggregate_completed_5m_discards_partial_group() -> None:
    frame = _candles(11)

    aggregated = aggregate_completed_5m(frame)

    assert list(aggregated.index.minute) == [15, 20]
    assert aggregated.iloc[0]["open"] == pytest.approx(frame.iloc[0]["open"])
    assert aggregated.iloc[0]["close"] == pytest.approx(frame.iloc[4]["close"])
    assert aggregated.iloc[0]["volume"] == pytest.approx(500.0)


def test_latest_one_minute_snapshot_reports_bullish_rsi_state() -> None:
    frame = _candles(20)
    expected = frame.index[-1]

    snapshot = build_latest_snapshot(
        frame,
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="1M",
        evaluation_time=expected + pd.Timedelta(minutes=1),
        expected_timestamp=expected,
    )

    assert snapshot is not None
    assert snapshot.data_quality == "VALID"
    assert snapshot.fresh is True
    assert snapshot.rsi_value == pytest.approx(100.0)
    assert snapshot.price_vs_vwap == "ABOVE"
    assert snapshot.rsi_state == "BULLISH"
    assert snapshot.to_storage_payload()["candle_timestamp"] == expected.isoformat()


def test_latest_five_minute_snapshot_uses_only_complete_groups() -> None:
    frame = _candles(76)
    evaluated_at = frame.index[-1] + pd.Timedelta(minutes=1)

    snapshot = build_latest_snapshot(
        frame,
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="5M",
        evaluation_time=evaluated_at,
        expected_timestamp=datetime(2026, 8, 20, 10, 25, tzinfo=IST),
    )

    assert snapshot is not None
    assert snapshot.candle_timestamp == datetime(2026, 8, 20, 10, 25, tzinfo=IST)
    assert snapshot.timeframe == "5M"
    assert snapshot.candle_volume == pytest.approx(500.0)
    assert snapshot.data_quality == "VALID"


def test_stale_expected_timestamp_is_reported_through_freshness_only() -> None:
    """Staleness must not be smuggled into the RSI reading.

    The retired `bullish_context`/`bearish_context` pair was forced to False
    whenever the snapshot was stale, which made the pair unreadable: a False
    could mean "RSI disagrees" or "the data is old". `rsi_state` is now a
    statement about RSI and nothing else, and callers read `fresh` /
    `data_quality` to learn the snapshot is not usable.
    """
    frame = _candles(20)

    snapshot = build_latest_snapshot(
        frame,
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="1M",
        evaluation_time=frame.index[-1] + pd.Timedelta(minutes=1),
        expected_timestamp=frame.index[-2],
    )

    assert snapshot is not None
    assert snapshot.data_quality == "STALE_CONTEXT"
    assert snapshot.fresh is False
    assert snapshot.rsi_state == "BULLISH"


def test_insufficient_rsi_history_is_explicit() -> None:
    frame = _candles(10)

    snapshot = build_latest_snapshot(
        frame,
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="1M",
        evaluation_time=frame.index[-1] + pd.Timedelta(minutes=1),
    )

    assert snapshot is not None
    assert snapshot.rsi_value is None
    assert snapshot.data_quality == "INSUFFICIENT_RSI_HISTORY"
    assert snapshot.rsi_state is None, "no reading means no classification"


def test_missing_volume_is_rejected() -> None:
    frame = _candles(20).drop(columns=["volume"])

    with pytest.raises(MarketContextError, match="volume"):
        add_market_indicators(frame)
