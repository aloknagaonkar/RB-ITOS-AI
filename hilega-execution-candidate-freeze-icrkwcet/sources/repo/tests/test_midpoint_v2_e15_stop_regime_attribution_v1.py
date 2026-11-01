from market_lab.midpoint_v2_e15_stop_regime_attribution_v1 import classify_stop_regime


def test_initial_sl5_regime():
    row = {
        "exit_reason": "STOP_TOUCH",
        "stop_history": [
            {
                "active_stop": 95.0,
                "breakeven_active": False,
                "trail_active": False,
            }
        ],
    }
    assert classify_stop_regime(row) == "INITIAL_SL5"


def test_breakeven_regime():
    row = {
        "exit_reason": "STOP_TOUCH",
        "stop_history": [
            {
                "active_stop": 100.0,
                "breakeven_active": True,
                "trail_active": False,
            }
        ],
    }
    assert classify_stop_regime(row) == "BREAKEVEN"


def test_trailing_takes_precedence_over_breakeven():
    row = {
        "exit_reason": "STOP_GAP",
        "stop_history": [
            {
                "active_stop": 111.0,
                "breakeven_active": True,
                "trail_active": True,
            }
        ],
    }
    assert classify_stop_regime(row) == "TRAILING"


def test_time_exit_is_not_stop():
    row = {
        "exit_reason": "TIME_EXIT",
        "stop_history": [],
    }
    assert classify_stop_regime(row) == "NOT_STOP_EXIT"
