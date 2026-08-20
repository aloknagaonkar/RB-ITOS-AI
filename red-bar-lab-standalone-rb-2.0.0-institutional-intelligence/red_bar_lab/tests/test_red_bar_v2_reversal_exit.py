from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.services.red_bar_v2_reversal_exit import (
    REVERSAL_EXIT_REASON,
    confirmed_live_direction,
    execute_confirmed_reversal_exits,
)


def _snapshot(**overrides):
    values = {
        "alignment_status": "READY",
        "trend_strength": "CONFIRMED",
        "reference_midpoint": 24200.0,
        "index_close": 24250.0,
        "index_rsi": 58.0,
        "futures_close": 24320.0,
        "futures_vwap": 24270.0,
        "direction": "BEARISH",
        "option_side": "PE",
    }
    values.update(overrides)
    return RedBarV2UISnapshot(**values)


def test_confirmed_live_direction_uses_current_inputs_not_old_trade_direction():
    assert confirmed_live_direction(_snapshot()) == "BULLISH"


def test_confirmed_reversal_closes_only_conflicting_v2_orders():
    closed = []
    orders = [
        {
            "order_id": "PE-1",
            "execution_strategy_source": "RED_BAR_V2",
            "status": "OPEN",
            "option_type": "PE",
        },
        {
            "order_id": "CE-1",
            "execution_strategy_source": "RED_BAR_V2",
            "status": "OPEN",
            "option_type": "CE",
        },
        {
            "order_id": "LEGACY-PE",
            "execution_strategy_source": "REFERENCE_LEVEL",
            "status": "OPEN",
            "option_type": "PE",
        },
    ]

    result = execute_confirmed_reversal_exits(
        snapshot=_snapshot(),
        open_orders=orders,
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )

    assert result.status == "EXITED"
    assert result.confirmed_direction == "BULLISH"
    assert result.conflicting_orders == 1
    assert result.exited_orders == 1
    assert closed == [("PE-1", REVERSAL_EXIT_REASON)]


def test_incomplete_alignment_does_not_force_exit():
    closed = []
    result = execute_confirmed_reversal_exits(
        snapshot=_snapshot(index_rsi=48.0),
        open_orders=[
            {
                "order_id": "PE-1",
                "execution_strategy_source": "RED_BAR_V2",
                "status": "OPEN",
                "option_type": "PE",
            }
        ],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )

    assert result.status == "NO_ACTION"
    assert closed == []
