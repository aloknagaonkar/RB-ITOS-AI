from red_bar_lab.ui._shared import *
from red_bar_lab.services.global_readiness_store import read_global_readiness_snapshots
from red_bar_lab.services.global_readiness_validation import (
    build_global_readiness_shadow_report,
    replay_global_readiness,
)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Market Readiness")
    st.caption(
        "Unified read-only market-data, execution-policy, Red Bar V2 alignment and "
        "market-hours observations. This page has no execution authority."
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
