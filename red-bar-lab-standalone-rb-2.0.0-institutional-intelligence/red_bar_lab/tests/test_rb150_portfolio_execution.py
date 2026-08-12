from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.candidate_lifecycle import CandidateLifecycleManager
from red_bar_lab.execution.portfolio_manager import PortfolioCandidate, PortfolioRiskManager

IST = ZoneInfo("Asia/Kolkata")


def _pc(qid, rank, health, expectancy, price=100.0, qty=50, kind="PE"):
    return PortfolioCandidate(
        queue_id=qid, signal_id="SIG", symbol=qid, option_type=kind, rank=rank,
        candidate_score=90-rank, opportunity_health=health,
        expectancy_pct=expectancy, reference_price=price,
        stop_loss_pct=15.0, quantity=qty,
    )


def test_rb150_old_signal_age_is_informational_only():
    now = datetime(2026, 8, 11, 14, 0, tzinfo=IST)
    manager = CandidateLifecycleManager(freshness_seconds=180)
    row = manager.evaluate(
        signal_id="OLD-BUT-ALIVE",
        confirmation_timestamp=(now - timedelta(hours=2)).isoformat(),
        now=now,
    )
    assert row.state == "AGING"
    assert row.active is True
    assert row.replacement_required is False
    assert row.reason == "CURRENT_CANDIDATE"


def test_rb150_portfolio_admits_multiple_best_candidates_when_budget_allows():
    manager = PortfolioRiskManager(
        maximum_open_trades=5, maximum_same_direction=3,
        maximum_capital_pct=40, maximum_risk_pct=5,
        minimum_opportunity_health=75,
    )
    rows = manager.admit([
        _pc("Q1", 1, 92, 12),
        _pc("Q2", 2, 88, 11),
        _pc("Q3", 3, 83, 9),
    ], initial_capital=100000)
    assert sum(row.admitted for row in rows) == 3
    assert {row.status for row in rows} == {"APPROVED"}


def test_rb150_portfolio_prioritizes_best_and_watchlists_when_risk_full():
    manager = PortfolioRiskManager(
        maximum_open_trades=5, maximum_same_direction=3,
        maximum_capital_pct=100, maximum_risk_pct=2,
        minimum_opportunity_health=75,
    )
    rows = manager.admit([
        _pc("LOW", 3, 80, 8, price=100, qty=75),
        _pc("BEST", 1, 95, 14, price=100, qty=75),
        _pc("MID", 2, 88, 10, price=100, qty=75),
    ], initial_capital=100000)
    approved = [row.queue_id for row in rows if row.admitted]
    waiting = [row.queue_id for row in rows if not row.admitted]
    assert approved == ["BEST"]
    assert set(waiting) == {"MID", "LOW"}
    assert all("RISK_BUDGET" in row.reason for row in rows if not row.admitted)


def test_rb150_weak_opportunity_health_stays_watchlist_even_if_rank_one():
    manager = PortfolioRiskManager(minimum_opportunity_health=75, maximum_risk_pct=10)
    rows = manager.admit([
        _pc("RANK1-WEAK", 1, 60, 20, price=20, qty=10),
        _pc("RANK2-STRONG", 2, 90, 10, price=20, qty=10),
    ], initial_capital=100000)
    by_id = {row.queue_id: row for row in rows}
    assert by_id["RANK1-WEAK"].admitted is False
    assert by_id["RANK2-STRONG"].admitted is True
