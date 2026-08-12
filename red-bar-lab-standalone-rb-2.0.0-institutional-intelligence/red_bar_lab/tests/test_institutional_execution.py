from types import SimpleNamespace

from red_bar_lab.execution.institutional_execution import InstitutionalExecutionCommittee
from red_bar_lab.execution.paper_engine import PaperContract
from red_bar_lab.execution.performance_selection import (
    HistoricalPerformance,
    TradeSelectionEvaluation,
)


def candidate(option_type="PE"):
    return SimpleNamespace(
        contract=PaperContract(
            instrument_token=101,
            tradingsymbol="NIFTYTESTPE" if option_type == "PE" else "NIFTYTESTCE",
            exchange="NFO",
            option_type=option_type,
            strike=24400.0,
            expiry="2026-08-11",
            lot_size=75,
        ),
        total_score=100.0,
    )


def selection(*, sample=0, wins=0, hist_score=50.0, eligible=True):
    h = HistoricalPerformance(
        sample_size=sample,
        wins=wins,
        losses=max(0, sample - wins),
        win_rate_pct=(wins / sample * 100 if sample else None),
        average_return_pct=None,
        average_winner_pct=None,
        average_loser_pct=None,
        profit_factor=None,
        expectancy_pct=None,
        average_mfe_pct=None,
        average_mae_pct=None,
        evidence_ready=sample >= 10,
    )
    return TradeSelectionEvaluation(
        candidate_rank=1,
        candidate_symbol="NIFTYTESTPE",
        candidate_score=100.0,
        opportunity_score=90.0,
        reward_remaining_pct=80.0,
        reward_risk_ratio=1.667,
        execution_quality_score=100.0,
        historical_score=hist_score,
        selection_score=88.0,
        historical=h,
        eligible=eligible,
        decision="BUY PE" if eligible else "SKIP",
        reason="ALL_SELECTION_GATES_PASS" if eligible else "BLOCKED",
    )


def opportunity(score=90.0):
    return SimpleNamespace(opportunity_score=score)


def test_strong_candidate_has_positive_ev_and_can_execute_without_history():
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=60)
    result = committee.evaluate(
        candidate=candidate(),
        selection=selection(),
        opportunity=opportunity(95),
        historical_orders=[],
        current_shadow=None,
        historical_shadow=[],
        stop_loss_pct=15,
        target_pct=25,
    )
    assert result.execution_probability_pct >= 60
    assert result.expected_value_pct > 0
    assert result.eligible is True


def test_performance_hard_block_remains_authoritative_and_is_transparent():
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=50)
    result = committee.evaluate(
        candidate=candidate(),
        selection=selection(eligible=False),
        opportunity=opportunity(100),
        historical_orders=[],
        current_shadow=None,
        historical_shadow=[],
        stop_loss_pct=15,
        target_pct=25,
    )
    assert result.eligible is False
    assert "PERFORMANCE_HARD_BLOCK" in result.reason
    assert "BLOCKED" in result.reason


def test_adaptive_module_reliability_rewards_proven_support():
    committee = InstitutionalExecutionCommittee(
        minimum_execution_probability_pct=50,
        minimum_module_samples=2,
    )
    orders = [
        {
            "signal_id": "S1", "status": "CLOSED", "option_type": "PE",
            "entry_price": 100, "exit_price": 120,
        },
        {
            "signal_id": "S2", "status": "CLOSED", "option_type": "PE",
            "entry_price": 100, "exit_price": 115,
        },
    ]
    historical_shadow = [
        {"signal_id": "S1", "modules": [
            {"module": "PCR", "recommendation": "BUY PE", "confidence": 80},
            {"module": "Market Context", "recommendation": "BUY CE", "confidence": 80},
        ]},
        {"signal_id": "S2", "modules": [
            {"module": "PCR", "recommendation": "BUY PE", "confidence": 85},
            {"module": "Market Context", "recommendation": "BUY CE", "confidence": 75},
        ]},
    ]
    current = {"modules": [
        {"module": "PCR", "recommendation": "BUY PE", "confidence": 90},
        {"module": "Market Context", "recommendation": "BUY CE", "confidence": 90},
    ]}
    result = committee.evaluate(
        candidate=candidate("PE"),
        selection=selection(),
        opportunity=opportunity(),
        historical_orders=orders,
        current_shadow=current,
        historical_shadow=historical_shadow,
        stop_loss_pct=15,
        target_pct=25,
    )
    modules = {m.module: m for m in result.modules}
    assert modules["PCR"].reliability_score > 50
    assert modules["PCR"].current_support == "SUPPORT"
    assert modules["Market Context"].current_support == "OPPOSE"
    assert result.intelligence_score > 50


def test_more_history_increases_payoff_authority_not_primary_confidence():
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=50)
    low = committee.evaluate(
        candidate=candidate(), selection=selection(sample=0), opportunity=opportunity(),
        historical_orders=[], current_shadow=None, historical_shadow=[],
        stop_loss_pct=15, target_pct=25,
    )
    high = committee.evaluate(
        candidate=candidate(), selection=selection(sample=40, wins=32, hist_score=90),
        opportunity=opportunity(), historical_orders=[], current_shadow=None,
        historical_shadow=[], stop_loss_pct=15, target_pct=25,
    )
    assert high.adaptive_history_weight_pct > low.adaptive_history_weight_pct
    # RB-1.2.0: history informs expectancy/payoff evidence; it does not replace
    # the Primary Rule Engine as execution-confidence authority.
    assert high.execution_probability_pct == low.execution_probability_pct
    assert any(v.expert == "Primary Rule Engine" for v in high.expert_votes)


def test_rb100_opportunity_reduces_probability_not_target_geometry():
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=0)
    opp = SimpleNamespace(opportunity_score=75.0, reward_remaining_pct=40.0)
    result = committee.evaluate(
        candidate=candidate(), selection=selection(), opportunity=opp,
        historical_orders=[], current_shadow=None, historical_shadow=[],
        stop_loss_pct=15, target_pct=25,
    )
    assert result.expected_win_pct == 25.0
    assert result.expected_loss_pct == 15.0
    assert result.expectancy_pct == result.expected_value_pct
    assert result.expectancy_source == "CONFIGURED_PAYOFF_PRIOR"


def test_rb100_expectancy_formula_uses_probability_and_payoff():
    from red_bar_lab.execution.expectancy_engine import expectancy_pct
    assert expectancy_pct(75.0, 25.0, 15.0) == 15.0


def test_rb141_shadow_agreement_is_informational_only():
    c = candidate()
    c.total_score = 80.0
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=0)
    result = committee.evaluate(
        candidate=c, selection=selection(), opportunity=opportunity(90),
        historical_orders=[], current_shadow={
            "shadow_decision": "BUY PE",
            "shadow_confidence": 90,
            "modules": [
                {"module": "PCR", "recommendation": "BUY PE", "confidence": 85},
                {"module": "Greeks", "recommendation": "BUY PE", "confidence": 90},
            ],
        }, historical_shadow=[], stop_loss_pct=15, target_pct=25,
    )
    assert result.primary_confidence_pct == 80.0
    assert result.shadow_decision == "BUY PE"
    assert result.agreement == "AGREE"
    assert result.shadow_adjustment_pct == 0.0
    assert result.execution_probability_pct == 80.0
    assert result.expected_win_pct == 25.0
    assert result.expected_loss_pct == 15.0


def test_rb141_shadow_conflict_is_informational_only():
    c = candidate()
    c.total_score = 88.0
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=0)
    result = committee.evaluate(
        candidate=c, selection=selection(), opportunity=opportunity(90),
        historical_orders=[], current_shadow={
            "shadow_decision": "BUY CE",
            "shadow_confidence": 80,
            "modules": [],
        }, historical_shadow=[], stop_loss_pct=15, target_pct=25,
    )
    assert result.agreement == "CONFLICT"
    assert result.shadow_adjustment_pct == 0.0
    assert result.execution_probability_pct == 88.0


def test_rb141_shadow_wait_is_informational_only():
    c = candidate()
    c.total_score = 80.0
    committee = InstitutionalExecutionCommittee(minimum_execution_probability_pct=0)
    result = committee.evaluate(
        candidate=c, selection=selection(), opportunity=opportunity(90),
        historical_orders=[], current_shadow={
            "shadow_decision": "WAIT",
            "shadow_confidence": 75,
            "modules": [],
        }, historical_shadow=[], stop_loss_pct=15, target_pct=25,
    )
    assert result.agreement == "NEUTRAL"
    assert result.shadow_adjustment_pct == 0.0
    assert result.execution_probability_pct == 80.0

