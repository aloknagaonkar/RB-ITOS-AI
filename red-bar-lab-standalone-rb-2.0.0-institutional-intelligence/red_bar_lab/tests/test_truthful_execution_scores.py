from red_bar_lab.execution.execution_score_contract import (
    truthful_execution_scores,
    with_truthful_execution_scores,
)


def test_legacy_probability_is_exposed_as_heuristic_not_calibrated_probability():
    result = truthful_execution_scores(
        {
            "execution_probability_pct": 95.0,
            "expectancy_pct": 1.75,
            "expectancy_source": "HISTORICAL_BLEND",
            "evidence_sample_size": 12,
            "evidence_ready": 1,
        }
    )

    assert result.selection_heuristic_score == 95.0
    assert result.research_expectancy_pct == 1.75
    assert result.calibrated_probability_pct is None
    assert result.calibration_status == "NOT_CALIBRATED"


def test_explicit_calibrated_probability_is_preserved():
    row = with_truthful_execution_scores(
        {
            "execution_probability_pct": 82.0,
            "calibrated_probability_pct": 61.5,
            "expectancy_pct": None,
            "evidence_sample_size": 250,
            "evidence_ready": True,
        }
    )

    assert row["selection_heuristic_score"] == 82.0
    assert row["calibrated_probability_pct"] == 61.5
    assert row["calibration_status"] == "CALIBRATED"
    assert row["research_expectancy_pct"] is None
