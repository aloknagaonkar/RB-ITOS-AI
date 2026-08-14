from red_bar_lab.services.shadow_out_of_sample_validation import (
    classify_groups,
    summarize_group,
    ShadowOutOfSampleValidationService,
)


def row(
    *,
    direction="BULLISH",
    breakout=True,
    adx_slope=3.0,
    displacement=3.0,
    correct=True,
    day="2026-08-01",
    regime="TRENDING_BULLISH",
):
    return {
        "direction": direction,
        "breakout": breakout,
        "adx_slope": adx_slope,
        "directional_displacement_atr": displacement,
        "direction_correct_30m": correct,
        "maximum_favorable_excursion": 20.0 if correct else 8.0,
        "maximum_adverse_excursion": 6.0 if correct else 18.0,
        "trading_date": day,
        "regime": regime,
        "time_bucket": "MORNING_1030_1159",
        "evidence": [
            "ADX_RISING",
            "SWING_HIGH_BREAKOUT",
            "POSITIVE_ATR_DISPLACEMENT",
        ],
    }


def test_group_classification():
    rows = [
        row(),
        row(direction="BEARISH", breakout=False),
        row(adx_slope=1.0),
    ]
    groups = classify_groups(rows)
    assert len(groups["BASELINE"]) == 3
    assert len(groups["BULLISH_ONLY"]) == 2
    assert len(groups["BULLISH_BREAKOUT"]) == 2
    assert len(groups["CALIBRATED_BULLISH_BREAKOUT"]) == 1


def test_passing_group_meets_all_gates():
    rows = []
    for index in range(24):
        rows.append(
            row(
                correct=True,
                day=f"2026-08-{(index % 12) + 1:02d}",
                regime="TRENDING_BULLISH" if index % 2 else "EXPANSION",
            )
        )
    result = summarize_group("TEST", rows)
    assert result.eligible is True
    assert result.accuracy_30m == 100.0
    assert result.represented_regimes == 2


def test_small_group_fails_sample_gate():
    result = summarize_group("TEST", [row()] * 5)
    assert result.eligible is False
    assert "INSUFFICIENT OUT-OF-SAMPLE SIGNALS" in result.warnings


def test_service_returns_all_four_groups_and_blocks_execution():
    rows = [row() for _ in range(25)]
    result = ShadowOutOfSampleValidationService().evaluate(rows)
    assert len(result["summaries"]) == 4
    assert result["execution_allowed"] is False
    assert all(
        summary["execution_allowed"] is False
        for summary in result["summaries"]
    )
