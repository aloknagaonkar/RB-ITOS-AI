from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.ui.current_trade_exit_columns import (
    _protection_stage,
    _trail_moved,
)


def _position(*, entry=100.0, current=100.0, mfe=0.0, stop=85.0):
    return {
        "entry_price": entry,
        "current_price": current,
        "mfe_points": mfe,
        "stop_price": stop,
        "target1_price": 125.0,
        "target2_price": 140.0,
    }


def test_trailing_not_armed_before_trigger():
    health = PaperExitEngine().evaluate(position=_position(current=108.0, mfe=8.0))
    assert health.trailing_active is False
    assert _protection_stage(health) == "PROFIT LOCK ACTIVE"
    assert _trail_moved(health) == "NO — NOT ARMED"


def test_trailing_active_and_moved_above_initial_stop():
    health = PaperExitEngine().evaluate(position=_position(current=114.0, mfe=15.0))
    assert health.trailing_active is True
    assert health.trailing_stop == 109.25
    assert health.effective_stop == 109.25
    assert _protection_stage(health) == "TRAILING ACTIVE"
    assert _trail_moved(health) == "YES +24.25"


def test_trailing_stop_only_moves_up_with_higher_peak():
    first = PaperExitEngine().evaluate(position=_position(current=114.0, mfe=15.0))
    second = PaperExitEngine().evaluate(
        position={
            **_position(current=120.0, mfe=22.0),
            "protected_stop_price": first.effective_stop,
        }
    )
    assert second.trailing_active is True
    assert second.trailing_stop == 115.9
    assert second.effective_stop == 115.9
    assert second.effective_stop > first.effective_stop
