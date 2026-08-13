from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.candidate_lifecycle import CandidateLifecycleManager
from red_bar_lab.execution.portfolio_manager import PortfolioCandidate, PortfolioRiskManager

IST = ZoneInfo("Asia/Kolkata")


def _pc(qid, rank, health, expectancy, price=100.0, qty=50, kind="PE"):
    return PortfolioCandidate(
        queue_id=qid,
        signal_id="SIG",
        symbol=qid,
        option_type=kind,
        rank=rank,
        candidate_score=90 - rank,
        opportunity_health=health,
        expectancy_pct=expectancy,
        reference_price=price,
        stop_loss_pct=15.0,
        quantity=qty,
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


def test_portfolio_pass_through_approves_all_committee_candidates():
    manager = PortfolioRiskManager(
        maximum_open_trades=1,
        maximum_same_direction=1,
        maximum_capital_pct=1,
        maximum_risk_pct=0.1,
        minimum_opportunity_health=99,
    )
    rows = manager.admit(
        [
            _pc("Q1", 1, 92, 12),
            _pc("Q2", 2, 88, 11),
            _pc("Q3", 3, 83, 9),
        ],
        initial_capital=100000,
        current_open_trades=10,
        current_deployed_capital=100000,
        current_risk=100000,
        current_ce=10,
        current_pe=10,
    )

    assert len(rows) == 3
    assert all(row.admitted is True for row in rows)
    assert {row.status for row in rows} == {"APPROVED"}
    assert {row.reason for row in rows} == {
        "COMMITTEE_APPROVED_PORTFOLIO_BYPASSED"
    }


def test_portfolio_pass_through_does_not_block_for_risk_or_capital():
    manager = PortfolioRiskManager(
        maximum_open_trades=1,
        maximum_same_direction=1,
        maximum_capital_pct=1,
        maximum_risk_pct=0.1,
        minimum_opportunity_health=100,
    )
    rows = manager.admit(
        [
            _pc("LOW", 3, 10, -20, price=1000, qty=500),
            _pc("BEST", 1, 95, 14, price=1000, qty=500),
            _pc("MID", 2, 50, -10, price=1000, qty=500),
        ],
        initial_capital=1000,
        current_open_trades=50,
        current_deployed_capital=500000,
        current_risk=250000,
        current_pe=50,
    )

    assert [row.queue_id for row in rows] == ["BEST", "MID", "LOW"]
    assert all(row.admitted for row in rows)
    assert all(row.status == "APPROVED" for row in rows)


def test_portfolio_pass_through_does_not_block_low_opportunity_health():
    manager = PortfolioRiskManager(
        minimum_opportunity_health=99,
        maximum_risk_pct=0.1,
    )
    rows = manager.admit(
        [
            _pc("RANK1-WEAK", 1, 1, -50, price=20, qty=10),
            _pc("RANK2-STRONG", 2, 90, 10, price=20, qty=10),
        ],
        initial_capital=100,
    )

    by_id = {row.queue_id: row for row in rows}
    assert by_id["RANK1-WEAK"].admitted is True
    assert by_id["RANK2-STRONG"].admitted is True
    assert all(row.reason == "COMMITTEE_APPROVED_PORTFOLIO_BYPASSED" for row in rows)
