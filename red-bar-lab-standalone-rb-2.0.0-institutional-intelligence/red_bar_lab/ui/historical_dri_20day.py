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
from red_bar_lab.services.historical_dri_outcome_reconciliation import (
    reconcile_historical_dri_outcomes,
)
from red_bar_lab.services.historical_dri_research_readiness import (
    HistoricalDRIResearchReadinessService,
)
from red_bar_lab.ui._shared import (
    HistoricalOptionChainSyncService,
    RedBarHistoricalService,
    RedBarUpstoxService,
    _st_dataframe_arrow_safe,
)

_SESSION_KEY = "historical_dri_20day_validation_v1"


def build_20day_validation_wrapper(original_render, research_lab_module):
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
        _render(
            layout=layout,
            database=database,
            token=token,
            instrument_key=instrument_key,
            research_lab_module=research_lab_module,
        )

    return wrapped


def _render(*, layout, database, token, instrument_key, research_lab_module):
    st.markdown("---")
    st.markdown("#### 20-Day DRI Rolling Validation & Exit Reconciliation")
    st.caption(
        "Extends the frozen DRI strategy to twenty research-qualified trading days "
        "and reconciles headline outcomes against baseline, fixed trailing and "
        "adaptive trailing exits on the same executed trade set. No strategy rules "
        "or live execution settings are changed."
    )

    try:
        reader = RedBarHistoricalService(RedBarUpstoxService("cache-only"), layout)
        available_dates = reader.available_dates(instrument_key, interval_minutes=1)
    except Exception as exc:
        st.warning(f"Unable to read cached replay dates: {type(exc).__name__}: {exc}")
        return

    if not available_dates:
        st.info("No cached one-minute replay dates are available.")
        return

    end_date = st.selectbox(
        "20-Day Validation End Date",
        available_dates,
        index=len(available_dates) - 1,
        format_func=lambda value: value.isoformat(),
        key="historical_dri_20day_end_date",
    )

    if st.button(
        "Run 20-Day DRI Validation",
        type="primary",
        key="historical_dri_20day_run",
    ):
        progress = st.progress(0.0, text="Preparing 20-day validation...")
        status = st.empty()
        try:
            base_sync = HistoricalOptionChainSyncService(
                RedBarUpstoxService(token or "cache-only"),
                layout,
                reader,
                database=database,
            )
            research_sync = HistoricalDRIResearchReadinessService(
                base_sync,
                reader,
            )

            def validate_day(trading_date):
                return research_sync.validate_day(instrument_key, trading_date)

            def run_day(trading_date):
                policy = research_lab_module.HistoricalDecisionReplayService(
                    reader,
                    freshness_seconds=180,
                    hard_expiry_seconds=900,
                    minimum_confidence_pct=70.0,
                    stop_loss_pct=15.0,
                    target_pct=25.0,
                    option_chain_sync=research_sync,
                )
                return HistoricalDRIDecisionReplayService(policy).run_day(
                    instrument_key,
                    trading_date,
                )

            def on_progress(done, total, trading_date, stage):
                ratio = min(1.0, done / total) if total else 0.0
                progress.progress(
                    ratio,
                    text=(
                        f"Successful replay days {done}/{total} · "
                        f"{trading_date.isoformat()} · {stage}"
                    ),
                )
                status.caption(f"Checking {trading_date.isoformat()} — {stage}")

            window = run_latest_ready_dri_window(
                available_dates,
                end_date=end_date,
                requested_days=20,
                validate_day=validate_day,
                run_day=run_day,
                progress_callback=on_progress,
            )
            reconciliation = reconcile_historical_dri_outcomes(
                window.replay_results
            )
            st.session_state[_SESSION_KEY] = {
                "instrument_key": instrument_key,
                "end_date": end_date,
                "window": window,
                "reconciliation": reconciliation,
            }
            progress.progress(
                1.0 if window.complete else window.completed_days / 20.0,
                text=(
                    f"Validation complete: {window.completed_days}/20 successful days"
                ),
            )
            if window.complete:
                status.success("Twenty research-qualified days were validated.")
            else:
                status.warning(
                    f"Only {window.completed_days}/20 qualified days were available. "
                    "Results remain diagnostic and cannot promote the strategy."
                )
        except Exception as exc:
            st.exception(exc)

    state = st.session_state.get(_SESSION_KEY)
    if not state or state.get("instrument_key") != instrument_key:
        return

    window = state["window"]
    report = window.report
    reconciliation = state["reconciliation"]
    decision = "PROMOTE TO LIVE SHADOW" if window.promotion_passed else "HOLD"
    if not window.complete:
        decision = "HOLD — INCOMPLETE WINDOW"

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Validated Days", f"{window.completed_days}/20")
    m2.metric("Profitable Days", f"{report.profitable_day_pct:.1f}%")
    m3.metric("Total Net Points", f"{report.total_net_points:.2f}")
    m4.metric("Median Daily Points", f"{report.median_daily_points:.2f}")
    m5.metric("Profit Factor", _pf(report.profit_factor))
    m6.metric("Decision", decision)

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Max Daily Drawdown", f"{report.maximum_daily_drawdown:.2f}")
    n2.metric("Profit Concentration", f"{report.single_day_profit_concentration_pct:.1f}%")
    n3.metric("Max Losing Streak", report.maximum_losing_streak)
    n4.metric("Consecutive Losing Days", report.maximum_consecutive_losing_days)

    st.markdown("##### Exit Outcome Reconciliation")
    st.caption(
        "These totals intentionally use different stored exit bases. A delta is not "
        "automatically a defect; the detailed table identifies the exact basis and "
        "missing fields for every executed trade."
    )
    reconciliation_summary = reconciliation.summary_rows()
    _st_dataframe_arrow_safe(
        reconciliation_summary,
        width="stretch",
        hide_index=True,
    )

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Executed Trades", reconciliation.executed_trades)
    r2.metric(
        "Headline vs Baseline",
        f"{reconciliation.headline_vs_baseline_delta:.2f}",
    )
    r3.metric(
        "Headline vs Fixed",
        f"{reconciliation.headline_vs_fixed_delta:.2f}",
    )
    r4.metric(
        "Headline vs Adaptive",
        f"{reconciliation.headline_vs_adaptive_delta:.2f}",
    )

    with st.expander("Per-Trade Exit Reconciliation", expanded=False):
        _st_dataframe_arrow_safe(
            list(reconciliation.rows),
            width="stretch",
            hide_index=True,
        )

    st.markdown("##### 20-Day Daily Results")
    daily_rows = window.daily_rows()
    _st_dataframe_arrow_safe(daily_rows, width="stretch", hide_index=True)

    st.markdown("##### Promotion Criteria")
    promotion_rows = report.promotion_rows()
    _st_dataframe_arrow_safe(
        promotion_rows,
        width="stretch",
        hide_index=True,
    )

    with st.expander("20-Day Readiness Trace", expanded=False):
        _st_dataframe_arrow_safe(
            window.attempt_rows(),
            width="stretch",
            hide_index=True,
        )

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            "Download 20-Day Daily CSV",
            data=pd.DataFrame(daily_rows).to_csv(index=False),
            file_name="historical_dri_20day_daily.csv",
            mime="text/csv",
            key="historical_dri_20day_daily_download",
        )
    with d2:
        st.download_button(
            "Download Reconciliation CSV",
            data=pd.DataFrame(reconciliation.rows).to_csv(index=False),
            file_name="historical_dri_exit_reconciliation.csv",
            mime="text/csv",
            key="historical_dri_reconciliation_download",
        )
    with d3:
        st.download_button(
            "Download 20-Day Readiness CSV",
            data=pd.DataFrame(window.attempt_rows()).to_csv(index=False),
            file_name="historical_dri_20day_readiness.csv",
            mime="text/csv",
            key="historical_dri_20day_readiness_download",
        )


def _pf(value: float | None) -> str:
    if value is None:
        return "—"
    if value == float("inf"):
        return "∞"
    return f"{value:.2f}"
