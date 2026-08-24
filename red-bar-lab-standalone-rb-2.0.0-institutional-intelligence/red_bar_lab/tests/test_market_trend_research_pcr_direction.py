from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from red_bar_lab.services.market_trend_research.models import (
    PcrBias,
    PcrMarketDirection,
)
from red_bar_lab.services.market_trend_research.policy import MarketTrendResearchPolicy
from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository
from red_bar_lab.tests.test_market_trend_research_live_ui import (
    NOW,
    RepositoryStub,
    StreamlitStub,
    _health,
    _projection,
)
from red_bar_lab.tests.test_market_trend_research_repository_and_performance import _snapshot
from red_bar_lab.ui import market_trend_research_panel as panel


@pytest.mark.parametrize(
    ("pcr", "classification", "direction", "reason_code", "explanation"),
    (
        (0.699, PcrBias.BEARISH, PcrMarketDirection.BEARISH,
         "PCR_BELOW_BEARISH_THRESHOLD", "PCR 0.699 is below 0.70."),
        (0.700, PcrBias.NEUTRAL, PcrMarketDirection.NEUTRAL,
         "PCR_WITHIN_NEUTRAL_RANGE", "PCR 0.700 is between 0.70 and 1.25."),
        (1.249, PcrBias.NEUTRAL, PcrMarketDirection.NEUTRAL,
         "PCR_WITHIN_NEUTRAL_RANGE", "PCR 1.249 is between 0.70 and 1.25."),
        (1.250, PcrBias.BULLISH, PcrMarketDirection.BULLISH,
         "PCR_WITHIN_BULLISH_RANGE", "PCR 1.250 is between 1.25 and 1.50."),
        (1.500, PcrBias.BULLISH, PcrMarketDirection.BULLISH,
         "PCR_WITHIN_BULLISH_RANGE", "PCR 1.500 is between 1.25 and 1.50."),
        (1.501, PcrBias.STRONGLY_BULLISH, PcrMarketDirection.BULLISH,
         "PCR_ABOVE_STRONG_BULLISH_THRESHOLD", "PCR 1.501 is above 1.50."),
    ),
)
def test_exact_pcr_direction_boundaries(
    pcr, classification, direction, reason_code, explanation
):
    policy = MarketTrendResearchPolicy()
    assert policy.classify(pcr) is classification
    evidence = policy.direction_evidence(pcr)
    assert evidence.classification is classification
    assert evidence.direction is direction
    assert evidence.reason_code == reason_code
    assert evidence.explanation == explanation
    assert evidence.authority == "OBSERVATIONAL_ONLY"


def test_unavailable_pcr_direction_is_explicit():
    evidence = MarketTrendResearchPolicy().direction_evidence(None)
    assert evidence.classification is PcrBias.UNAVAILABLE
    assert evidence.direction is PcrMarketDirection.UNAVAILABLE
    assert evidence.reason_code == "PCR_UNAVAILABLE"
    assert evidence.explanation == "PCR could not be calculated."


def test_new_projection_persists_direction_evidence(tmp_path):
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    repository.persist(_snapshot())
    projection = repository.latest_projection(underlying="NIFTY 50")
    aggregate = projection["current_panel"]["aggregate"]
    evidence = aggregate["direction_evidence"]
    expected = MarketTrendResearchPolicy().direction_evidence(
        aggregate["pcr"], classification=PcrBias(aggregate["classification"])
    )
    assert evidence["direction"] == expected.direction.value
    assert evidence["classification"] == expected.classification.value
    assert evidence["reason_code"] == expected.reason_code
    assert evidence["explanation"] == expected.explanation


def test_legacy_projection_uses_shared_policy_mapping():
    aggregate = {"pcr": 1.501, "classification": "STRONGLY_BULLISH"}
    evidence = panel._direction_evidence(aggregate)
    assert evidence["direction"] is PcrMarketDirection.BULLISH
    assert evidence["reason_code"] == "PCR_ABOVE_STRONG_BULLISH_THRESHOLD"


def test_clear_current_oi_labels_and_morning_labels_unchanged():
    assert panel.CURRENT_COLUMNS == (
        "Strike", "Position", "CE current OI", "CE previous-day OI",
        "CE OI change today", "CE OI change %", "PE current OI",
        "PE previous-day OI", "PE OI change today", "PE OI change %",
    )
    assert panel.MORNING_COLUMNS == (
        "Strike", "Position", "CE current OI", "CE opening OI",
        "CE since-open ΔOI", "CE since-open ΔOI%", "PE current OI",
        "PE opening OI", "PE since-open ΔOI", "PE since-open ΔOI%",
    )


def test_current_rows_use_clear_labels_and_existing_values():
    row = {
        "strike": 24250.0,
        "position": "ATM",
        "ce_current_oi": 120.0,
        "ce_previous_day_oi": 90.0,
        "ce_previous_day_change": 30.0,
        "ce_previous_day_change_pct": 33.333,
        "pe_current_oi": 150.0,
        "pe_previous_day_oi": 100.0,
        "pe_previous_day_change": 50.0,
        "pe_previous_day_change_pct": 50.0,
    }
    rendered = panel._current_rows({"rows": [row]})[0]
    assert rendered["CE OI change today"] == "+30"
    assert rendered["CE OI change %"] == "+33.33%"
    assert rendered["PE OI change today"] == "+50"
    assert rendered["PE OI change %"] == "+50.00%"


def test_overall_oi_summary_uses_total_row_values(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    projection = _projection()
    panel._render_current(projection, stale=False, live_source_age=3.0)
    text = "\n".join(str(value) for _, value in stub.calls)
    assert "Total CE OI change: +30 (+33.33%)" in text
    assert "Total PE OI change: +50 (+50.00%)" in text


def test_missing_and_zero_aggregate_percentages_render_unavailable(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    projection = _projection()
    total = projection["current_panel"]["rows"][-1]
    total["ce_previous_day_change"] = 120.0
    total["ce_previous_day_change_pct"] = None
    total["pe_previous_day_change"] = None
    total["pe_previous_day_change_pct"] = None
    panel._render_current(projection, stale=False, live_source_age=3.0)
    text = "\n".join(str(value) for _, value in stub.calls)
    assert "Total CE OI change: +120 (Not available)" in text
    assert "Total PE OI change: Not available (Not available)" in text


def test_direction_and_final_combined_direction_are_separate(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    panel._render_market_direction_research(_projection(), stale=False)
    text = "\n".join(str(value) for _, value in stub.calls)
    assert "PCR market direction': 'BULLISH" in text
    assert "Final combined direction': 'NOT YET CALCULATED" in text
    assert sum(kind == "dataframe" for kind, _ in stub.calls) == 1
    assert not any(kind in {"write", "caption"} for kind, _ in stub.calls)


def test_stale_projection_marks_pcr_direction_stale(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    panel._render_market_direction_research(_projection(), stale=True)
    text = "\n".join(str(value) for _, value in stub.calls)
    assert "BULLISH — STALE" in text


def test_current_panel_shows_only_overall_total_before_expanded_details(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    projection = _projection()
    strike_row = dict(projection["current_panel"]["rows"][0])
    strike_row.update({"strike": 24200.0, "position": "ATM"})
    projection["current_panel"]["rows"].insert(0, strike_row)

    panel._render_current(projection, stale=False, live_source_age=3.0)

    first_table = next(value for kind, value in stub.calls if kind == "dataframe")
    assert len(first_table) == 1
    assert first_table[0]["Position"] == "Overall total"
    assert any(
        kind == "expander" and value == "Current/Overall PCR details"
        for kind, value in stub.calls
    )


def test_full_cycle_keeps_one_projection_and_health_read(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    repository = RepositoryStub(_projection(), _health(age=3.0))
    panel._render_projection_cycle(repository, underlying="NIFTY 50", now=NOW)
    assert repository.projection_reads == 1
    assert repository.health_reads == 1


def test_ui_remains_projection_only():
    source = Path("red_bar_lab/ui/market_trend_research_panel.py").read_text(encoding="utf-8")
    assert "Upstox" not in source
    assert "requests" not in source
    assert ".execute(" not in source
    assert "latest_projection" in source
    assert "latest_runtime_health" in source
