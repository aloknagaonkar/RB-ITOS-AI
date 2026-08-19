from __future__ import annotations

import json
from pathlib import Path

from red_bar_lab.execution.strategy_shadow_comparison import (
    StrategyShadowComparisonService,
    compare_strategy_records,
)


def directional_record(
    direction: str = "BEARISH",
    trigger: float = 24165.45,
    *,
    signal_id: str = "SIG-1",
    setup_type: str = "EARLY_1M_BEARISH_STRUCTURE_BREAK",
    detected_at: str = "2026-08-18T15:29:00+05:30",
    fresh_until: str = "2026-08-18T15:33:00+05:30",
):
    return {
        "status": "READY",
        "early_bundle_preview": {
            "primary_signal_id": signal_id,
            "direction": direction,
            "primary_setup_type": setup_type,
            "detected_at": detected_at,
            "fresh_until": fresh_until,
            "trigger_level": trigger,
            "invalidation_level": 24202.85,
        },
    }


def red_bar_record():
    return {
        "status": "SIGNAL_AVAILABLE",
        "latest_attempt": {
            "signal_id": "RB-1",
            "direction": "BEARISH",
            "level_type": "NEXT_RED_CANDLE",
            "confirmation_timestamp": "2026-08-18T15:29:00+05:30",
            "level_value": 24165.45,
            "invalidation_level": 24202.85,
            "fresh_until": "2026-08-18T15:33:00+05:30",
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

    assert result["comparison_status"] == "EXACT_MATCH"
    assert result["comparison_class"] == "EXACT_IDENTITY"
    assert result["match"] is True
    assert result["mismatch_fields"] == []
    assert result["identity_difference_fields"] == []


def test_dri_stage_difference_is_equivalent_not_hard_mismatch():
    legacy = directional_record(
        signal_id="SIG-CONFIRMED",
        setup_type="BEARISH_STRUCTURE_BREAK",
        detected_at="2026-08-18T15:25:00+05:30",
        fresh_until="2026-08-18T15:40:00+05:30",
    )
    shadow = directional_record(
        signal_id="SIG-EARLY",
        setup_type="EARLY_1M_BEARISH_STRUCTURE_BREAK",
        detected_at="2026-08-18T15:29:00+05:30",
        fresh_until="2026-08-18T15:33:00+05:30",
    )

    result = compare_strategy_records("directional_regime", legacy, shadow)

    assert result["comparison_status"] == "EXPECTED_STAGE_DIFFERENCE"
    assert result["comparison_class"] == "LIFECYCLE_EQUIVALENT"
    assert result["match"] is True
    assert result["mismatch_fields"] == []
    assert result["identity_difference_fields"] == [
        "signal_id",
        "setup_type",
        "timestamp",
        "fresh_until",
    ]
    assert result["timestamp_delta_seconds"] == 240.0


def test_dri_same_geometry_outside_stage_window_is_directionally_equivalent():
    legacy = directional_record(
        signal_id="SIG-CONFIRMED",
        setup_type="BEARISH_STRUCTURE_BREAK",
        detected_at="2026-08-18T14:00:00+05:30",
        fresh_until="2026-08-18T14:15:00+05:30",
    )
    shadow = directional_record(
        signal_id="SIG-EARLY",
        detected_at="2026-08-18T15:29:00+05:30",
    )

    result = compare_strategy_records("directional_regime", legacy, shadow)

    assert result["comparison_status"] == "DIRECTIONAL_EQUIVALENT"
    assert result["comparison_class"] == "GEOMETRY_EQUIVALENT"
    assert result["match"] is True
    assert result["timestamp_delta_seconds"] == 5340.0


def test_comparison_reports_true_geometry_mismatch_fields():
    result = compare_strategy_records(
        "directional_regime",
        directional_record(),
        directional_record(direction="BULLISH", trigger=24170.0),
    )

    assert result["comparison_status"] == "TRUE_MISMATCH"
    assert result["comparison_class"] == "GEOMETRY_OR_DIRECTION_MISMATCH"
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
    assert result["comparison_class"] == "NOT_COMPARABLE"
    assert result["match"] is None


def test_service_compares_only_active_red_bar_strategy(tmp_path: Path):
    red_bar = red_bar_record()
    service = StrategyShadowComparisonService(
        runs_root=tmp_path,
        instrument_key="NSE_INDEX|Nifty 50",
        legacy_snapshot_loader=lambda: {
            "red_bar": red_bar,
            "directional_regime": directional_record(),
            "rsi_reversal": {
                "latest_historical_signal": {
                    "signal_id": "RSI-OLD",
                    "direction": "BULLISH",
                }
            },
        },
    )
    shadow = {
        "scan_identity": "NSE_INDEX|Nifty 50|1M|2026-08-18T15:29:00+05:30",
        "evaluated_at": "2026-08-18T15:30:00+05:30",
        "red_bar": red_bar,
        "directional_regime": directional_record(),
        "rsi_reversal": {
            "latest_historical_signal": {
                "signal_id": "RSI-OLD",
                "direction": "BULLISH",
            }
        },
    }

    payload = service.compare_and_record(shadow)

    assert payload["comparison_status"] == "MATCH"
    assert payload["comparable_strategy_count"] == 1
    assert payload["matching_strategy_count"] == 1
    assert payload["exact_match_strategy_count"] == 1
    assert payload["equivalent_strategy_count"] == 0
    assert payload["mismatch_strategy_count"] == 0
    assert [row["strategy"] for row in payload["comparisons"]] == ["red_bar"]
    assert payload["diagnostic_only"] is True
    assert payload["production_persistence"] is False
    assert payload["execution_allowed"] is False
    assert service.journal_path.exists()
    assert service.status_path.exists()
    status = json.loads(service.status_path.read_text(encoding="utf-8"))
    assert status["scan_identity"] == shadow["scan_identity"]
    assert status["comparison_version"] == "INDEPENDENT-STRATEGY-COMPARISON-V2"
