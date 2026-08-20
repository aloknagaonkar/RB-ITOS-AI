from red_bar_lab.execution.paper_monitor import (
    _candle_diagnostic_log_values,
)
from red_bar_lab.execution.underlying_candle_monitoring import (
    UnderlyingCandleMonitorDiagnostic,
)
from red_bar_lab.execution.underlying_candle_readiness import (
    UnderlyingCandleReadiness,
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
    )

    assert _candle_diagnostic_log_values(diagnostic) == (
        "READY",
        "Latest completed candle is aligned.",
        "75.2",
        "2026-08-20T14:29:00+05:30",
        "2026-08-20T14:29:00+05:30",
        "SNAPSHOT_STALE_CANDLES_READY",
        "NONE",
    )


def test_candle_diagnostic_log_values_are_stable_when_data_missing():
    diagnostic = UnderlyingCandleMonitorDiagnostic(
        readiness=UnderlyingCandleReadiness(
            status="MISSING",
            reason="Underlying candle provider request failed.",
        ),
        bridge_alignment="CANDLES_DEGRADED",
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
    )
