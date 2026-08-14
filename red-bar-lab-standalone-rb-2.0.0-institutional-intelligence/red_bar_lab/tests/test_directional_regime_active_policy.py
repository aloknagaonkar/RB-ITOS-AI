from red_bar_lab.execution.directional_regime_policy import (
    evaluate_directional_regime_policy,
)


def test_aligned_adds_bonus_and_caps_score():
    policy = evaluate_directional_regime_policy(
        "ALIGNED",
        aligned_bonus=5.0,
    )
    assert policy.block_execution is False
    assert policy.action == "CONFIDENCE_BONUS"
    assert policy.adjusted_score(93.0) == 98.0
    assert policy.adjusted_score(99.0) == 100.0


def test_conflict_holds_execution():
    policy = evaluate_directional_regime_policy("CONFLICT")
    assert policy.block_execution is True
    assert policy.action == "HOLD"
    assert policy.candidate_score_bonus == 0.0


def test_partial_and_neutral_continue_without_bonus():
    for status in ("PARTIAL_ALIGNMENT", "NEUTRAL"):
        policy = evaluate_directional_regime_policy(status)
        assert policy.block_execution is False
        assert policy.action == "CONTINUE"
        assert policy.adjusted_score(70.0) == 70.0


def test_unavailable_is_fail_open():
    policy = evaluate_directional_regime_policy(None)
    assert policy.status == "UNAVAILABLE"
    assert policy.block_execution is False
    assert policy.action == "CONTINUE"
