from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from red_bar_lab.services.evidence_replay import EvidenceAwareHistoricalDecisionReplayService
from red_bar_lab.services.historical_decision_replay import HistoricalDecisionReplayService
from red_bar_lab.storage.database import RedBarDatabase


def _replay_result():
    row = SimpleNamespace(
        signal_id="RB-WIRING-1",
        timestamp="2026-08-13T10:05:00+05:30",
        level_type="FIRST_CANDLE",
        direction="BULLISH",
        option_side="CE",
        primary_confidence_pct=90.0,
        final_confidence_pct=90.0,
        expectancy_pct=1.0,
        decision="APPROVED",
        execution="WOULD_TAKE",
        blocker="NONE",
        data_fidelity="PARTIAL_LIVE_PARITY_HIGH",
        candidate_symbol="NIFTY24500CE",
        candidate_rank=1,
        candidate_score=90.0,
        opportunity_health=91.0,
        portfolio_status="APPROVED",
        portfolio_reason="PORTFOLIO_ADMITTED",
        exit_reason="BULLISH_EMA10_EXIT",
        option_entry_price=100.0,
        option_exit_price=112.0,
        option_return_pct=12.0,
        outcome_result="WIN",
        outcome_basis="EXECUTED_EXIT_ENGINE",
    )
    return SimpleNamespace(
        trading_date=date(2026, 8, 13),
        data_fidelity="PARTIAL_LIVE_PARITY_HIGH",
        data_source="LIVE_MARKET_CAPTURE",
        rows=(row,),
    )


def test_evidence_aware_replay_persists_only_after_parent_result_exists(tmp_path, monkeypatch):
    db = RedBarDatabase(tmp_path / "wiring.db")
    db.initialize()
    result = _replay_result()

    monkeypatch.setattr(
        HistoricalDecisionReplayService,
        "run_day",
        lambda self, instrument_key, trading_date: result,
    )

    service = EvidenceAwareHistoricalDecisionReplayService(
        SimpleNamespace(),
        option_chain_sync=SimpleNamespace(database=db),
    )
    returned = service.run_day("NSE_INDEX|Nifty 50", date(2026, 8, 13))

    assert returned is result
    assert service.last_evidence_report is not None
    assert service.last_evidence_report.records_written == 1

    from red_bar_lab.intelligence.historical_evidence import HistoricalEvidenceStore

    rows = HistoricalEvidenceStore(db).read(source_type="HISTORICAL_REPLAY")
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "RB-WIRING-1"
    assert rows[0]["outcome_result"] == "WIN"
    assert rows[0]["shadow_execution_impact"] == "NONE"


def test_workspace_routes_research_replay_through_evidence_wrapper():
    from red_bar_lab.ui import workspace
    from red_bar_lab.ui.pages import historical_intelligence, research_lab

    assert (
        research_lab.HistoricalDecisionReplayService
        is EvidenceAwareHistoricalDecisionReplayService
    )
    assert workspace._PAGE_MODULES["Historical Intelligence"] is historical_intelligence
