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


def _display_time(value) -> str:
    if value in (None, "", "Unavailable"):
        return "Unavailable"
    try:
        timestamp = datetime.fromisoformat(str(value))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        return timestamp.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")
    except (TypeError, ValueError):
        return str(value)


def _render_background_evidence(settings) -> None:
    trading_date = datetime.now(IST).date().isoformat()
    rows = read_evaluation_cycles(settings.runs_root, limit=1000, trading_date=trading_date)
    summary = summarize_evaluation_cycles(rows)
    status = current_background_architecture_status()

    st.markdown("### Background Architecture Runtime — Sections 1–10E")
    st.caption(
        "Durable, restart-safe evidence from the shared Upstox candle cache and stored "
        "option-chain context. The first authoritative blocking section is reported; "
        "later read-only audit placeholders never replace the root blocker."
    )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Runner", "RUNNING" if status.get("running") else "STOPPED")
    c2.metric("Orchestrator runs", int(summary.get("orchestration_run_count") or 0))
    c3.metric("Strategy evaluations", int(summary.get("strategy_evaluation_count") or 0))
    c4.metric("Healthy at 9E", int(summary.get("healthy_candidate_count") or 0))
    c5.metric("Shadow routed", int(summary.get("shadow_routed_count") or 0))
    c6.metric("Execution", "DISABLED")

    st.dataframe(
        [
            {"Runtime detail": "Instrument", "Value": status.get("instrument_key") or "Unavailable"},
            {"Runtime detail": "Evaluation interval", "Value": f"{status.get('interval_seconds') or 0} seconds"},
            {"Runtime detail": "Last completed cycle", "Value": _display_time(status.get("last_cycle_at"))},
            {"Runtime detail": "Last runner error", "Value": status.get("last_error") or "None"},
            {"Runtime detail": "Latest durable record", "Value": _display_time(summary.get("latest_recorded_at"))},
            {"Runtime detail": "Journal version", "Value": summary.get("journal_version")},
        ],
        width="stretch",
        hide_index=True,
    )

    if not rows:
        st.warning("No durable architecture evaluation exists for today yet. Wait one interval and refresh.")
        return

    latest_by_strategy: dict[str, dict[str, object]] = {}
    for row in rows:
        latest_by_strategy.setdefault(str(row.get("strategy_id") or "UNKNOWN"), dict(row))

    st.markdown("#### Latest outcome by strategy")
    st.dataframe(
        [
            {
                "Strategy": row.get("strategy_id"),
                "Completed": _display_time(row.get("completed_at")),
                "1m candles": row.get("prepared_candle_count"),
                "5m candles": row.get("five_minute_candle_count"),
                "Signal": row.get("signal_id"),
                "Bundle": row.get("bundle_id"),
                "S1": row.get("section_1_outcome"),
                "S2": row.get("section_2_outcome"),
                "S3": row.get("section_3_outcome"),
                "S4": row.get("section_4_outcome"),
                "5A Data": row.get("section_5a_outcome") or row.get("section_5_outcome"),
                "5B Market": row.get("section_5b_outcome") or "LEGACY_NOT_RECORDED",
                "5C Metadata": row.get("section_5c_outcome") or "LEGACY_NOT_RECORDED",
                "5D Safeguards": row.get("section_5d_outcome") or "LEGACY_NOT_RECORDED",
                "5E Ranking": row.get("section_5e_outcome") or row.get("section_5_outcome"),
                "S6": row.get("section_6_outcome"),
                "S7": row.get("section_7_outcome"),
                "S8": row.get("section_8_outcome"),
                "S9": row.get("section_9_outcome"),
                "10D": row.get("section_10d_outcome"),
                "10E": row.get("section_10e_outcome"),
                "First blocked at": row.get("terminal_section"),
                "Root reason": row.get("terminal_reason"),
            }
            for row in latest_by_strategy.values()
        ],
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Section 5 canonical sequence")
    st.dataframe(
        [
            {"Section": "5A", "Name": "Contract data readiness", "Purpose": "Time-safe snapshot and requested-side contract rows"},
            {"Section": "5B", "Name": "Point-in-time market context", "Purpose": "Spot and ATM from the exact 5A snapshot"},
            {"Section": "5C", "Name": "Execution metadata context", "Purpose": "Token, symbol, exchange, lot size and tick size"},
            {"Section": "5D", "Name": "Absolute contract safeguards", "Purpose": "Freshness, expiry, liquidity, spread and strike-distance checks"},
            {"Section": "5E", "Name": "Deterministic ranking", "Purpose": "Rank only contracts that passed 5D"},
        ],
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Durable cycle history")
    st.dataframe(
        [
            {
                "Recorded": _display_time(row.get("recorded_at")),
                "Run": row.get("orchestration_cycle_id") or "Legacy journal row",
                "Strategy": row.get("strategy_id"),
                "Signal": row.get("signal_id"),
                "Candidates": row.get("candidate_count"),
                "9E evidence": row.get("shadow_evidence_captured"),
                "10D routes": row.get("shadow_route_count"),
                "First blocked at": row.get("terminal_section"),
                "Root reason": row.get("terminal_reason"),
            }
            for row in rows[:300]
        ],
        width="stretch",
        hide_index=True,
    )
    st.info(
        "Old journal rows remain visible but may show LEGACY_NOT_RECORDED for 5B–5D. "
        "New cycles record every Section 5 sub-stage and the first real blocker."
    )


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    ensure_background_architecture_orchestrator(
        settings=settings, layout=layout, database=database, instrument_key=str(instrument_key)
    )
    _render_background_evidence(settings)
    previous.render_page(
        settings, layout, database, token, underlying_name, instrument_key, interval
    )


__all__ = ["SECTION_10_STAGES", "build_reconciliation_snapshot", "render_page"]
