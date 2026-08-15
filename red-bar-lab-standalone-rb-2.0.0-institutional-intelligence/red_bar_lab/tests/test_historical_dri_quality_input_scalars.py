from dataclasses import fields
from pathlib import Path

from red_bar_lab.services.historical_decision_replay import DecisionReplayRow


def test_quality_input_audit_fields_exist():
    names = {item.name for item in fields(DecisionReplayRow)}
    assert "quality_candidate_score_input" in names
    assert "quality_opportunity_health_input" in names


def test_service_uses_exact_row_scalars_for_quality():
    service = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "historical_dri_decision_replay.py"
    ).read_text(encoding="utf-8")
    assert "quality_candidate_score_input = resolve_numeric_metric(" in service
    assert "quality_opportunity_health_input = resolve_numeric_metric(" in service
    assert "candidate_score=quality_candidate_score_input" in service
    assert "opportunity_health=quality_opportunity_health_input" in service


def test_ui_exports_quality_input_audit_columns():
    ui = (
        Path(__file__).resolve().parents[1]
        / "ui"
        / "pages"
        / "research_lab.py"
    ).read_text(encoding="utf-8")
    assert '"Quality Candidate Score Input":' in ui
    assert '"Quality Opportunity Health Input":' in ui
