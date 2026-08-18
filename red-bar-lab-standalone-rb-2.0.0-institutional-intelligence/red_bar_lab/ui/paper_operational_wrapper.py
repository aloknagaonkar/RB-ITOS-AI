from __future__ import annotations

from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

import streamlit as st

from red_bar_lab.ui.active_trade_views import (
    ActiveTradeViewDatabaseProxy,
    render_candidates_and_queue,
    render_current_trades,
    render_recent_exits,
    render_trading_overview,
)


def build_operational_paper_page_wrapper(original):
    """Keep Paper Trading operational; Section 10 analysis lives on its own page."""

    @wraps(original)
    def wrapper(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        proxy = ActiveTradeViewDatabaseProxy(database)
        trading_date = (
            datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        )

        render_trading_overview(proxy, instrument_key, trading_date)
        render_current_trades(proxy)
        st.info(
            "Strategy attribution, performance reconciliation and the migration "
            "roadmap are available under Paper Architecture Reconciliation."
        )
        render_candidates_and_queue(proxy, trading_date)
        render_recent_exits(proxy)

        with st.expander(
            "Advanced Details & Diagnostics",
            expanded=False,
        ):
            st.caption(
                "Full legacy detail: market health, Red Bar eligibility, "
                "candidate lifecycle, session, Opportunity Health, Performance "
                "Selection, Committee evidence, exit diagnostics and history."
            )
            return original(
                settings,
                layout,
                proxy,
                token,
                underlying_name,
                instrument_key,
                interval,
            )

    return wrapper


__all__ = ["build_operational_paper_page_wrapper"]
