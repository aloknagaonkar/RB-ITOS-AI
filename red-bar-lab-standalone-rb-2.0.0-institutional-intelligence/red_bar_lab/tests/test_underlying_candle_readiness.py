from datetime import datetime

from red_bar_lab.execution.underlying_candle_readiness import (
    CANDLE_CURRENT_INCOMPLETE,
    CANDLE_INVALID_TIMESTAMP,
    CANDLE_MARKET_CLOSED,
    CANDLE_MISSING,
    CANDLE_READY,
    CANDLE_STALE,
    CANDLE_TIMESTAMP_MISMATCH,
    assess_underlying_candle_freshness,
)


def _now(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_ready_completed_candle():
    result = assess_underlying_candle_freshness(
        [["2026-08-20T14:29:00+05:30", 1, 2, 0, 1]],
        now=_now("2026-08-20T14:30:20+05:30"),
    )

    assert result.status == CANDLE_READY
    assert result.ready is True
    assert result.latest_timestamp == "2026-08-20T14:29:00+05:30"
    assert result.expected_completed_timestamp == "2026-08-20T14:29:00+05:30"
    assert result.candle_age_seconds == 80.0


def test_current_incomplete_candle_is_ignored_when_completed_exists():
    result = assess_underlying_candle_freshness(
        [
            {"timestamp": "2026-08-20T14:29:00+05:30"},
            {"timestamp": "2026-08-20T14:30:00+05:30"},
        ],
        now=_now("2026-08-20T14:30:20+05:30"),
    )

    assert result.status == CANDLE_READY
    assert "ignored" in result.reason
    assert result.latest_timestamp == "2026-08-20T14:29:00+05:30"


def test_only_current_incomplete_candle_is_not_ready():
    result = assess_underlying_candle_freshness(
        [{"timestamp": "2026-08-20T14:30:00+05:30"}],
        now=_now("2026-08-20T14:30:20+05:30"),
    )

    assert result.status == CANDLE_CURRENT_INCOMPLETE
    assert result.ready is False


def test_stale_completed_candle():
    result = assess_underlying_candle_freshness(
        [{"timestamp": "2026-08-20T14:25:00+05:30"}],
        now=_now("2026-08-20T14:30:20+05:30"),
        stale_after_seconds=120,
    )

    assert result.status == CANDLE_STALE
    assert "240 seconds" in result.reason


def test_empty_collection_during_market_hours():
    result = assess_underlying_candle_freshness(
        [],
        now=_now("2026-08-20T14:30:20+05:30"),
    )

    assert result.status == CANDLE_MISSING


def test_invalid_timestamps():
    result = assess_underlying_candle_freshness(
        [{"timestamp": "not-a-date"}],
        now=_now("2026-08-20T14:30:20+05:30"),
    )

    assert result.status == CANDLE_INVALID_TIMESTAMP


def test_previous_trading_date_is_timestamp_mismatch():
    result = assess_underlying_candle_freshness(
        [{"timestamp": "2026-08-19T15:29:00+05:30"}],
        now=_now("2026-08-20T09:16:20+05:30"),
    )

    assert result.status == CANDLE_TIMESTAMP_MISMATCH
    assert "different trading date" in result.reason


def test_market_closed_is_not_reported_as_stale():
    result = assess_underlying_candle_freshness(
        [{"timestamp": "2026-08-20T15:29:00+05:30"}],
        now=_now("2026-08-20T19:24:00+05:30"),
    )

    assert result.status == CANDLE_MARKET_CLOSED
    assert result.candle_age_seconds is None


def test_epoch_milliseconds_are_supported():
    timestamp = int(_now("2026-08-20T14:29:00+05:30").timestamp() * 1000)
    result = assess_underlying_candle_freshness(
        [[timestamp, 1, 2, 0, 1]],
        now=_now("2026-08-20T14:30:20+05:30"),
    )

    assert result.status == CANDLE_READY


def test_interval_alignment_for_five_minute_candles():
    result = assess_underlying_candle_freshness(
        [{"timestamp": "2026-08-20T14:25:00+05:30"}],
        now=_now("2026-08-20T14:30:20+05:30"),
        interval_minutes=5,
        stale_after_seconds=300,
    )

    assert result.status == CANDLE_READY
    assert result.expected_completed_timestamp == "2026-08-20T14:25:00+05:30"
