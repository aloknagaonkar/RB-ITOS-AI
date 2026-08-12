from red_bar_lab.execution.institutional_execution import InstitutionalExecutionCommittee
from red_bar_lab.tests.test_institutional_execution import candidate, selection, opportunity


def _evaluate(shadow_decision, shadow_confidence):
    c = candidate(); c.total_score = 76.0
    return InstitutionalExecutionCommittee(minimum_execution_probability_pct=70).evaluate(
        candidate=c, selection=selection(), opportunity=opportunity(90), historical_orders=[],
        current_shadow={"shadow_decision": shadow_decision, "shadow_confidence": shadow_confidence, "modules": []},
        historical_shadow=[], stop_loss_pct=15, target_pct=25,
    )


def test_shadow_never_changes_execution_probability_or_eligibility():
    agree = _evaluate("BUY PE", 100)
    wait = _evaluate("WAIT", 100)
    conflict = _evaluate("BUY CE", 100)
    assert {agree.execution_probability_pct, wait.execution_probability_pct, conflict.execution_probability_pct} == {76.0}
    assert {agree.shadow_adjustment_pct, wait.shadow_adjustment_pct, conflict.shadow_adjustment_pct} == {0.0}
    assert agree.eligible == wait.eligible == conflict.eligible
    assert agree.decision == wait.decision == conflict.decision


def test_shadow_is_still_reported_for_research():
    result = _evaluate("BUY CE", 83)
    assert result.shadow_decision == "BUY CE"
    assert result.shadow_confidence_pct == 83.0
    assert result.agreement == "CONFLICT"
    shadow_vote = next(v for v in result.expert_votes if v.expert == "Shadow Intelligence")
    assert shadow_vote.effective_weight == 0.0
    assert shadow_vote.contribution == 0.0
    assert "INFORMATIONAL ONLY" in shadow_vote.detail
