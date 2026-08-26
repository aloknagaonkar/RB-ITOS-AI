from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.execution.execution_policy import resolve_execution_policy
from red_bar_lab.services.red_bar_v2_rsi_exit import execute_rsi_threshold_exits


def _order(option_type: str) -> dict[str, object]:
    return {
        "order_id": f"ORDER-{option_type}",
        "status": "OPEN",
        "option_type": option_type,
        "execution_strategy_source": "RED_BAR_V2",
    }


def test_pe_exits_when_completed_one_minute_rsi_is_above_45():
    closed: list[tuple[str, str]] = []
    held = execute_rsi_threshold_exits(
        completed_1m_rsi=45.0,
        completed_1m_timestamp="2026-08-25T10:00:00+05:30",
        open_orders=[_order("PE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    assert held.exited_orders == 0

    exited = execute_rsi_threshold_exits(
        completed_1m_rsi=45.01,
        completed_1m_timestamp="2026-08-25T10:01:00+05:30",
        open_orders=[_order("PE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    assert exited.exited_orders == 1
    assert closed == [("ORDER-PE", "AUTO_RSI_ABOVE_45")]


def test_ce_exits_when_completed_one_minute_rsi_is_below_55():
    closed: list[tuple[str, str]] = []
    result = execute_rsi_threshold_exits(
        completed_1m_rsi=54.99,
        completed_1m_timestamp="2026-08-25T10:01:00+05:30",
        open_orders=[_order("CE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    assert result.exited_orders == 1
    assert closed == [("ORDER-CE", "AUTO_RSI_BELOW_55")]


def test_red_bar_v2_has_no_initial_premium_stop_but_keeps_profit_protection():
    policy = resolve_execution_policy({"execution_strategy_source": "RED_BAR_V2"})
    assert policy.initial_premium_stop_enabled is False
    position = {
        "entry_price": 100.0,
        "current_price": 92.0,
        "stop_price": 93.0,
        "mfe_points": 0.0,
        "execution_strategy_source": "RED_BAR_V2",
    }
    loss = PaperExitEngine().evaluate(position=position, exit_mode=policy.exit_mode)
    assert loss.hard_exit_reason is None
    assert loss.effective_stop is None

    position.update(current_price=108.0, mfe_points=8.0)
    protected = PaperExitEngine().evaluate(position=position, exit_mode=policy.exit_mode)
    assert protected.effective_stop == 102.0
    assert protected.profit_lock_active is True


def test_other_strategies_keep_initial_premium_stop():
    policy = resolve_execution_policy(
        {"execution_strategy_source": "DIRECTIONAL_REGIME_INTELLIGENCE"}
    )
    assert policy.initial_premium_stop_enabled is True
