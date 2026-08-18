from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

import red_bar_lab.ui.pages.paper_architecture_reconciliation_v3 as previous
from red_bar_lab.execution.background_architecture_orchestrator import (
    current_background_architecture_status,
    ensure_background_architecture_orchestrator,
)
from red_bar_lab.execution.shadow_evaluation_journal import (
    read_evaluation_cycles,
    summarize_evaluation_cycles,
)


IST = ZoneInfo("Asia/Kolkata")
SECTION_10_STAGES = previous.SECTION_10_STAGES
build_reconciliation_snapshot = previous.build_reconciliation_snapshot


def _render_background_evidence(settings) -> None:
    trading_date = datetime.now(IST).date().isoformat()
    rows = read_evaluation_cycles(
        settings.runs_root,
        limit=1000,
        trading_date=trading_date,
    )
    summary = summarize_evaluation_cycles(rows)
    status = current_background_architecture_status()

    st.markdown("### Background Architecture Runtime — Sections 1–10E")
    st.caption(
        "Durable, restart-safe evidence produced from the shared Upstox candle cache, "
        "stored option-chain context, strategy-owned Sections 1–3, and the headless "
        "Sections 4–10E shadow path. No execution authority is attached."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Runner", "RUNNING" if status.get("running") else "STOPPED")
    c2.metric("Cycles today", int(summary.get("cycle_count") or 0))
    c3.metric("Healthy at 9E", int(summary.get("healthy_candidate_count") or 0))
    c4.metric("Shadow routed", int(summary.get("shadow_routed_count") or 0))
    c5.metric("Execution", "DISABLED")

    st.write(
        {
            "Instrument": status.get("instrument_key"),
            "Interval seconds": status.get("interval_seconds"),
            "Last cycle": status.get("last_cycle_at"),
            "Last runner error": status.get("last_error"),
            "Latest durable record": summary.get("latest_recorded_at"),
            "Journal version": summary.get("journal_version"),
        }
    )

    if not rows:
        st.warning(
            "The background runner has not written a cycle for today yet. Leave the app "
            "running for at least one interval and refresh this page."
        )
        return

    latest_by_strategy: dict[str, dict[str, object]] = {}
    for row in rows:
        strategy = str(row.get("strategy_id") or "UNKNOWN")
        latest_by_strategy.setdefault(strategy, dict(row))

    st.markdown("#### Latest section outcome by strategy")
    st.dataframe(
        [
            {
                "Strategy": row.get("strategy_id"),
                "Started": row.get("started_at"),
                "Completed": row.get("completed_at"),
                "Candles": row.get("prepared_candle_count"),
                "Signal": row.get("signal_id"),
                "Bundle": row.get("bundle_id"),
                "S1": row.get("section_1_outcome"),
                "S2": row.get("section_2_outcome"),
                "S3": row.get("section_3_outcome"),
                "S4": row.get("section_4_outcome"),
                "S5": row.get("section_5_outcome"),
                "S6": row.get("section_6_outcome"),
                "S7": row.get("section_7_outcome"),
                "S8": row.get("section_8_outcome"),
                "S9": row.get("section_9_outcome"),
                "10D": row.get("section_10d_outcome"),
                "10E": row.get("section_10e_outcome"),
                "Stopped At": row.get("terminal_section"),
                "Reason": row.get("terminal_reason"),
            }
            for row in latest_by_strategy.values()
        ],
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Durable cycle history")
    st.dataframe(
        [
            {
                "Recorded": row.get("recorded_at"),
                "Strategy": row.get("strategy_id"),
                "Signal": row.get("signal_id"),
                "Candidates": row.get("candidate_count"),
                "Evidence": row.get("shadow_evidence_captured"),
                "Routes": row.get("shadow_route_count"),
                "Terminal Section": row.get("terminal_section"),
                "Terminal Reason": row.get("terminal_reason"),
            }
            for row in rows[:300]
        ],
        width="stretch",
        hide_index=True,
    )
    st.info(
        "Interpretation: a strategy can be evaluated successfully even when no trade is "
        "healthy. The terminal section and reason show exactly where the cycle stopped."
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
    ensure_background_architecture_orchestrator(
        settings=settings,
        layout=layout,
        database=database,
        instrument_key=str(instrument_key),
    )
    _render_background_evidence(settings)
    previous.render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    )


__all__ = [
    "SECTION_10_STAGES",
    "build_reconciliation_snapshot",
    "render_page",
]
