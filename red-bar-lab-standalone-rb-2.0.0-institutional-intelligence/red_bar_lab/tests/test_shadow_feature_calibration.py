from datetime import date

import pandas as pd

from red_bar_lab.services.shadow_feature_calibration import (
    ShadowFeatureCalibrationService,
    analyze_numeric_quantiles,
    build_calibration_rows,
    build_recommendations,
)


def _result_row(
    *,
    correct,
    confidence,
    adx,
    direction="BULLISH",
    regime="TRENDING_BULLISH",
):
    return {
        "direction_correct_30m": correct,
        "maximum_favorable_excursion": 20.0 if correct else 8.0,
        "maximum_adverse_excursion": 6.0 if correct else 18.0,
        "confidence": confidence,
        "adx": adx,
        "direction": direction,
        "regime": regime,
        "transition_type": "BULLISH_TRANSITION",
        "time_bucket": "MORNING_1030_1159",
        "breakout": False,
        "breakdown": False,
        "bullish_structure": True,
        "bearish_structure": False,
        "ema_fast_slope_atr": 0.2,
        "ema_slow_slope_atr": 0.1,
        "ema_fast_acceleration_atr": 0.05,
        "ema_spread_atr": 0.4,
        "adx_slope": 1.0,
        "dmi_gap": 10.0,
        "directional_dmi_gap": 10.0,
        "displacement_atr": 0.8,
        "directional_displacement_atr": 0.8,
        "range_atr": 1.1,
        "compression_ratio": 1.2,
        "volume_ratio": 1.0,
        "evidence": ["ADX_RISING", "PLUS_DI_DOMINANT"],
    }


def test_numeric_quantiles_identify_accuracy_lift():
    rows = []
    for index in range(40):
        rows.append(
            _result_row(
                correct=index >= 20,
                confidence=60 + index,
                adx=10 + index,
            )
        )
    segments = analyze_numeric_quantiles(rows, "adx")
    assert len(segments) == 4
    assert max(float(row["lift_vs_baseline"]) for row in segments) > 0


def test_calibration_service_builds_evidence_and_recommendations():
    rows = []
    for index in range(120):
        correct = index < 80
        row = _result_row(
            correct=correct,
            confidence=90 if correct else 85,
            adx=35 if correct else 18,
            direction="BULLISH" if index % 2 == 0 else "BEARISH",
        )
        if correct:
            row["evidence"] = ["ADX_RISING", "PLUS_DI_DOMINANT"]
        else:
            row["evidence"] = ["EMA_FAST_SLOPE_POSITIVE"]
        rows.append(row)

    result = ShadowFeatureCalibrationService().analyze(
        rows,
        minimum_segment_samples=10,
    )
    assert result["baseline"]["samples"] == 120
    assert result["evidence_segments"]
    assert result["strongest_segments"]
    assert all(row["execution_allowed"] is False for row in result["recommendations"])


def test_recommendations_require_sample_accuracy_and_lift():
    analyses = [{
        "feature": "adx",
        "segment": "(30, 50]",
        "samples": 40,
        "accuracy_30m": 65.0,
        "lift_vs_baseline": 10.0,
        "mfe_mae_ratio": 1.5,
    }]
    recommendations = build_recommendations(analyses)
    assert len(recommendations) == 1
    assert recommendations[0]["priority"] == 1
    assert recommendations[0]["execution_allowed"] is False
