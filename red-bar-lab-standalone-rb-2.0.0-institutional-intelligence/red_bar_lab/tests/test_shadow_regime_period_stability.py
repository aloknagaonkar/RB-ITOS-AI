from red_bar_lab.services.shadow_regime_period_stability import (
    ShadowRegimePeriodStabilityService,
)


def row(
    *,
    day,
    timestamp,
    correct,
    direction="BULLISH",
    regime="EXPANSION",
    time_bucket="MORNING_1030_1159",
    range_atr=1.5,
    mfe=20.0,
    mae=10.0,
):
    return {
        "trading_date": day,
        "timestamp": timestamp,
        "direction_correct_5m": correct,
        "direction_correct_15m": correct,
        "direction_correct_30m": correct,
        "maximum_favorable_excursion": mfe,
        "maximum_adverse_excursion": mae,
        "direction": direction,
        "regime": regime,
        "time_bucket": time_bucket,
        "range_atr": range_atr,
    }


def test_period_comparison_detects_accuracy_decay():
    calibration = [
        row(
            day="2026-07-01",
            timestamp=f"2026-07-01 10:{index:02d}:00",
            correct=True,
        )
        for index in range(20)
    ]
    oos = [
        row(
            day="2026-08-01",
            timestamp=f"2026-08-01 10:{index:02d}:00",
            correct=index < 5,
            mfe=8.0,
            mae=20.0,
        )
        for index in range(20)
    ]

    result = ShadowRegimePeriodStabilityService().analyze(calibration, oos)
    codes = {item["code"] for item in result["findings"]}
    assert "PERIOD_ACCURACY_DECAY" in codes
    assert "OOS_ADVERSE_MOVE_DOMINATES" in codes
    assert result["execution_allowed"] is False


def test_duplicate_density_detects_close_same_direction_signals():
    oos = [
        row(
            day="2026-08-01",
            timestamp="2026-08-01 10:00:00",
            correct=False,
        ),
        row(
            day="2026-08-01",
            timestamp="2026-08-01 10:05:00",
            correct=False,
        ),
        row(
            day="2026-08-01",
            timestamp="2026-08-01 10:10:00",
            correct=True,
        ),
    ]
    result = ShadowRegimePeriodStabilityService().analyze([], oos)
    assert result["duplicate_density"]["possible_duplicates"] == 2
    assert result["duplicate_density"]["duplicate_share_pct"] > 0


def test_failure_cluster_is_reported():
    oos = [
        row(
            day="2026-08-01",
            timestamp=f"2026-08-01 10:{index:02d}:00",
            correct=False,
        )
        for index in range(3)
    ]
    result = ShadowRegimePeriodStabilityService().analyze([], oos)
    assert result["failure_clusters"][0]["failures"] == 3
    codes = {item["code"] for item in result["findings"]}
    assert "CONSECUTIVE_FAILURE_CLUSTER" in codes


def test_grouped_outputs_exist():
    rows = [
        row(
            day="2026-08-01",
            timestamp="2026-08-01 10:00:00",
            correct=True,
            regime="TRENDING_BULLISH",
            range_atr=0.8,
        )
    ]
    result = ShadowRegimePeriodStabilityService().analyze(rows, rows)
    assert result["calibration_by_week"]
    assert result["oos_by_regime"]
    assert result["oos_by_volatility"]
