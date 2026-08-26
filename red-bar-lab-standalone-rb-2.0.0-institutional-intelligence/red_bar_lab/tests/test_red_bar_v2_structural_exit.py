from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.services.red_bar_v2_structural_exit import execute_structural_stop_exits


def _order(option_type: str, source: str = "RED_BAR_V2") -> dict[str, object]:
    return {"order_id": option_type, "status": "OPEN", "option_type": option_type,
            "execution_strategy_source": source}


def test_completed_close_drives_pe_and_ce_structural_exits():
    snapshot = RedBarV2UISnapshot(reference_high=24250.0, reference_low=24200.0)
    closed: list[tuple[str, str]] = []
    pe = execute_structural_stop_exits(
        snapshot=snapshot, completed_1m_close=24250.01,
        completed_1m_timestamp="2026-08-26T10:01:00+05:30",
        open_orders=[_order("PE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    ce = execute_structural_stop_exits(
        snapshot=snapshot, completed_1m_close=24199.99,
        completed_1m_timestamp="2026-08-26T10:02:00+05:30",
        open_orders=[_order("CE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    assert pe.exited_orders == ce.exited_orders == 1
    assert closed == [
        ("PE", "AUTO_REFERENCE_HIGH_INVALIDATION"),
        ("CE", "AUTO_REFERENCE_LOW_INVALIDATION"),
    ]


def test_boundary_equality_and_other_strategies_do_not_exit():
    snapshot = RedBarV2UISnapshot(reference_high=24250.0, reference_low=24200.0)
    closed: list[tuple[str, str]] = []
    result = execute_structural_stop_exits(
        snapshot=snapshot, completed_1m_close=24250.0,
        completed_1m_timestamp="2026-08-26T10:01:00+05:30",
        open_orders=[_order("PE"), _order("PE", "DIRECTIONAL_REGIME_INTELLIGENCE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    assert result.exited_orders == 0
    assert closed == []
