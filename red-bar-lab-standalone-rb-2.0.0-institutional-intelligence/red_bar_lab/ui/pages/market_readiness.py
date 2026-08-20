import sqlite3

from red_bar_lab.ui._shared import *
from red_bar_lab.services.global_readiness_store import read_global_readiness_snapshots
from red_bar_lab.services.global_readiness_validation import (
    build_global_readiness_shadow_report,
    replay_global_readiness,
)
from red_bar_lab.services.independent_market_recommendation import (
    build_independent_market_recommendation,
)
from red_bar_lab.services.nifty_futures_snapshot_store import read_nifty_futures_snapshots
from red_bar_lab.services.trade_evidence import build_trade_evidence_recommendation


def _display_score(value):
    return "—" if value is None else f"{value:.1f}"


def _display_number(value, digits=3):
    return "—" if value is None else f"{float(value):.{digits}f}"


def _latest_option_context(database_path):
    """Read persisted option evidence only; never call a market-data provider."""
    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_context_snapshots'"
            ).fetchone()
            if not table:
                return {}
            row = connection.execute(
                """
                SELECT entry_timestamp, option_expiry, option_spot_price, atm_strike,
                       pcr_oi, atm_call_delta, atm_put_delta, atm_call_iv, atm_put_iv
                FROM option_context_snapshots
                ORDER BY julianday(entry_timestamp) DESC, entry_timestamp DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else {}
    except sqlite3.Error:
        return {}


def _evidence_table(recommendation):
    return [
        {"Category": "Positive", "Evidence": ", ".join(recommendation.positive_evidence) or "NONE"},
        {"Category": "Caution", "Evidence": ", ".join(recommendation.caution_evidence) or "NONE"},
        {"Category": "Blocking", "Evidence": ", ".join(recommendation.blocking_evidence) or "NONE"},
    ]


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Trade Evidence & Market Readiness")
    st.caption(
        "Two separate read-only views: an independent market recommendation driven by "
        "futures/readiness evidence, and a Red Bar V2 recommendation for comparison. "
        "Neither view has execution authority."
    )

    rows = read_global_readiness_snapshots(
        settings.database_path,
        underlying_name=underlying_name,
        limit=500,
    )
    if not rows:
        st.warning("No global readiness snapshots are available yet. Run the paper monitor once.")
        return

    latest = rows[0]
    diagnostics = database.read_paper_signal_diagnostics(limit=1)
    latest_signal = diagnostics[0] if diagnostics else {}
    futures_rows = read_nifty_futures_snapshots(
        settings.database_path,
        underlying_name=underlying_name,
        limit=1,
    )
    latest_futures = futures_rows[0] if futures_rows else {}
    option_context = _latest_option_context(settings.database_path)

    independent = build_independent_market_recommendation(
        readiness=latest,
        futures_snapshot=latest_futures,
        option_context=option_context,
    )
    v2_recommendation = build_trade_evidence_recommendation(
        readiness=latest,
        signal_diagnostic=latest_signal,
        futures_snapshot=latest_futures,
    )

    st.markdown("### A. Independent Market Recommendation")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Independent direction", independent.direction)
    i2.metric("Suggested trade", f"BUY {independent.suggested_option}" if independent.suggested_option != "—" else "WAIT")
    i3.metric("Evidence grade", independent.grade)
    i4.metric("Suggested action", independent.action)

    independent_rows = [{
        "Futures state": independent.futures_state,
        "Futures strength": independent.futures_strength,
        "Suggested side": independent.suggested_option,
        "ATM strike": option_context.get("atm_strike") or "—",
        "Expiry": option_context.get("option_expiry") or "—",
        "Option delta": _display_number(independent.option_delta),
        "Delta source": independent.delta_source,
        "PCR OI": _display_number(independent.pcr_oi),
        "Call IV": _display_number(option_context.get("atm_call_iv"), 2),
        "Put IV": _display_number(option_context.get("atm_put_iv"), 2),
        "Global readiness": latest.get("overall_status") or "—",
        "Authority": independent.authority,
    }]
    st.dataframe(_arrow_safe_rows(independent_rows), width="stretch", hide_index=True)
    st.info(independent.summary)
    st.dataframe(_arrow_safe_rows(_evidence_table(independent)), width="stretch", hide_index=True)
    st.caption(
        "Direction comes from NIFTY futures positioning, not Red Bar V2. Delta is the exact "
        "candidate delta when persisted; otherwise it is the latest ATM delta for the suggested side."
    )

    st.markdown("### B. Red Bar V2 Recommendation")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Red Bar direction", v2_recommendation.direction)
    r2.metric("Suggested option", v2_recommendation.suggested_option)
    r3.metric("Evidence grade", v2_recommendation.grade)
    r4.metric("Suggested action", v2_recommendation.action)

    v2_rows = [{
        "Signal time": latest_signal.get("confirmation_timestamp") or latest_signal.get("timestamp") or "—",
        "Suggested contract": v2_recommendation.suggested_contract,
        "Candidate score": _display_score(v2_recommendation.candidate_score),
        "Suggested-side ATM delta": _display_number(
            option_context.get("atm_call_delta") if v2_recommendation.suggested_option == "CE"
            else option_context.get("atm_put_delta") if v2_recommendation.suggested_option == "PE"
            else None
        ),
        "Futures state": latest_futures.get("positioning_state") or "—",
        "Futures strength": latest_futures.get("strength") or latest.get("futures_strength") or "—",
        "Global readiness": latest.get("overall_status") or "—",
        "Authority": v2_recommendation.authority,
    }]
    st.dataframe(_arrow_safe_rows(v2_rows), width="stretch", hide_index=True)
    st.info(v2_recommendation.summary)
    st.dataframe(_arrow_safe_rows(_evidence_table(v2_recommendation)), width="stretch", hide_index=True)

    independent_side = independent.suggested_option
    v2_side = v2_recommendation.suggested_option
    if independent_side in {"CE", "PE"} and v2_side in {"CE", "PE"}:
        alignment = "CONFIRMED" if independent_side == v2_side else "CONFLICTED"
    else:
        alignment = "NOT_COMPARABLE"
    st.markdown("### C. Recommendation Alignment")
    a1, a2, a3 = st.columns(3)
    a1.metric("Independent view", independent_side)
    a2.metric("Red Bar V2 view", v2_side)
    a3.metric("Alignment", alignment)
    if alignment == "CONFLICTED":
        st.warning("Independent futures/readiness evidence and Red Bar V2 suggest opposite option sides. Wait for confirmation.")
    elif alignment == "CONFIRMED":
        st.success("Independent market evidence and Red Bar V2 suggest the same option side.")
    else:
        st.info("One of the two views has no actionable direction yet.")

    st.markdown("### Market Readiness Detail")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall readiness", latest.get("overall_status") or "—")
    c2.metric("Data readiness", "BLOCKED" if latest.get("blocking_reasons") else "USABLE")
    c3.metric("Execution readiness", "LIMITED" if latest.get("execution_reasons") else "READY")
    c4.metric("Market hours", latest.get("market_hours_status") or "—")

    st.markdown("#### Component readiness")
    component_fields = (
        "underlying_status", "option_chain_status", "option_quote_status", "pcr_status",
        "futures_status", "futures_strength", "v2_alignment_status",
        "execution_source_status", "market_hours_status",
    )
    component_rows = [{"Component": field.replace("_", " ").title(), "Status": latest.get(field)} for field in component_fields]
    st.dataframe(_arrow_safe_rows(component_rows), width="stretch", hide_index=True)

    st.markdown("#### Reasons")
    reason_rows = [
        {"Category": "Blocking", "Reasons": ", ".join(latest.get("blocking_reasons") or ()) or "NONE"},
        {"Category": "Advisory", "Reasons": ", ".join(latest.get("advisory_reasons") or ()) or "NONE"},
        {"Category": "Execution", "Reasons": ", ".join(latest.get("execution_reasons") or ()) or "NONE"},
    ]
    st.dataframe(_arrow_safe_rows(reason_rows), width="stretch", hide_index=True)

    shadow = build_global_readiness_shadow_report(rows)
    st.markdown("#### Shadow validation")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Observations", shadow.observations)
    s2.metric("READY rate", f"{shadow.ready_rate_pct:.1f}%")
    s3.metric("Signals seen / scored", f"{shadow.signals_seen} / {shadow.signals_scored}")
    s4.metric("Opened / skipped", f"{shadow.orders_opened} / {shadow.orders_skipped}")
    st.caption(f"Execution impact: {shadow.execution_impact}")

    replay = replay_global_readiness(rows)
    st.markdown("#### Historical readiness replay")
    st.dataframe(
        _arrow_safe_rows([{
            "Observations": replay.observations,
            "READY": replay.status_counts.get("READY", 0),
            "DEGRADED": replay.status_counts.get("DEGRADED", 0),
            "BLOCKED": replay.status_counts.get("BLOCKED", 0),
            "UNAVAILABLE": replay.status_counts.get("UNAVAILABLE", 0),
            "Execution impact": replay.execution_impact,
        }]),
        width="stretch",
        hide_index=True,
    )
    if replay.blocking_reason_counts:
        st.markdown("##### Most common blocking reasons")
        st.dataframe(_arrow_safe_rows([{"Reason": key, "Count": value} for key, value in replay.blocking_reason_counts.items()]), width="stretch", hide_index=True)
    if replay.advisory_reason_counts:
        st.markdown("##### Most common advisory reasons")
        st.dataframe(_arrow_safe_rows([{"Reason": key, "Count": value} for key, value in replay.advisory_reason_counts.items()]), width="stretch", hide_index=True)

    st.markdown("#### Latest snapshot")
    st.dataframe(_arrow_safe_rows([latest]), width="stretch", hide_index=True)

    st.markdown("#### Recent history")
    columns = (
        "observed_at", "overall_status", "underlying_status", "option_chain_status",
        "option_quote_status", "pcr_status", "futures_status", "futures_strength",
        "v2_alignment_status", "execution_source_status", "market_hours_status",
        "signals_seen", "signals_scored", "orders_opened", "orders_skipped", "authority",
    )
    st.dataframe(_arrow_safe_rows([{key: row.get(key) for key in columns} for row in rows]), width="stretch", hide_index=True)
