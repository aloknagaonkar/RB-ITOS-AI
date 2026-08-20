from __future__ import annotations

import sqlite3
from typing import Any

from red_bar_lab.ui.pre_trade_full_card import (
    build_pre_trade_full_card,
    render_pre_trade_full_card,
)
from red_bar_lab.ui.red_bar_v2_live_runtime import resolve_red_bar_v2_live_state
from red_bar_lab.ui.red_bar_v2_runtime_diagnostics import (
    render_red_bar_v2_runtime_diagnostics,
)


def _latest_v2_trading_date(database: Any) -> str | None:
    path = getattr(database, "path", None)
    if not path:
        return None
    try:
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                """
                SELECT trading_date
                FROM paper_signal_diagnostics
                WHERE signal_id LIKE 'RBV2-%'
                ORDER BY timestamp DESC, id DESC LIMIT 1
                """
            ).fetchone()
    except (sqlite3.Error, OSError):
        return None
    return str(row[0]) if row and row[0] else None


def install(page_module: Any, database: Any, instrument_key: str) -> None:
    """Make the Red Bar Strategy legacy panel reflect latest persisted V2 runtime."""
    if not hasattr(page_module, "render_red_bar_v2_legacy_panel"):
        return

    page_module._red_bar_v2_runtime_database = database
    page_module._red_bar_v2_runtime_instrument_key = instrument_key

    if getattr(page_module, "_red_bar_v2_live_state_installed", False):
        return

    original_render = page_module.render_red_bar_v2_legacy_panel

    def render_red_bar_v2_legacy_panel(st, snapshot, open_orders=None):
        current_database = page_module._red_bar_v2_runtime_database
        current_instrument = page_module._red_bar_v2_runtime_instrument_key
        trading_date = _latest_v2_trading_date(current_database)
        resolved = snapshot
        diagnostics = None
        if trading_date:
            resolved, runtime = resolve_red_bar_v2_live_state(
                current_database,
                snapshot,
                instrument_key=current_instrument,
                trading_date=trading_date,
            )
            diagnostics = runtime.to_dict()

        original_render(st, resolved, open_orders=open_orders)
        if diagnostics is not None and resolved is not None:
            card = build_pre_trade_full_card(current_database, resolved, diagnostics)
            render_pre_trade_full_card(st, card)
            render_red_bar_v2_runtime_diagnostics(st, diagnostics)

    page_module.render_red_bar_v2_legacy_panel = render_red_bar_v2_legacy_panel
    page_module._red_bar_v2_live_state_installed = True


__all__ = ["install"]
