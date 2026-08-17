from red_bar_lab.execution.execution_policy import (
    RSI_EXIT_MODE,
    resolve_execution_policy,
)


def _assert_reversal_policy(signal):
    policy = resolve_execution_policy(signal)
    assert policy.stop_loss_pct == 7.0
    assert policy.target_pct is None
    assert policy.exit_mode == RSI_EXIT_MODE
    assert policy.directional_conflicts_observational is True


def test_red_bar_uses_reversal_premium_protection_policy():
    _assert_reversal_policy({
        "signal_id": "RB-TEST-1",
        "signal_source": "REFERENCE_LEVEL",
        "execution_strategy_source": "RED_BAR",
    })


def test_rsi_uses_reversal_premium_protection_policy():
    _assert_reversal_policy({
        "signal_id": "RSI7-TEST-1",
        "signal_source": "RSI_EXTREME_REVERSAL_V1",
    })


def test_directional_regime_uses_reversal_premium_protection_policy():
    _assert_reversal_policy({
        "signal_id": "DRI-TEST-1",
        "signal_source": "DIRECTIONAL_REGIME_INTELLIGENCE",
        "execution_strategy_source": "DIRECTIONAL_REGIME_INTELLIGENCE",
    })


def test_legacy_persisted_standard_exit_is_normalized():
    policy = resolve_execution_policy({
        "signal_id": "RB-LEGACY-1",
        "execution_strategy_source": "RED_BAR",
        "strategy_stop_loss_pct": 15.0,
        "strategy_target_pct": 25.0,
        "exit_mode": "STANDARD_MULTI_FACTOR",
    })
    assert policy.stop_loss_pct == 7.0
    assert policy.target_pct is None
    assert policy.exit_mode == RSI_EXIT_MODE
    assert policy.directional_conflicts_observational is True
