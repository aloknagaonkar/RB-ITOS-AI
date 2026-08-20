from red_bar_lab.execution.paper_monitor import (
    _candle_diagnostic_log_values,
)
from red_bar_lab.execution.underlying_candle_monitoring import (
    UnderlyingCandleMonitorDiagnostic,
)
from red_bar_lab.execution.underlying_candle_readiness import (
    UnderlyingCandleReadiness,
)
from red_bar_lab.execution.underlying_volume_authority import (
    UnderlyingVolumeAuthority,
)


def test_candle_diagnostic_log_values_include_freshness_context():
    diagnostic = UnderlyingCandleMonitorDiagnostic(
        readiness=UnderlyingCandleReadiness(
            status="READY",
            reason="Latest completed candle is aligned.",
            latest_timestamp="2026-08-20T14:29:00+05:30",
            candle_age_seconds=75.25,
            expected_completed_timestamp="2026-08-20T14:29:00+05:30",
        ),
        bridge_alignment="SNAPSHOT_STALE_CANDLES_READY",
        volume_authority=UnderlyingVolumeAuthority(
            status="NOT_APPLICABLE",
            reason="Cash index volume is not a traded-volume authority.",
            volume=None,
            source="INDEX_PRICE_ONLY",
        ),
    )

    assert _candle_diagnostic_log_values(diagnostic) == (
        "READY",
        "Latest completed candle is aligned.",
        "75.2",
        "2026-08-20T14:29:00+05:30",
        "2026-08-20T14:29:00+05:30",
        "SNAPSHOT_STALE_CANDLES_READY",
        "NONE",
        "NOT_APPLICABLE",
        "Cash index volume is not a traded-volume authority.",
        "INDEX_PRICE_ONLY",
        "NA",
    )


def test_candle_diagnostic_log_values_are_stable_when_data_missing():
    diagnostic = UnderlyingCandleMonitorDiagnostic(
        readiness=UnderlyingCandleReadiness(
            status="MISSING",
            reason="Underlying candle provider request failed.",
        ),
        bridge_alignment="CANDLES_DEGRADED",
        volume_authority=UnderlyingVolumeAuthority(
            status="NOT_APPLICABLE",
            reason="Cash index volume is not a traded-volume authority.",
            volume=None,
            source="INDEX_PRICE_ONLY",
        ),
        fetch_error="RuntimeError:provider unavailable",
    )

    assert _candle_diagnostic_log_values(diagnostic) == (
        "MISSING",
        "Underlying candle provider request failed.",
        "NA",
        "NA",
        "NA",
        "CANDLES_DEGRADED",
        "RuntimeError:provider unavailable",
        "NOT_APPLICABLE",
        "Cash index volume is not a traded-volume authority.",
        "INDEX_PRICE_ONLY",
        "NA",
    )


def test_candle_diagnostic_log_values_preserve_traded_volume():
    diagnostic = UnderlyingCandleMonitorDiagnostic(
        readiness=UnderlyingCandleReadiness(
            status="READY",
            reason="Latest completed candle is aligned.",
        ),
        bridge_alignment="CONSISTENT",
        volume_authority=UnderlyingVolumeAuthority(
            status="APPLICABLE",
            reason="Traded-instrument volume is available.",
            volume=125000.0,
            source="TRADED_INSTRUMENT",
        ),
    )

    values = _candle_diagnostic_log_values(diagnostic)

    assert values[7:] == (
        "APPLICABLE",
        "Traded-instrument volume is available.",
        "TRADED_INSTRUMENT",
        "125000.0",
    )
