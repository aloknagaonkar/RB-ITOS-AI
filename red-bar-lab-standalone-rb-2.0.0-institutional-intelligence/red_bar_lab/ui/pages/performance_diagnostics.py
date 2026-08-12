from red_bar_lab.ui._shared import *
from red_bar_lab.services.performance_diagnostics import build_performance_gate_trace


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Performance Hard Block Trace")
    st.caption("Read-only decomposition of Performance Selection and operational duplicate blocking. No trading rule is changed.")
    selected_date = st.date_input("Trading date", value=date.today(), key="performance_trace_date")
    rows = database.read_trade_selection_evaluations(trading_date=selected_date.isoformat(), limit=500)
    if not rows:
        st.info("No Trade Selection evaluations are stored for this date yet.")
        return
    ordered = sorted(rows, key=lambda row: str(row.get("evaluated_at") or ""), reverse=True)
    options = {}
    for index, row in enumerate(ordered):
        label = f"Rank #{row.get('candidate_rank')} · {row.get('candidate_symbol')} · {row.get('decision')} · {row.get('evaluated_at')}"
        options[f"{label} · {index + 1}"] = row
    selection = options[st.selectbox("Inspect Performance evaluation", list(options.keys()), key="performance_trace_candidate")]
    lifecycles = database.read_candidate_lifecycle(signal_id=str(selection.get("signal_id") or ""), limit=200)
    lifecycle = next((x for x in lifecycles if str(x.get("candidate_symbol") or "") == str(selection.get("candidate_symbol") or "")), None)
    trace = build_performance_gate_trace(selection, lifecycle)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Decision", str(trace.get("decision") or "—"))
    c2.metric("Candidate Score", f"{float(trace.get('candidate_score') or 0):.2f}")
    c3.metric("Opportunity Score", f"{float(trace.get('opportunity_score') or 0):.2f}")
    c4.metric("TSS", f"{float(trace.get('selection_score') or 0):.2f}")
    c5.metric("Duplicate", "YES" if trace.get("duplicate") else "NO")

    blockers = trace.get("blockers") or []
    if blockers:
        st.error("Performance / operational block caused by: " + ", ".join(str(x) for x in blockers))
    else:
        st.success("No reconstructed Performance or duplicate hard blocker is present.")

    st.markdown("#### Performance Selection Gates")
    st.dataframe(_arrow_safe_rows(trace.get("gates") or []), width="stretch", hide_index=True)
    st.markdown("#### Persisted Selection Reason")
    st.code(str(trace.get("reason") or "—"), language=None)
    st.markdown("#### Candidate Lifecycle")
    st.dataframe(_arrow_safe_rows([{
        "state": trace.get("lifecycle_state"),
        "reason": trace.get("lifecycle_reason"),
        "duplicate": trace.get("duplicate"),
        "execution_quality_score": trace.get("execution_quality_score"),
    }]), width="stretch", hide_index=True)
    st.caption("In the current engine, only zero spread score and zero liquidity score are Performance hard blockers. Candidate score, Opportunity extension gate, TSS, and historical reference levels are soft evidence. Duplicate protection is applied later by automation and forces selection eligibility false for the same signal + account + contract.")
