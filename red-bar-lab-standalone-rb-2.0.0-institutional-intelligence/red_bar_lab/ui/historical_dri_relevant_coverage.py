from __future__ import annotations

from functools import wraps

import pandas as pd
import streamlit as st

from red_bar_lab.services.historical_dri_relevant_coverage_compat import (
    analyze_historical_dri_relevant_coverage,
)
from red_bar_lab.ui._shared import (
    HistoricalOptionChainSyncService,
    RedBarHistoricalService,
    RedBarUpstoxService,
    _st_dataframe_arrow_safe,
)

_SESSION_KEY = "historical_dri_relevant_coverage_audit"


def build_relevant_coverage_wrapper(original_render):
    """Append a diagnostic-only relevant-contract coverage audit."""

    @wraps(original_render)
    def wrapped(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        original_render(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )
        _render_relevant_coverage_audit(
            layout=layout,
            database=database,
            token=token,
            instrument_key=instrument_key,
        )

    return wrapped


def _render_relevant_coverage_audit(*, layout, database, token, instrument_key) -> None:
    st.markdown("---")
    st.markdown("#### DRI Strategy-Relevant Option Coverage Audit")
    st.caption(
        "Explains whether incomplete historical option data affects contracts that "
        "could plausibly enter the DRI Rank-1 candidate universe. The audit uses the "
        "actual underlying session range plus a two-strike safety buffer. It is "
        "read-only and cannot override Replay Ready, change strategy rules, or permit "
        "an unreliable date into the 10-day promotion sample."
    )

    try:
        replay_reader = RedBarHistoricalService(
            RedBarUpstoxService("cache-only"), layout
        )
        available_dates = replay_reader.available_dates(
            instrument_key, interval_minutes=1
        )
    except Exception as exc:
        st.warning(f"Unable to read cached dates: {type(exc).__name__}: {exc}")
        return

    if not available_dates:
        st.info("No cached one-minute historical dates are available.")
        return

    selected_date = st.selectbox(
        "Coverage Audit Trading Date",
        available_dates,
        index=len(available_dates) - 1,
        format_func=lambda value: value.isoformat(),
        key="historical_dri_relevant_coverage_date",
    )

    if st.button(
        "Run Strategy-Relevant Coverage Audit",
        key="historical_dri_relevant_coverage_run",
    ):
        try:
            sync = HistoricalOptionChainSyncService(
                RedBarUpstoxService(token or "cache-only"),
                layout,
                replay_reader,
                database=database,
            )
            with st.spinner(
                "Auditing near-market CE/PE candle and OI coverage..."
            ):
                coverage = sync.validate_day(instrument_key, selected_date)
                underlying = replay_reader.read_day(
                    instrument_key,
                    selected_date,
                    interval_minutes=1,
                )
                audit = analyze_historical_dri_relevant_coverage(
                    coverage,
                    underlying,
                )
            st.session_state[_SESSION_KEY] = {
                "instrument_key": instrument_key,
                "trading_date": selected_date,
                "audit": audit,
            }
        except Exception as exc:
            st.exception(exc)

    state = st.session_state.get(_SESSION_KEY)
    if (
        not state
        or state.get("instrument_key") != instrument_key
        or state.get("trading_date") != selected_date
    ):
        return

    audit = state["audit"]
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    a1.metric(
        "Global Replay Ready",
        "YES" if audit.global_replay_ready else "NO",
    )
    a2.metric("Audit Status", audit.status)
    a3.metric("Relevant Contracts", audit.relevant_contracts)
    a4.metric(
        "Relevant Ready",
        f"{audit.relevant_complete_contracts}/{audit.relevant_contracts}",
    )
    a5.metric(
        "Relevant Candle Coverage",
        f"{audit.relevant_candle_coverage_pct:.1f}%",
    )
    a6.metric(
        "Relevant OI Coverage",
        f"{audit.relevant_oi_coverage_pct:.1f}%",
    )

    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("Session Low", _format_number(audit.reference_low))
    b2.metric("Session High", _format_number(audit.reference_high))
    b3.metric("Strike Step", _format_number(audit.strike_step))
    b4.metric("Relevant CE", audit.relevant_ce_contracts)
    b5.metric("Relevant PE", audit.relevant_pe_contracts)

    if audit.status == "FULL_REPLAY_READY":
        st.success(audit.reason)
    elif audit.status == "STRATEGY_RELEVANT_COVERAGE_HIGH":
        st.warning(
            audit.reason
            + " The date remains excluded until a separately reviewed replay policy "
            "is approved; this audit does not automatically reclassify it."
        )
    else:
        st.error(audit.reason)

    st.caption(
        "Relevant strike window: "
        f"{_format_number(audit.relevant_low)} to "
        f"{_format_number(audit.relevant_high)}. "
        "Per-contract audit thresholds: candle coverage >= 90% and OI coverage >= 80%."
    )

    relevant_rows = audit.relevant_rows()
    st.markdown("##### Strategy-Relevant Contracts")
    if relevant_rows:
        _st_dataframe_arrow_safe(
            relevant_rows,
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No contracts could be classified as strategy-relevant for this date.")

    with st.expander("All Contract Coverage", expanded=False):
        all_rows = audit.all_rows()
        if all_rows:
            _st_dataframe_arrow_safe(
                all_rows,
                width="stretch",
                hide_index=True,
            )

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download Relevant Contracts CSV",
            data=pd.DataFrame(relevant_rows).to_csv(index=False),
            file_name=(
                f"historical_dri_relevant_coverage_{selected_date.isoformat()}.csv"
            ),
            mime="text/csv",
            key="historical_dri_relevant_coverage_download",
        )
    with c2:
        st.download_button(
            "Download Audit Summary CSV",
            data=pd.DataFrame([audit.summary()]).to_csv(index=False),
            file_name=(
                f"historical_dri_relevant_coverage_summary_"
                f"{selected_date.isoformat()}.csv"
            ),
            mime="text/csv",
            key="historical_dri_relevant_coverage_summary_download",
        )


def _format_number(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"
