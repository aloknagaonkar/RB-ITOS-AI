from red_bar_lab.execution.exit_engine import PaperExitEngine


def _position(entry: float, current: float, peak: float, **extra):
    return {
        "entry_price": entry,
        "current_price": current,
        "initial_stop_price": entry * 0.85,
        "stop_price": entry * 0.85,
        "mfe_points": peak - entry,
        **extra,
    }


def test_five_percent_peak_arms_breakeven():
    health = PaperExitEngine().evaluate(
        position=_position(100.0, 103.0, 105.0)
    )
    assert health.breakeven_armed is True
    assert health.effective_stop == 100.0


def test_eight_percent_peak_locks_two_percent_profit():
    health = PaperExitEngine().evaluate(
        position=_position(100.0, 104.0, 108.0)
    )
    assert health.profit_lock_active is True
    assert health.profit_lock_price == 102.0
    assert health.effective_stop == 102.0


def test_twelve_percent_peak_starts_five_percent_trailing():
    health = PaperExitEngine().evaluate(
        position=_position(100.0, 110.0, 112.0)
    )
    assert health.trailing_active is True
    assert health.trailing_stop == 106.4
    assert health.effective_stop == 106.4


def test_protected_stop_never_moves_backward():
    health = PaperExitEngine().evaluate(
        position=_position(
            100.0,
            108.0,
            112.0,
            protected_stop_price=109.0,
        )
    )
    assert health.effective_stop == 109.0


def test_profit_lock_exit_is_not_negative():
    health = PaperExitEngine().evaluate(
        position=_position(100.0, 101.5, 108.0)
    )
    assert health.action == "EXIT"
    assert health.hard_exit_reason == "PROFIT_LOCK_STOP"
