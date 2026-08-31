import pandas as pd

from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    build_red_bar_v2_futures_snapshot,
)


IST = "Asia/Kolkata"


def _frame(closes, volumes):
    timestamps = pd.date_range(
        "2026-08-18 09:15",
        periods=len(closes),
        freq="1min",
        tz=IST,
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": volumes,
        }
    )


def test_split_source_uses_index_close_and_futures_vwap_price():
    index = _frame([100.0 + i for i in range(20)], [0.0] * 20)
    futures = _frame([200.0 + i for i in range(20)], [1000.0] * 20)
    evaluation = pd.Timestamp("2026-08-18 09:35", tz=IST)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=evaluation,
        expected_timestamp=pd.Timestamp("2026-08-18 09:34", tz=IST),
    )

    assert snapshot is not None
    assert snapshot.candle_close == 119.0
    assert snapshot.vwap_comparison_price == 219.0
    assert snapshot.vwap_source_instrument_key == "NSE_FO|58072"
    assert snapshot.vwap_value is not None
    assert snapshot.price_vs_vwap == "ABOVE"
    assert health.status == "READY"
    assert health.aligned_rows == 20
    assert health.alignment_coverage_pct == 100.0


def test_zero_futures_volume_fails_closed():
    index = _frame([100.0 + i for i in range(20)], [0.0] * 20)
    futures = _frame([200.0 + i for i in range(20)], [0.0] * 20)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp("2026-08-18 09:35", tz=IST),
        expected_timestamp=pd.Timestamp("2026-08-18 09:34", tz=IST),
    )

    assert snapshot is None
    assert health.status == "BLOCKED"
    assert health.reason == "FUTURES_VOLUME_UNAVAILABLE"


def test_futures_one_candle_behind_aligns_to_common_candle():
    index = _frame([100.0 + i for i in range(20)], [0.0] * 20)
    futures = _frame([200.0 + i for i in range(19)], [1000.0] * 19)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp("2026-08-18 09:35", tz=IST),
        expected_timestamp=pd.Timestamp("2026-08-18 09:34", tz=IST),
    )

    assert snapshot is not None
    assert snapshot.candle_close == 118.0
    assert snapshot.vwap_comparison_price == 218.0
    assert health.status == "READY"
    assert health.reason == "FULL_TIMESTAMP_ALIGNMENT"


def test_index_one_candle_behind_futures_aligns_to_common_candle():
    index = _frame([100.0 + i for i in range(19)], [0.0] * 19)
    futures = _frame([200.0 + i for i in range(20)], [1000.0] * 20)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp("2026-08-18 09:34", tz=IST),
        expected_timestamp=pd.Timestamp("2026-08-18 09:33", tz=IST),
    )

    assert snapshot is not None
    assert snapshot.candle_close == 118.0
    assert snapshot.vwap_comparison_price == 218.0
    assert health.status == "READY"


def test_futures_two_candles_behind_still_fails_closed():
    index = _frame([100.0 + i for i in range(20)], [0.0] * 20)
    futures = _frame([200.0 + i for i in range(18)], [1000.0] * 18)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp("2026-08-18 09:35", tz=IST),
        expected_timestamp=pd.Timestamp("2026-08-18 09:34", tz=IST),
    )

    assert snapshot is None
    assert health.reason == "FUTURES_TIMESTAMP_MISMATCH"


def test_missing_expected_index_candle_is_stale_even_with_skew_tolerance():
    index = _frame([100.0 + i for i in range(19)], [0.0] * 19)
    futures = _frame([200.0 + i for i in range(20)], [1000.0] * 20)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp("2026-08-18 09:35", tz=IST),
        expected_timestamp=pd.Timestamp("2026-08-18 09:34", tz=IST),
    )

    assert snapshot is None
    assert health.reason == "STALE_CONTEXT"
