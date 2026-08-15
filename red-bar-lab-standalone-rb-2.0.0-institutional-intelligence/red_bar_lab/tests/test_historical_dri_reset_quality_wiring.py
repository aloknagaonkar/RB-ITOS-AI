from types import SimpleNamespace

from red_bar_lab.services.historical_dri_quality_refinement import (
    evaluate_reset_override_quality,
    resolve_numeric_metric,
)


def test_first_directional_entry_bypasses_reset_quality():
    result = evaluate_reset_override_quality(
        None,
        moment=None,
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="FIRST_DIRECTIONAL_ENTRY",
        break_level=None,
        candidate_score=95,
        opportunity_health=95,
    )
    assert result["applicable"] is False
    assert result["passed"] is True


def test_real_reset_override_uses_quality_gate():
    result = evaluate_reset_override_quality(
        None,
        moment=None,
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=None,
        candidate_score=95,
        opportunity_health=95,
    )
    assert result["applicable"] is True


def test_resolve_numeric_metric_across_object_shapes():
    rank1 = SimpleNamespace(candidate_score=88.89)
    opportunity = {"health_score": 85.0}
    assert resolve_numeric_metric(
        rank1,
        names=("candidate_score", "score"),
    ) == 88.89
    assert resolve_numeric_metric(
        opportunity,
        names=("health_score", "health"),
    ) == 85.0
