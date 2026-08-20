from datetime import datetime

from red_bar_lab.execution.underlying_candle_monitoring import (
    ALIGNMENT_AFTER_HOURS_EXPECTED,
    ALIGNMENT_CANDLES_DEGRADED,
    ALIGNMENT_CONSISTENT,
    ALIGNMENT_SNAPSHOT_STALE_CANDLES_READY,
    assess_monitor_underlying_candles,
)


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


def _now(text):
    return datetime.fromisoformat(text)


def test_fresh_candles_are_consistent_with_ready_bridge():
    provider = _Provider(
        [
            ["2026-08-20T10:28:00+05:30", 1, 2, 1, 2, 0, 0],
            ["2026-08-20T10:29:00+05:30", 1, 2, 1, 2, 0, 0],
            ["2026-08-20T10:30:00+05:30", 1, 2, 1, 2, 0, 0],
        ]
    )

    result = assess_monitor_underlying_candles(
        provider,
        instrument_key="NSE_INDEX|Nifty 50",
        now=_now("2026-08-20T10:30:20+05:30"),
        bridge_reason="V2_PAPER_SIGNAL_READY",
    )

    assert result.readiness.status == "READY"
    assert result.bridge_alignment == ALIGNMENT_CONSISTENT
    assert result.fetch_error is None
    assert result.volume_authority.status == "NOT_APPLICABLE"
    assert result.volume_authority.source == "INDEX_PRICE_ONLY"
    assert result.volume_authority.volume is None
    assert provider.calls == [("NSE_INDEX|Nifty 50", 1)]


def test_stale_snapshot_with_fresh_candles_is_explicitly_distinguished():
    provider = _Provider(
        [
            {"timestamp": "2026-08-20T10:29:00+05:30", "volume": 0},
            {"timestamp": "2026-08-20T10:30:00+05:30", "volume": 0},
        ]
    )

    result = assess_monitor_underlying_candles(
        provider,
        instrument_key="NSE_INDEX|Nifty 50",
        now=_now("2026-08-20T10:30:20+05:30"),
        bridge_reason="V2_SNAPSHOT_STALE",
    )

    assert result.readiness.status == "READY"
    assert result.bridge_alignment == ALIGNMENT_SNAPSHOT_STALE_CANDLES_READY
    assert result.volume_authority.status == "NOT_APPLICABLE"


def test_after_hours_snapshot_staleness_is_marked_expected():
    provider = _Provider(
        [["2026-08-20T15:29:00+05:30", 1, 2, 1, 2, 0, 0]]
    )

    result = assess_monitor_underlying_candles(
        provider,
        instrument_key="NSE_INDEX|Nifty 50",
        now=_now("2026-08-20T19:24:00+05:30"),
        bridge_reason="V2_SNAPSHOT_STALE",
    )

    assert result.readiness.status == "MARKET_CLOSED"
    assert result.bridge_alignment == ALIGNMENT_AFTER_HOURS_EXPECTED
    assert result.volume_authority.status == "NOT_APPLICABLE"


def test_provider_failure_is_degraded_but_non_throwing():
    provider = _Provider(error=RuntimeError("temporary outage"))

    result = assess_monitor_underlying_candles(
        provider,
        instrument_key="NSE_INDEX|Nifty 50",
        now=_now("2026-08-20T10:30:20+05:30"),
        bridge_reason="V2_SNAPSHOT_STALE",
    )

    assert result.readiness.status == "MISSING"
    assert result.bridge_alignment == ALIGNMENT_CANDLES_DEGRADED
    assert result.volume_authority.status == "NOT_APPLICABLE"
    assert result.fetch_error == "RuntimeError:temporary outage"


def test_traded_futures_volume_remains_applicable():
    provider = _Provider(
        [
            ["2026-08-20T10:29:00+05:30", 1, 2, 1, 2, 125000, 500000],
            ["2026-08-20T10:30:00+05:30", 1, 2, 1, 2, 130000, 510000],
        ]
    )

    result = assess_monitor_underlying_candles(
        provider,
        instrument_key="NSE_FO|58072",
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.readiness.status == "READY"
    assert result.volume_authority.status == "APPLICABLE"
    assert result.volume_authority.source == "TRADED_INSTRUMENT"
    assert result.volume_authority.volume == 130000.0


def test_mapping_candle_volume_is_preserved_for_traded_instrument():
    provider = _Provider(
        [
            {
                "timestamp": "2026-08-20T10:29:00+05:30",
                "volume": "87500",
            },
            {
                "timestamp": "2026-08-20T10:30:00+05:30",
                "volume": "90000",
            },
        ]
    )

    result = assess_monitor_underlying_candles(
        provider,
        instrument_key="NSE_FO|58072",
        now=_now("2026-08-20T10:30:20+05:30"),
    )

    assert result.volume_authority.status == "APPLICABLE"
    assert result.volume_authority.volume == 90000.0
