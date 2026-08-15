from __future__ import annotations

from functools import wraps

import pandas as pd
import streamlit as st

from red_bar_lab.services.historical_dri_10day_validation import (
    run_latest_ready_dri_window,
)
from red_bar_lab.services.historical_dri_decision_replay import (
    HistoricalDRIDecisionReplayService,
)
from red_bar_lab.ui._shared import (
    HistoricalOptionChainSyncService,
    RedBarHistoricalService,
    RedBarUpstoxService,
    _st_dataframe_arrow_safe,
)

_SESSION_KEY = "historical_dri_10day_validation"


def build_10day_validation_wrapper(original_render, research_lab_module):
    """Append the 10-day validator without rewriting Research Lab."""

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
        _render_10day_validation(
            layout=layout,
            database=database,
            token=token,
            instrument_key=instrument_key,
            research_lab_module=research_lab_module,
        )

    return wrapped


def _render_10day_validation(
    *,
    layout,
    database,
    token,
    instrument_key,
    research_lab_module,
) -> None:
    st.markdown("---")
    st.markdown("#### 10-Day DRI Risk & Consistency Validation")
    st.caption(
        "Runs the frozen DRI entry policy over the latest ten replay-ready "
        "trading dates up to the selected end date. Dates with incomplete "
        "option replay are skipped automatically, and the scan continues "
        "backward until ten successful days are collected. No live orders "
        "or strategy tuning are performed."
    )

    try:
        replay_reader = RedBarHistoricalService(
            RedBarUpstoxService("cache-only"), layout
        )
        available_dates = replay_reader.available_dates(
            instrument_key, interval_minutes=1
        )
    except Exception as exc:
        st.warning(f"Unable to read cached replay dates: {type(exc).__name__}: {exc}")
        return

    if not available_dates:
        st.info("Download/cache historical one-minute candles before running validation.")
        return

    end_date = st.selectbox(
        "10-Day Validation End Date",
        available_dates,
        index=len(available_dates) - 1,
        format_func=lambda value: value.isoformat(),
        key="historical_dri_10day_end_date",
    )
    st.caption(
        "The application checks cached dates from newest to oldest and uses "
        "only dates whose historical option replay reports Replay Ready = YES."
    )

    if st.button(
        "Run Enhanced 10-Day DRI Validation",
        type="primary",
        key="historical_dri_10day_run",
    ):
        progress = st.progress(0.0, text="Preparing 10-day validation...")
        status = st.empty()
        try:
            option_sync = HistoricalOptionChainSyncService(
                RedBarUpstoxService(token or "cache-only"),
                layout,
                replay_reader,
                database=database,
            )

            def validate_day(trading_date):
                return option_sync.validate_day(instrument_key, trading_date)

            def run_day(trading_date):
                policy = research_lab_module.HistoricalDecisionReplayService(
                    replay_reader,
                    freshness_seconds=180,
                    hard_expiry_seconds=900,
                    minimum_confidence_pct=70.0,
                    stop_loss_pct=15.0,
                    target_pct=25.0,
                    option_chain_sync=option_sync,
                )
                service = HistoricalDRIDecisionReplayService(policy)
                return service.run_day(instrument_key, trading_date)

            def on_progress(done, total, trading_date, stage):
                ratio = min(1.0, done / total) if total else 0.0
                progress.progress(
                    ratio,
                    text=(
                        f"Successful replay days {done}/{total} · "
                        f"{trading_date.isoformat()} · {stage}"
                    ),
                )
                status.caption(
                    f"Checking {trading_date.isoformat()} — {stage}"
                )

            window = run_latest_ready_dri_window(
                available_dates,
                end_date=end_date,
                requested_days=10,
                validate_day=validate_day,
                run_day=run_day,
                progress_callback=on_progress,
            )
            st.session_state[_SESSION_KEY] = {
                "instrument_key": instrument_key,
                "end_date": end_date,
                "window": window,
            }
            progress.progress(
                1.0 if window.complete else window.completed_days / 10.0,
                text=(
                    f"Validation complete: {window.completed_days}/10 successful days"
                ),
            )
            if window.complete:
                status.success("Ten replay-ready trading days were validated.")
            else:
                status.warning(
                    "Only "
                    f"{window.completed_days}/10 replay-ready days were available. "
                    "Promotion remains HOLD until ten successful days are collected."
                )
        except Exception as exc:
            st.exception(exc)

    state = st.session_state.get(_SESSION_KEY)
    if not state or state.get("instrument_key") != instrument_key:
        return
    window = state["window"]
    report = window.report

    status_text = "PROMOTE" if window.promotion_passed else "HOLD"
    if not window.complete:
        status_text = "HOLD — INCOMPLETE WINDOW"

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Validated Days", f"{window.completed_days}/10")
    m2.metric("Profitable Days", f"{report.profitable_day_pct:.1f}%")
    m3.metric("Total Net Points", f"{report.total_net_points:.2f}")
    m4.metric("Median Daily Points", f"{report.median_daily_points:.2f}")
    m5.metric("Profit Factor", _format_profit_factor(report.profit_factor))
    m6.metric("Decision", status_text)

    n1, n2, n3, n4, n5, n6 = st.columns(6)
    n1.metric("Average Winner", f"{report.average_winner:.2f}")
    n2.metric("Average Loss", f"{report.average_loss:.2f}")
    n3.metric("Max Losing Streak", report.maximum_losing_streak)
    n4.metric(
        "Consecutive Losing Days",
        report.maximum_consecutive_losing_days,
    )
    n5.metric("Max Daily Drawdown", f"{report.maximum_daily_drawdown:.2f}")
    n6.metric(
        "Profit Concentration",
        f"{report.single_day_profit_concentration_pct:.1f}%",
    )

    if window.promotion_passed:
        st.success(
            "All promotion criteria passed across a complete 10-day window. "
            "The next permitted milestone is live shadow intelligence, not automated execution."
        )
    elif window.complete:
        st.warning(
            "The 10-day window is complete, but one or more promotion criteria failed. "
            "Keep strategy-entry rules frozen and continue historical validation."
        )
    else:
        st.info(
            "This is a partial diagnostic result only. It cannot promote the strategy."
        )

    st.markdown("##### Daily Results")
    daily_rows = window.daily_rows()
    _st_dataframe_arrow_safe(daily_rows, width="stretch", hide_index=True)

    st.markdown("##### Promotion Criteria")
    promotion_rows = report.promotion_rows()
    _st_dataframe_arrow_safe(
        promotion_rows,
        width="stretch",
        hide_index=True,
    )

    st.markdown("##### Strategy Segment Performance")
    slice_rows = report.slice_rows()
    _st_dataframe_arrow_safe(slice_rows, width="stretch", hide_index=True)

    with st.expander("Replay-Date Readiness and Failure Trace", expanded=False):
        attempt_rows = window.attempt_rows()
        _st_dataframe_arrow_safe(
            attempt_rows,
            width="stretch",
            hide_index=True,
        )

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.download_button(
            "Download Daily CSV",
            data=pd.DataFrame(daily_rows).to_csv(index=False),
            file_name="historical_dri_10day_daily.csv",
            mime="text/csv",
            key="historical_dri_10day_daily_download",
        )
    with d2:
        st.download_button(
            "Download Promotion CSV",
            data=pd.DataFrame(promotion_rows).to_csv(index=False),
            file_name="historical_dri_10day_promotion.csv",
            mime="text/csv",
            key="historical_dri_10day_promotion_download",
        )
    with d3:
        st.download_button(
            "Download Segments CSV",
            data=pd.DataFrame(slice_rows).to_csv(index=False),
            file_name="historical_dri_10day_segments.csv",
            mime="text/csv",
            key="historical_dri_10day_segments_download",
        )
    with d4:
        st.download_button(
            "Download Readiness CSV",
            data=pd.DataFrame(window.attempt_rows()).to_csv(index=False),
            file_name="historical_dri_10day_readiness.csv",
            mime="text/csv",
            key="historical_dri_10day_readiness_download",
        )


def _format_profit_factor(value: float | None) -> str:
    if value is None:
        return "—"
    if value == float("inf"):
        return "∞"
    return f"{value:.2f}"
