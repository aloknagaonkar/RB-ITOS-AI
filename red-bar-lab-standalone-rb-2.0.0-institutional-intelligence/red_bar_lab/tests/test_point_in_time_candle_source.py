from datetime import date

from red_bar_lab.services.point_in_time_candle_source import (
    select_point_in_time_completed_candles,
)


def _reader(rows):
    def read(**kwargs):
        return rows

    return read


def test_current_session_prefers_live_persisted_candles():
    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="2026-08-21T10:25:00+05:30",
        live_reader=_reader(
            [
                {"timestamp": "2026-08-21T10:15:00+05:30", "close": 25000.0},
                {"timestamp": "2026-08-21T10:20:00+05:30", "close": 25005.0},
            ]
        ),
        historical_reader=_reader(
            [{"timestamp": "2026-08-21T10:10:00+05:30", "close": 24990.0}]
        ),
        current_date=date(2026, 8, 21),
    )

    assert result.status == "READY"
    assert result.selected_source == "LIVE_PERSISTED"
    assert result.row_count == 2
    assert result.fallback_used is False
    assert result.no_lookahead_passed is True


def test_current_session_uses_explicit_historical_fallback():
    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="2026-08-21T10:25:00+05:30",
        live_reader=_reader([]),
        historical_reader=_reader(
            [{"timestamp": "2026-08-21T10:20:00+05:30", "close": 25005.0}]
        ),
        current_date=date(2026, 8, 21),
    )

    assert result.status == "READY"
    assert result.selected_source == "HISTORICAL_REPOSITORY"
    assert result.fallback_used is True
    assert result.latest_candle_timestamp.endswith("10:20:00+05:30")


def test_historical_session_uses_historical_source_directly():
    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="2026-08-20T10:25:00+05:30",
        live_reader=_reader(
            [{"timestamp": "2026-08-20T10:20:00+05:30", "close": 25005.0}]
        ),
        historical_reader=_reader(
            [{"timestamp": "2026-08-20T10:15:00+05:30", "close": 24995.0}]
        ),
        current_date=date(2026, 8, 21),
    )

    assert result.status == "READY"
    assert result.selected_source == "HISTORICAL_REPOSITORY"
    assert result.fallback_used is False


def test_future_candles_are_excluded_and_report_no_lookahead_failure():
    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="2026-08-21T10:25:00+05:30",
        live_reader=_reader(
            [
                {"timestamp": "2026-08-21T10:20:00+05:30", "close": 25005.0},
                {"timestamp": "2026-08-21T10:30:00+05:30", "close": 25020.0},
            ]
        ),
        historical_reader=None,
        current_date=date(2026, 8, 21),
    )

    assert result.status == "READY"
    assert result.row_count == 1
    assert result.no_lookahead_passed is False
    assert all(row["timestamp"] <= "2026-08-21T10:25:00+05:30" for row in result.rows)


def test_only_future_candles_return_explicit_missing_reason():
    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="2026-08-21T10:25:00+05:30",
        live_reader=_reader(
            [{"timestamp": "2026-08-21T10:30:00+05:30", "close": 25020.0}]
        ),
        historical_reader=None,
        allow_historical_fallback=False,
        current_date=date(2026, 8, 21),
    )

    assert result.status == "MISSING"
    assert result.reason_code == "ONLY_FUTURE_CANDLES_AVAILABLE"
    assert result.no_lookahead_passed is False


def test_reader_failure_is_explicit_and_does_not_raise():
    def broken(**kwargs):
        raise RuntimeError("database unavailable")

    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="2026-08-20T10:25:00+05:30",
        historical_reader=broken,
        current_date=date(2026, 8, 21),
    )

    assert result.status == "FAILED"
    assert result.reason_code == "HISTORICAL_REPOSITORY_READ_FAILED"
    assert "database unavailable" in result.reason


def test_invalid_cutoff_returns_failed_result():
    result = select_point_in_time_completed_candles(
        instrument_key="NIFTY",
        timeframe="5m",
        cutoff_timestamp="not-a-time",
    )

    assert result.status == "FAILED"
    assert result.reason_code == "CUTOFF_TIMESTAMP_INVALID"
