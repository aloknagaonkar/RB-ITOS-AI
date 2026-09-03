from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.services.red_bar_v2_structural_exit import execute_structural_stop_exits


def _order(option_type: str, source: str = "RED_BAR_V2") -> dict[str, object]:
    return {"order_id": option_type, "status": "OPEN", "option_type": option_type,
            "execution_strategy_source": source}


def test_completed_close_drives_pe_and_ce_structural_exits():
    snapshot = RedBarV2UISnapshot(
        reference_timestamp="2026-08-26T09:20:00+05:30",
        reference_high=24250.0,
        reference_low=24200.0,
    )
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
    snapshot = RedBarV2UISnapshot(
        reference_timestamp="2026-08-26T09:20:00+05:30",
        reference_high=24250.0,
        reference_low=24200.0,
    )
    closed: list[tuple[str, str]] = []
    result = execute_structural_stop_exits(
        snapshot=snapshot, completed_1m_close=24250.0,
        completed_1m_timestamp="2026-08-26T10:01:00+05:30",
        open_orders=[_order("PE"), _order("PE", "DIRECTIONAL_REGIME_INTELLIGENCE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )
    assert result.exited_orders == 0
    assert closed == []


def test_stale_reference_session_cannot_close_current_position():
    snapshot = RedBarV2UISnapshot(
        reference_timestamp="2026-08-25T09:20:00+05:30",
        reference_high=24250.0,
        reference_low=24200.0,
    )
    closed: list[tuple[str, str]] = []

    result = execute_structural_stop_exits(
        snapshot=snapshot,
        completed_1m_close=24260.0,
        completed_1m_timestamp="2026-08-26T10:01:00+05:30",
        open_orders=[_order("PE")],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )

    assert result.reason == "REFERENCE_SESSION_MISMATCH"
    assert result.exited_orders == 0
    assert closed == []


def test_a_position_opened_outside_the_band_is_not_closed_by_its_own_entry():
    """A deputy-born CE lives below the reference low from the moment it exists.

    Every completed close after such an entry is below ``reference_low``, so
    without reading the entry level this rule would close the position on its
    first cycle -- reporting the geometry of the entry as its invalidation. The
    guard only ever suppresses an exit, and only when the entry level is recorded
    and provably outside, so a row without one behaves exactly as before.
    """
    snapshot = RedBarV2UISnapshot(
        reference_timestamp="2026-08-26T09:20:00+05:30",
        reference_high=24250.0,
        reference_low=24200.0,
    )
    closed: list[tuple[str, str]] = []
    outside = dict(_order("CE"), underlying_price_entry=24150.0)
    inside = dict(_order("CE"), order_id="CE-INSIDE", underlying_price_entry=24225.0)
    unrecorded = _order("CE")
    unrecorded["order_id"] = "CE-UNRECORDED"

    result = execute_structural_stop_exits(
        snapshot=snapshot, completed_1m_close=24180.0,
        completed_1m_timestamp="2026-08-26T10:01:00+05:30",
        open_orders=[outside, inside, unrecorded],
        close_position=lambda order_id, reason: closed.append((order_id, reason)),
    )

    assert result.exited_orders == 2
    assert [order_id for order_id, _ in closed] == ["CE-INSIDE", "CE-UNRECORDED"]
