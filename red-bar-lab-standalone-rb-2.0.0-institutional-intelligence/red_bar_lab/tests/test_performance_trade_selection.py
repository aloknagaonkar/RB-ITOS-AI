from types import SimpleNamespace

from red_bar_lab.execution.performance_selection import PerformanceTradeSelectionEngine


def _candidate(score=90.0, spread=15.0, liquidity=20.0, option_type="CE"):
    return SimpleNamespace(
        total_score=score,
        spread_score=spread,
        liquidity_score=liquidity,
        contract=SimpleNamespace(option_type=option_type, tradingsymbol="TESTCE"),
    )


def _opportunity(score=90.0, reward=80.0, eligible=True):
    return SimpleNamespace(
        opportunity_score=score,
        reward_remaining_pct=reward,
        eligible=eligible,
    )


def test_selection_uses_neutral_history_prior_when_sample_is_small():
    engine = PerformanceTradeSelectionEngine(
        minimum_selection_score=60,
        minimum_history_samples=10,
    )
    result = engine.evaluate(
        candidate=_candidate(),
        candidate_rank=2,
        opportunity=_opportunity(),
        historical_orders=[],
        entry_mode="FRESH_SIGNAL",
        minimum_candidate_score=65,
        stop_loss_pct=15,
        target_pct=25,
        require_opportunity_gate=False,
    )
    assert result.historical.sample_size == 0
    assert result.historical.evidence_ready is False
    assert result.historical_score == 50.0
    assert result.eligible is True
    assert result.candidate_rank == 2


def test_bad_mature_history_becomes_soft_evidence():
    orders = []
    for i in range(10):
        orders.append({
            "status": "CLOSED",
            "option_type": "CE",
            "entry_mode": "FRESH_SIGNAL",
            "entry_price": 100.0,
            "exit_price": 95.0 if i < 8 else 110.0,
            "mfe_points": 10.0,
            "mae_points": 5.0,
        })
    engine = PerformanceTradeSelectionEngine(
        minimum_selection_score=50,
        minimum_history_samples=10,
    )
    result = engine.evaluate(
        candidate=_candidate(),
        candidate_rank=1,
        opportunity=_opportunity(),
        historical_orders=orders,
        entry_mode="FRESH_SIGNAL",
        minimum_candidate_score=65,
        stop_loss_pct=15,
        target_pct=25,
        require_opportunity_gate=False,
    )
    assert result.historical.evidence_ready is True
    assert result.historical.win_rate_pct == 20.0
    assert result.eligible is True
    assert "HISTORICAL_WIN_RATE" in result.reason
    assert "SOFT_EVIDENCE" in result.reason


def test_stale_candidate_opportunity_failure_is_soft_evidence():
    engine = PerformanceTradeSelectionEngine(minimum_selection_score=50)
    result = engine.evaluate(
        candidate=_candidate(),
        candidate_rank=1,
        opportunity=_opportunity(eligible=False),
        historical_orders=[],
        entry_mode="OPPORTUNITY_EXTENSION",
        minimum_candidate_score=65,
        stop_loss_pct=15,
        target_pct=25,
        require_opportunity_gate=True,
    )
    assert result.eligible is True
    assert "OPPORTUNITY_EXTENSION" in result.reason
    assert "SOFT_EVIDENCE" in result.reason


def test_tss_below_reference_does_not_veto_when_execution_quality_is_valid():
    engine = PerformanceTradeSelectionEngine(minimum_selection_score=70)
    result = engine.evaluate(
        candidate=_candidate(score=86.0),
        candidate_rank=1,
        opportunity=_opportunity(score=50.0),
        historical_orders=[],
        entry_mode="FRESH_SIGNAL",
        minimum_candidate_score=65,
        stop_loss_pct=15,
        target_pct=25,
        require_opportunity_gate=False,
    )
    assert result.selection_score < 70
    assert result.eligible is True
    assert "TSS=" in result.reason
    assert "NO_HARD_PERFORMANCE_BLOCKERS" in result.reason
    assert "REWARD_RISK_INFORMATIONAL_ONLY" in result.reason


def test_spread_remains_a_hard_blocker():
    engine = PerformanceTradeSelectionEngine(minimum_selection_score=70)
    result = engine.evaluate(
        candidate=_candidate(spread=0),
        candidate_rank=1,
        opportunity=_opportunity(),
        historical_orders=[],
        entry_mode="FRESH_SIGNAL",
        minimum_candidate_score=65,
        stop_loss_pct=15,
        target_pct=25,
        require_opportunity_gate=False,
    )
    assert result.eligible is False
    assert "HARD_BLOCK:SPREAD" in result.reason
