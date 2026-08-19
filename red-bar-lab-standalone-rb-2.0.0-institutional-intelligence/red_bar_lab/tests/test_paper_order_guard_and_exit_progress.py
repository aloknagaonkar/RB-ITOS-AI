from __future__ import annotations

import pytest

from red_bar_lab.execution.paper_order_guard import (
    PaperOrderGuardError,
    validate_paper_order,
)
from red_bar_lab.ui.red_bar_v2_legacy_panel import (
    _exit_level,
    _exit_progress_rows,
)


def _order(**overrides):
    row = {
        "account_id": "PAPER-STD",
        "signal_id": "SIG-1",
        "instrument_token": 100,
        "option_type": "PE",
        "execution_strategy_source": "RED_BAR_V2",
    }
    row.update(overrides)
    return row


def test_reference_level_is_blocked_when_v2_is_authority():
    with pytest.raises(PaperOrderGuardError, match="PAPER_SOURCE_DISABLED"):
        validate_paper_order(
            _order(execution_strategy_source="REFERENCE_LEVEL"),
            [],
            lambda source: source == "RED_BAR_V2",
        )


def test_same_direction_limit_is_rechecked_at_insert_boundary():
    open_rows = [
        _order(signal_id=f"SIG-{index}", instrument_token=index)
        for index in range(3)
    ]
    with pytest.raises(
        PaperOrderGuardError,
        match="MAXIMUM_SAME_DIRECTION_TRADES_REACHED",
    ):
        validate_paper_order(
            _order(signal_id="SIG-NEW", instrument_token=999),
            open_rows,
            lambda source: source == "RED_BAR_V2",
        )


def test_duplicate_signal_contract_is_skipped_before_database_constraint():
    with pytest.raises(PaperOrderGuardError, match="DUPLICATE_PAPER_ORDER_SKIPPED"):
        validate_paper_order(
            _order(),
            [_order()],
            lambda source: source == "RED_BAR_V2",
        )


def test_exit_progress_reports_current_target_level():
    order = {
        "tradingsymbol": "NIFTY PE",
        "execution_strategy_source": "RED_BAR_V2",
        "entry_price": 100.0,
        "current_price": 126.0,
        "stop_price": 85.0,
        "target1_price": 125.0,
        "target2_price": 140.0,
        "unrealized_pnl": 1300.0,
        "mfe_points": 30.0,
        "mae_points": -4.0,
        "exit_mode": "FIXED_TRAILING",
    }

    assert _exit_level(order) == "TARGET 1 REACHED"
    row = _exit_progress_rows([order])[0]
    assert row["Current level"] == "TARGET 1 REACHED"
    assert row["Move %"] == "+26.00%"
    assert row["Exit mode"] == "FIXED_TRAILING"
