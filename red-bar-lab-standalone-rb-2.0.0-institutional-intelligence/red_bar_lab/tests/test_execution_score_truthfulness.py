from __future__ import annotations

import inspect

from red_bar_lab.execution.execution_score_contract import (
    MINIMUM_CALIBRATION_BUCKET_SAMPLES,
    calibration_is_ready,
    public_execution_scores,
    truthful_execution_scores,
)
from red_bar_lab.ui.pages import committee_diagnostics


def _deciles(samples: int):
    return [
        {
            "decile": index + 1,
            "labelled_outcomes": samples,
            "predicted_probability_pct": 5 + index * 10,
            "realized_success_pct": 4 + index * 10,
        }
        for index in range(10)
    ]


def test_public_contract_hides_legacy_probability_and_expected_value_names():
    result = public_execution_scores({
        "execution_probability_pct": 82.5,
        "expected_value_pct": 4.2,
        "expectancy_pct": 1.4,
    })

    assert result["selection_heuristic_score"] == 82.5
    assert result["research_expectancy_pct"] == 1.4
    assert "execution_probability_pct" not in result
    assert "expected_value_pct" not in result
    assert result["calibrated_probability_pct"] is None


def test_probability_is_withheld_until_all_deciles_have_200_labels():
    assert MINIMUM_CALIBRATION_BUCKET_SAMPLES == 200
    assert calibration_is_ready(_deciles(199)) is False
    assert calibration_is_ready(_deciles(200)) is True

    unready = truthful_execution_scores({
        "execution_probability_pct": 75,
        "calibrated_probability_pct": 72,
        "calibration_deciles": _deciles(199),
    })
    ready = truthful_execution_scores({
        "execution_probability_pct": 75,
        "calibrated_probability_pct": 72,
        "calibration_deciles": _deciles(200),
    })

    assert unready.calibrated_probability_pct is None
    assert unready.calibration_status == "NOT_CALIBRATED"
    assert ready.calibrated_probability_pct == 72
    assert ready.calibration_status == "CALIBRATED"


def test_committee_ui_keeps_sections_and_uses_truthful_labels():
    source = inspect.getsource(committee_diagnostics.render_page)
    assert "Committee Gate Trace" in source
    assert "Authoritative Committee Gates" in source
    assert "Persisted Committee Reason" in source
    assert "Candidate Context" in source
    assert "Selection Heuristic Score" in source
    assert "Research Expectancy" in source
    assert "Final Probability" not in source
