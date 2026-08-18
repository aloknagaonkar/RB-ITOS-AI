from __future__ import annotations

import streamlit as st

from red_bar_lab.ui.historical_red_bar_v2_windows import _render_window_panel
from red_bar_lab.ui.red_bar_v2_promotion_panel import (
    render_red_bar_v2_promotion_panel,
)


def render_page(
    settings,
    layout,
    database,
    token,
    underlying_name,
    instrument_key,
    interval,
) -> None:
    """Dedicated Red Bar V2 research, replay and promotion-readiness workspace."""
    st.subheader("Red Bar V2 Validation")
    st.caption(
        "Dedicated research workspace for the NEXT_RED_CANDLE RSI/VWAP strategy. "
        "Historical validation and promotion evidence are observation-only and "
        "cannot place paper or live orders."
    )

    mode_col, source_col, exit_col = st.columns(3)
    mode_col.metric("Strategy mode", "RESEARCH / SHADOW")
    source_col.metric("Replay source", "Underlying 1-minute OHLCV")
    exit_col.metric("Exit authority", "Legacy exit path unchanged")

    with st.expander("How to use this workspace", expanded=True):
        st.markdown(
            "1. Confirm cached one-minute historical dates are available in "
            "**Research Lab → Historical Data**.\n"
            "2. Choose the validation end date below.\n"
            "3. Run the 10-day or 20-day Red Bar V2 validation.\n"
            "4. Review ready/blocked dates and candidate counts.\n"
            "5. Refresh promotion evidence after validation completes."
        )
        st.info(
            "The dedicated page uses the same validated Red Bar V2 replay engine "
            "and append-only promotion-evidence store as Research Lab."
        )

    _render_window_panel(
        layout=layout,
        database=database,
        token=token,
        instrument_key=instrument_key,
    )

    render_red_bar_v2_promotion_panel(st, settings)
