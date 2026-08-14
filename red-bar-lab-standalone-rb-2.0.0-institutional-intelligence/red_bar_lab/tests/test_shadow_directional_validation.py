from datetime import date

from red_bar_lab.services.shadow_directional_validation import (
    confidence_band,
    evaluate_promotion_gates,
    MultiDayShadowValidationService,
)


def row(day, direction="BULLISH", correct=True, regime="TRENDING_BULLISH", confidence=80):
    return {
        "trading_date": day,
        "direction": direction,
        "direction_correct_5m": correct,
        "direction_correct_15m": correct,
        "direction_correct_30m": correct,
        "maximum_favorable_excursion": 20.0,
        "maximum_adverse_excursion": 8.0,
        "regime": regime,
        "confidence": confidence,
    }


def test_confidence_bands():
    assert confidence_band(20) == "LOW"
    assert confidence_band(50) == "MODERATE"
    assert confidence_band(65) == "STRONG"
    assert confidence_band(80) == "VERY_STRONG"


def test_promotion_gates_fail_for_small_sample():
    rows = [row("2026-08-01"), row("2026-08-02", direction="BEARISH")]
    result = evaluate_promotion_gates(rows)
    assert result.eligible is False
    assert "INSUFFICIENT SAMPLE" in result.warnings


def test_promotion_gates_can_pass_balanced_evidence():
    rows = []
    for session in range(20):
        day = f"2026-07-{session + 1:02d}"
        for i in range(5):
            rows.append(row(
                day,
                direction="BULLISH" if i % 2 == 0 else "BEARISH",
                regime="TRENDING_BULLISH" if i % 3 else "RANGE",
            ))
    result = evaluate_promotion_gates(rows)
    assert result.eligible is True
    assert result.evaluated_transitions == 100
    assert result.trading_sessions == 20


def test_weekends_are_excluded():
    service = MultiDayShadowValidationService()
    dates = service.trading_dates(date(2026, 8, 7), date(2026, 8, 10))
    assert all(day.weekday() < 5 for day in dates)
