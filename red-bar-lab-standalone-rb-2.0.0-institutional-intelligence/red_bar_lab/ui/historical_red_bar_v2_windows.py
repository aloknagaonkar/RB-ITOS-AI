from __future__ import annotations

from functools import wraps

import pandas as pd
import streamlit as st

from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.red_bar_v2_historical_validation import (
    RED_BAR_V2_STRATEGY_ID,
    RED_BAR_V2_VERSION,
    red_bar_v2_strategy_registry,
    run_red_bar_v2_historical_strategy_validation,
)
from red_bar_lab.services.upstox_service import RedBarUpstoxService


_SESSION_PREFIX = "historical_red_bar_v2_window"


def build_red_bar_v2_window_wrapper(original_render):
    """Append dedicated 10-day and 20-day Red Bar V2 validators."""

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
        result = original_render(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )
        _render_window_panel(
            layout=layout,
            database=database,
            token=token,
            instrument_key=instrument_key,
        )
        return result

    return wrapped


def _render_window_panel(*, layout, database, token, instrument_key) -> None:
    st.markdown("---")
    st.markdown("#### Red Bar V2 — 10-Day / 20-Day Historical Validation")
    st.caption(
        "Runs the validated Red Bar V2 NEXT_RED_CANDLE RSI/VWAP replay over the "
        "latest cached one-minute sessions up to the selected end date. This is "
        "research-only and does not place paper or live orders."
    )

    try:
        reader = RedBarHistoricalService(RedBarUpstoxService("cache-only"), layout)
        available_dates = reader.available_dates(instrument_key, interval_minutes=1)
    except Exception as exc:
        st.warning(f"Unable to read cached replay dates: {type(exc).__name__}: {exc}")
        return

    if not available_dates:
        st.info("Download/cache historical one-minute candles before running validation.")
        return

    end_date = st.selectbox(
        "Red Bar V2 Validation End Date",
        available_dates,
        index=len(available_dates) - 1,
        format_func=lambda value: value.isoformat(),
        key="historical_red_bar_v2_end_date",
    )

    c1, c2 = st.columns(2)
    with c1:
        run_10 = st.button(
            "Run 10-Day Red Bar V2 Validation",
            type="primary",
            key="historical_red_bar_v2_run_10",
        )
    with c2:
        run_20 = st.button(
            "Run 20-Day Red Bar V2 Validation",
            key="historical_red_bar_v2_run_20",
        )

    requested_days = 10 if run_10 else 20 if run_20 else None
    if requested_days is not None:
        _run_window(
            requested_days=requested_days,
            available_dates=available_dates,
            end_date=end_date,
            reader=reader,
            layout=layout,
            database=database,
            token=token,
            instrument_key=instrument_key,
        )

    for window_days in (10, 20):
        state = st.session_state.get(f"{_SESSION_PREFIX}_{window_days}")
        if not state or state.get("instrument_key") != instrument_key:
            continue
        _render_result(window_days, state["report"])


def _run_window(
    *,
    requested_days,
    available_dates,
    end_date,
    reader,
    layout,
    database,
    token,
    instrument_key,
) -> None:
    eligible = tuple(day for day in available_dates if day <= end_date)
    selected_dates = eligible[-requested_days:]
    progress = st.progress(0.0, text=f"Preparing {requested_days}-day Red Bar V2 validation...")
    status = st.empty()

    if len(selected_dates) < requested_days:
        status.warning(
            f"Only {len(selected_dates)}/{requested_days} cached sessions are available. "
            "The result will remain diagnostic."
        )

    try:
        from red_bar_lab.ui._shared import HistoricalOptionChainSyncService

        option_sync = HistoricalOptionChainSyncService(
            RedBarUpstoxService(token or "cache-only"),
            layout,
            reader,
            database=database,
        )
        reports = run_red_bar_v2_historical_strategy_validation(
            replay_reader=reader,
            option_chain_sync=option_sync,
            instrument_key=instrument_key,
            trading_dates=selected_dates,
            strategies=((RED_BAR_V2_STRATEGY_ID, RED_BAR_V2_VERSION),),
            registry=red_bar_v2_strategy_registry(),
        )
        report = reports[0]
        st.session_state[f"{_SESSION_PREFIX}_{requested_days}"] = {
            "instrument_key": instrument_key,
            "end_date": end_date,
            "report": report,
        }
        progress.progress(1.0, text=f"Completed {len(report.days)}/{requested_days} sessions")
        if len(report.days) == requested_days and report.metrics.blocked_days == 0:
            status.success(f"{requested_days} Red Bar V2 sessions were validated.")
        else:
            status.warning(
                f"Completed {len(report.days)}/{requested_days} sessions with "
                f"{report.metrics.blocked_days} blocked day(s)."
            )
    except Exception as exc:
        st.exception(exc)


def _render_result(window_days: int, report) -> None:
    st.markdown(f"##### Red Bar V2 {window_days}-Day Results")
    metrics = report.metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Requested Days", len(report.requested_dates))
    m2.metric("Ready Days", metrics.ready_days)
    m3.metric("Blocked Days", metrics.blocked_days)
    m4.metric("Candidate Events", sum(len(day.rows) for day in report.days))
    m5.metric("Readiness", f"{metrics.readiness_pct:.1f}%")

    rows = []
    for day in report.days:
        admitted = sum(1 for row in day.rows if row.execution.startswith("SHADOW_"))
        blocked = sum(1 for row in day.rows if row.execution == "BLOCKED")
        rows.append(
            {
                "Trading Date": day.trading_date.isoformat(),
                "Ready": day.ready,
                "Fidelity": day.fidelity,
                "Reason": day.readiness_reason,
                "Admitted Candidates": admitted,
                "Blocked Candidates": blocked,
                "Total Candidate Events": len(day.rows),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)
    st.download_button(
        f"Download Red Bar V2 {window_days}-Day CSV",
        data=pd.DataFrame(rows).to_csv(index=False),
        file_name=f"red_bar_v2_{window_days}day_validation.csv",
        mime="text/csv",
        key=f"historical_red_bar_v2_{window_days}day_download",
    )
