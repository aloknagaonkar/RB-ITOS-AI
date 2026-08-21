from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from red_bar_lab.ui.pre_trade_full_card import (
    build_pre_trade_full_card,
    render_pre_trade_full_card,
)
from red_bar_lab.ui.red_bar_v2_live_runtime import resolve_red_bar_v2_live_state
from red_bar_lab.ui.red_bar_v2_runtime_diagnostics import (
    render_red_bar_v2_runtime_diagnostics,
)


def _diagnostic_date_expression(conn: sqlite3.Connection, alias: str = "") -> str:
    """Return a date expression compatible with old and current diagnostics schemas."""
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(paper_signal_diagnostics)")
    }
    prefix = f"{alias}." if alias else ""
    if "trading_date" in columns:
        return f"{prefix}trading_date"
    return f"substr({prefix}timestamp, 1, 10)"


def _latest_v2_trading_date(database: Any) -> str | None:
    path = getattr(database, "path", None)
    if not path:
        return None
    try:
        with sqlite3.connect(str(path)) as conn:
            date_expression = _diagnostic_date_expression(conn)
            row = conn.execute(
                f"""
                SELECT {date_expression}
                FROM paper_signal_diagnostics
                WHERE signal_id LIKE 'RBV2-%'
                ORDER BY timestamp DESC, id DESC LIMIT 1
                """
            ).fetchone()
    except (sqlite3.Error, OSError):
        return None
    return str(row[0]) if row and row[0] else None


def _diagnostics_dict(value: Any) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    payload = getattr(value, "__dict__", None)
    return dict(payload) if isinstance(payload, dict) else None


def install(page_module: Any, database: Any, instrument_key: str) -> None:
    """Make the Red Bar Strategy legacy panel reflect latest persisted V2 runtime."""
    if not hasattr(page_module, "render_red_bar_v2_legacy_panel"):
        return

    page_module._red_bar_v2_runtime_database = database
    page_module._red_bar_v2_runtime_instrument_key = instrument_key

    if getattr(page_module, "_red_bar_v2_live_state_installed", False):
        return

    original_render = page_module.render_red_bar_v2_legacy_panel

    def render_red_bar_v2_legacy_panel(
        st,
        snapshot,
        open_orders=None,
        option_context=None,
        runtime_diagnostics=None,
        **kwargs,
    ):
        current_database = page_module._red_bar_v2_runtime_database
        current_instrument = page_module._red_bar_v2_runtime_instrument_key
        resolved = snapshot
        diagnostics_object = runtime_diagnostics
        diagnostics = _diagnostics_dict(runtime_diagnostics)

        # Newer pages resolve the selected trading date before calling the panel.
        # Preserve that result. The fallback below keeps older call sites working.
        if runtime_diagnostics is None:
            trading_date = _latest_v2_trading_date(current_database)
            if trading_date:
                resolved, runtime = resolve_red_bar_v2_live_state(
                    current_database,
                    snapshot,
                    instrument_key=current_instrument,
                    trading_date=trading_date,
                )
                diagnostics_object = runtime
                diagnostics = runtime.to_dict()

        original_render(
            st,
            resolved,
            open_orders=open_orders,
            option_context=option_context,
            runtime_diagnostics=diagnostics_object,
            **kwargs,
        )
        if diagnostics is not None and resolved is not None:
            card = build_pre_trade_full_card(current_database, resolved, diagnostics)
            render_pre_trade_full_card(st, card)
            render_red_bar_v2_runtime_diagnostics(st, diagnostics)

    page_module.render_red_bar_v2_legacy_panel = render_red_bar_v2_legacy_panel
    page_module._red_bar_v2_live_state_installed = True


__all__ = ["install"]
