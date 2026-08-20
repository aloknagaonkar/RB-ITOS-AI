from datetime import datetime

from red_bar_lab.services.nifty_futures_market_data import (
    assess_nifty_futures_market_data,
    futures_market_log_values,
)
from red_bar_lab.services.nifty_futures_monitoring import NiftyFuturesMonitorResult


class _Provider:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def intraday_candles(self, instrument_key, interval_minutes=1):
        self.calls.append((instrument_key, interval_minutes))
        if self.error:
            raise self.error
        return self.payload


def _contract(status="READY"):
    return NiftyFuturesMonitorResult(
        status=status,
        reason="resolved" if status == "READY" else "missing",
        instrument_key="NSE_FO|58072" if status == "READY" else None,
        trading_symbol="NIFTY FUT 25 AUG 26" if status == "READY" else None,
        expiry="2026-08-25" if status == "READY" else None,
        error=None if status == "READY" else "not found",
    )


def _now(text):
    return datetime.fromisoformat(text)


def test_collects_latest_completed_futures_close_volume_and_oi():
    provider = _Provider(
        [
            ["2026-08-20T10:29:00+05:30", 25000, 25010, 24990, 25005, 1100, 50100],
            ["2026-08-20T10:30:00+05:30", 25005, 25020, 25000, 25015, 1250, 50450],
        ]
    )

    result = assess_nifty_futures_market_data(
        provider,
        contract=_contract(),
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.status == "READY"
    assert result.instrument_key == "NSE_FO|58072"
    assert result.candle_readiness.status == "READY"
    assert result.volume_authority.status == "APPLICABLE"
    assert result.latest_close == 25005.0
    assert result.latest_volume == 1100.0
    assert result.latest_oi == 50100.0
    assert result.latest_timestamp == "2026-08-20T10:29:00+05:30"
    assert result.candle_count == 2
    assert provider.calls == [("NSE_FO|58072", 1)]


def test_mapping_candles_and_dataframe_like_records_are_supported():
    provider = _Provider(
        [
            {
                "timestamp": "2026-08-20T10:29:00+05:30",
                "close": 25005,
                "volume": 1100,
                "oi": 50100,
            }
        ]
    )

    result = assess_nifty_futures_market_data(
        provider,
        contract=_contract(),
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.latest_close == 25005.0
    assert result.latest_volume == 1100.0
    assert result.latest_oi == 50100.0


def test_only_current_incomplete_candle_does_not_publish_telemetry():
    provider = _Provider(
        [["2026-08-20T10:30:00+05:30", 1, 2, 1, 2, 100, 200]]
    )

    result = assess_nifty_futures_market_data(
        provider,
        contract=_contract(),
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.status == "MISSING"
    assert result.candle_readiness.status == "CURRENT_CANDLE_INCOMPLETE"
    assert result.latest_volume is None
    assert result.latest_oi is None


def test_unavailable_contract_does_not_call_provider():
    provider = _Provider([])
    result = assess_nifty_futures_market_data(
        provider,
        contract=_contract("UNAVAILABLE"),
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.status == "UNAVAILABLE"
    assert provider.calls == []
    assert result.error == "not found"


def test_provider_failure_is_non_throwing():
    result = assess_nifty_futures_market_data(
        _Provider(error=RuntimeError("temporary outage")),
        contract=_contract(),
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.status == "ERROR"
    assert result.error == "RuntimeError:temporary outage"


def test_log_values_are_stable():
    provider = _Provider(
        [["2026-08-20T10:29:00+05:30", 1, 2, 1, 2, 100, 200]]
    )
    result = assess_nifty_futures_market_data(
        provider,
        contract=_contract(),
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert futures_market_log_values(result) == (
        "READY",
        "Latest completed NIFTY futures candle, volume and OI were collected.",
        "READY",
        "APPLICABLE",
        "2.00",
        "100.0",
        "200.0",
        "2026-08-20T10:29:00+05:30",
        "1",
        "NONE",
    )
