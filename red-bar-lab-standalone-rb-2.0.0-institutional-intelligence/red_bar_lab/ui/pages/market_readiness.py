from red_bar_lab.ui._shared import *
from red_bar_lab.services.global_readiness_store import read_global_readiness_snapshots
from red_bar_lab.services.global_readiness_validation import (
    build_global_readiness_shadow_report,
    replay_global_readiness,
)
from red_bar_lab.services.nifty_futures_snapshot_store import read_nifty_futures_snapshots
from red_bar_lab.services.trade_evidence import build_trade_evidence_recommendation


def _display_score(value):
    return "—" if value is None else f"{value:.1f}"


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Trade Evidence & Market Readiness")
    st.caption(
        "Read-only Red Bar V2 trade suggestion, market-data quality, futures confirmation "
        "and execution-policy evidence. This page never opens, blocks or modifies a trade."
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
    recommendation = build_trade_evidence_recommendation(
        readiness=latest,
        signal_diagnostic=latest_signal,
        futures_snapshot=latest_futures,
    )

    st.markdown("### Trade Evidence Recommendation")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Red Bar direction", recommendation.direction)
    r2.metric("Suggested option", recommendation.suggested_option)
    r3.metric("Evidence grade", recommendation.grade)
    r4.metric("Suggested action", recommendation.action)

    candidate_rows = [{
        "Signal time": latest_signal.get("confirmation_timestamp") or latest_signal.get("timestamp") or "—",
        "Suggested contract": recommendation.suggested_contract,
        "Candidate score": _display_score(recommendation.candidate_score),
        "Futures state": latest_futures.get("positioning_state") or "—",
        "Futures strength": latest_futures.get("strength") or latest.get("futures_strength") or "—",
        "Global readiness": latest.get("overall_status") or "—",
        "Authority": recommendation.authority,
    }]
    st.dataframe(_arrow_safe_rows(candidate_rows), width="stretch", hide_index=True)
    st.info(recommendation.summary)

    evidence_rows = [
        {
            "Category": "Positive",
            "Evidence": ", ".join(recommendation.positive_evidence) or "NONE",
        },
        {
            "Category": "Caution",
            "Evidence": ", ".join(recommendation.caution_evidence) or "NONE",
        },
        {
            "Category": "Blocking",
            "Evidence": ", ".join(recommendation.blocking_evidence) or "NONE",
        },
    ]
    st.dataframe(_arrow_safe_rows(evidence_rows), width="stretch", hide_index=True)
    st.caption(
        "Suggested CE/PE and evidence grade are observational only. Red Bar V2 remains "
        "the paper signal authority, and the existing execution engine remains unchanged."
    )

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
