import pandas as pd

from red_bar_lab.intelligence.red_bar_v2_session_health import (
    build_session_vwap_source_health,
)


IST = "Asia/Kolkata"


def _candles(periods: int, *, extra: int = 0, volume: float = 1000.0) -> pd.DataFrame:
    total = periods + extra
    timestamps = pd.date_range("2026-08-18 09:15", periods=total, freq="1min", tz=IST)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * total,
            "high": [101.0] * total,
            "low": [99.0] * total,
            "close": [100.0] * total,
            "volume": [volume] * total,
        }
    )


def test_session_health_reports_full_1m_and_completed_5m_alignment():
    health = build_session_vwap_source_health(
        _candles(375),
        _candles(375, extra=10),
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
    )

    assert health.status == "READY"
    assert health.reason == "FULL_SESSION_TIMESTAMP_ALIGNMENT"
    assert health.index_rows == 375
    assert health.futures_rows == 385
    assert health.aligned_rows == 375
    assert health.alignment_coverage_pct == 100.0
    assert health.positive_volume_rows == 385
    assert health.completed_5m_index_rows == 75
    assert health.completed_5m_futures_rows == 77
    assert health.completed_5m_aligned_rows == 75
    assert health.completed_5m_alignment_coverage_pct == 100.0
    assert health.last_aligned_timestamp == pd.Timestamp(
        "2026-08-18 15:29", tz=IST
    ).to_pydatetime()
    assert health.completed_5m_last_aligned_timestamp == pd.Timestamp(
        "2026-08-18 15:25", tz=IST
    ).to_pydatetime()


def test_session_health_blocks_incomplete_index_alignment():
    futures = _candles(374)
    health = build_session_vwap_source_health(
        _candles(375),
        futures,
        instrument_key="NIFTY",
        vwap_instrument_key="NIFTY-FUT",
    )

    assert health.status == "BLOCKED"
    assert health.reason == "INCOMPLETE_1M_TIMESTAMP_ALIGNMENT"
    assert health.aligned_rows == 374
