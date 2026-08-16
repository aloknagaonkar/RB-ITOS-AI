from red_bar_lab.execution.execution_policy import (
    RSI_EXIT_MODE,
    RSI_STRATEGY_SOURCE,
    resolve_execution_policy,
)


def test_rsi7_id_fallback_resolves_frozen_policy():
    policy = resolve_execution_policy({"signal_id": "RSI7-ABC123"})
    assert policy.strategy_source == RSI_STRATEGY_SOURCE
    assert policy.stop_loss_pct == 7.0
    assert policy.target_pct is None
    assert policy.exit_mode == RSI_EXIT_MODE


def test_persisted_queue_policy_survives_missing_artifact():
    policy = resolve_execution_policy({
        "signal_id": "RSI7-ABC123",
        "execution_strategy_source": RSI_STRATEGY_SOURCE,
        "strategy_stop_loss_pct": 7.0,
        "strategy_target_pct": None,
        "exit_mode": RSI_EXIT_MODE,
    })
    assert policy.stop_loss_pct == 7.0
    assert policy.target_pct is None
    assert policy.exit_mode == RSI_EXIT_MODE


def test_standard_persisted_policy_remains_standard():
    policy = resolve_execution_policy({
        "signal_id": "RB-1",
        "execution_strategy_source": "REFERENCE_LEVEL",
        "strategy_stop_loss_pct": 15.0,
        "strategy_target_pct": 25.0,
        "exit_mode": "STANDARD_MULTI_FACTOR",
    })
    assert policy.stop_loss_pct == 15.0
    assert policy.target_pct == 25.0
    assert policy.exit_mode == "STANDARD_MULTI_FACTOR"
