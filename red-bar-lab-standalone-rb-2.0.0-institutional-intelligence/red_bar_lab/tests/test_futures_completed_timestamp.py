from datetime import datetime

from red_bar_lab.services.nifty_futures_market_data import (
    assess_nifty_futures_market_data,
)
from red_bar_lab.services.nifty_futures_monitoring import NiftyFuturesMonitorResult


class Provider:
    def intraday_candles(self, instrument_key, interval_minutes=1):
        return [
            {
                "timestamp": "2026-08-21T10:18:00+05:30",
                "open": 25000,
                "high": 25005,
                "low": 24998,
                "close": 25003,
                "volume": 100,
                "oi": 1000,
            },
            {
                "timestamp": "2026-08-21T10:19:00+05:30",
                "open": 25003,
                "high": 25010,
                "low": 25001,
                "close": 25008,
                "volume": 120,
                "oi": 1010,
            },
        ]


def test_futures_completed_candle_exposes_open_and_close_timestamp():
    result = assess_nifty_futures_market_data(
        Provider(),
        contract=NiftyFuturesMonitorResult(
            status="READY",
            reason="ready",
            instrument_key="NSE_FO|NIFTY",
            trading_symbol="NIFTY FUT",
        ),
        now=datetime.fromisoformat("2026-08-21T10:21:00+05:30"),
        interval_minutes=1,
    )

    assert result.status == "READY"
    assert result.bar_open_timestamp == "2026-08-21T10:19:00+05:30"
    assert result.bar_close_timestamp == "2026-08-21T10:20:00+05:30"
    assert result.latest_timestamp == result.bar_close_timestamp
    assert result.futures_vwap_timestamp == result.bar_close_timestamp
