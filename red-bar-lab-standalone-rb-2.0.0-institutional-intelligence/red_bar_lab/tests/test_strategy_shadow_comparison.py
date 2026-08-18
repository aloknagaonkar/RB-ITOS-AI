from __future__ import annotations

import json
from pathlib import Path

from red_bar_lab.execution.strategy_shadow_comparison import (
    StrategyShadowComparisonService,
    compare_strategy_records,
)


def directional_record(direction: str = "BEARISH", trigger: float = 24165.45):
    return {
        "status": "READY",
        "early_bundle_preview": {
            "primary_signal_id": "SIG-1",
            "direction": direction,
            "primary_setup_type": "EARLY_1M_BEARISH_STRUCTURE_BREAK",
            "detected_at": "2026-08-18T15:29:00+05:30",
            "fresh_until": "2026-08-18T15:33:00+05:30",
            "trigger_level": trigger,
            "invalidation_level": 24202.85,
        },
    }


def test_comparison_matches_normalized_strategy_records():
    result = compare_strategy_records(
        "directional_regime",
        directional_record(),
        {
            "detection_status": "READY",
            "early_bundle_preview": directional_record()["early_bundle_preview"],
        },
    )

    assert result["comparison_status"] == "MATCH"
    assert result["match"] is True
    assert result["mismatch_fields"] == []


def test_comparison_reports_specific_mismatch_fields():
    result = compare_strategy_records(
        "directional_regime",
        directional_record(),
        directional_record(direction="BULLISH", trigger=24170.0),
    )

    assert result["comparison_status"] == "MISMATCH"
    assert result["match"] is False
    assert result["mismatch_fields"] == ["direction", "trigger_level"]


def test_missing_legacy_record_is_readiness_not_mismatch():
    result = compare_strategy_records(
        "rsi_reversal",
        None,
        {
            "latest_historical_signal": {
                "signal_id": "RSI-1",
                "direction": "BULLISH",
            }
        },
    )

    assert result["comparison_status"] == "LEGACY_NOT_READY"
    assert result["match"] is None


def test_service_writes_diagnostic_journal_and_atomic_status(tmp_path: Path):
    service = StrategyShadowComparisonService(
        runs_root=tmp_path,
        instrument_key="NSE_INDEX|Nifty 50",
        legacy_snapshot_loader=lambda: {
            "directional_regime": directional_record(),
        },
    )
    shadow = {
        "scan_identity": "NSE_INDEX|Nifty 50|1M|2026-08-18T15:29:00+05:30",
        "evaluated_at": "2026-08-18T15:30:00+05:30",
        "red_bar": {"status": "INPUT_UNAVAILABLE"},
        "directional_regime": directional_record(),
        "rsi_reversal": {"status": "NO_SIGNAL"},
    }

    payload = service.compare_and_record(shadow)

    assert payload["comparison_status"] == "MATCH"
    assert payload["comparable_strategy_count"] == 1
    assert payload["diagnostic_only"] is True
    assert payload["production_persistence"] is False
    assert payload["execution_allowed"] is False
    assert service.journal_path.exists()
    assert service.status_path.exists()
    status = json.loads(service.status_path.read_text(encoding="utf-8"))
    assert status["scan_identity"] == shadow["scan_identity"]
