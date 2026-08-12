from datetime import date

from red_bar_lab.ui._shared import *
from red_bar_lab.intelligence.previous_session_context import (
    PreviousSessionContextService,
    PreviousSessionHistoricalAdapter,
)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Previous Session Context")
    st.markdown(
        _decision_badge_html("SPRINT 3 · PREVIOUS SESSION CONTEXT · EXECUTION IMPACT = NONE", "shadow"),
        unsafe_allow_html=True,
    )
    st.caption(
        "Built only from the previous completed trading session. ONLINE snapshots are preferred; validated historical snapshots are an advisory fallback. "
        "Synthetic/mock/replay sources are not accepted. This page cannot change Primary, Committee, Portfolio, Queue, Exit or execution decisions."
    )

    trading_date = st.date_input("Trading date", value=date.today()).isoformat()

    readiness = PreviousSessionHistoricalAdapter(database, layout).ensure_previous_session(
        instrument_key, trading_date
    )
    st.markdown("### Previous Session Data Readiness")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Readiness", readiness.status)
    r2.metric("ONLINE Snapshots", readiness.online_snapshots)
    r3.metric("HISTORICAL Snapshots", readiness.historical_snapshots)
    r4.metric("Adapted Snapshots", readiness.adapted_snapshots)
    r5, r6 = st.columns(2)
    r5.metric("Historical Artifact Date", readiness.previous_artifact_date or "—")
    r6.metric("Artifact Contracts", readiness.artifact_contracts)
    if readiness.status in {"READY", "ADAPTED"}:
        st.success(readiness.detail)
    elif readiness.status == "ARTIFACTS_INCOMPLETE":
        st.warning(readiness.detail)
    else:
        st.info(readiness.detail)

    context = PreviousSessionContextService(database).latest_before(instrument_key, trading_date)
    if context.status == "WAITING":
        st.info(context.reason)
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Previous Session", context.previous_trading_date or "—")
    c2.metric("Data Source", context.data_source)
    c3.metric("Closing Bias", context.closing_bias)
    c4.metric("Carry-Forward Bias", context.carry_forward_bias)

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Carry Confidence", f"{context.carry_forward_confidence_pct:.1f}%")
    c6.metric("Buying Strength", f"{context.buying_strength_pct:.1f}%")
    c7.metric("Selling Strength", f"{context.selling_strength_pct:.1f}%")
    c8.metric("Closing Flow Score", f"{context.closing_flow_score:+.1f}")

    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Closing PCR", f"{context.closing_pcr:.2f}" if context.closing_pcr is not None else "—")
    c10.metric("Closing Max Pain", f"{context.closing_max_pain:.0f}" if context.closing_max_pain is not None else "—")
    c11.metric("Dominant Strike", f"{context.dominant_strike:.0f}" if context.dominant_strike is not None else "—")
    c12.metric("Dominant Side", context.dominant_side or "—")

    st.caption(f"Previous-session snapshots used: {context.snapshot_count} · Source provenance: {context.data_source} · Execution impact: {context.execution_impact}")
    if context.status == "PARTIAL":
        st.warning(context.reason)
    else:
        st.success(context.reason)

    st.markdown("### Opening Narrative")
    st.info(context.opening_narrative)
    st.markdown("### Carry-Forward Interpretation")
    rows = [
        {"Evidence": "Closing Strength", "Value": context.closing_bias, "Role": "Vote 1"},
        {"Evidence": "Closing PCR", "Value": context.closing_pcr, "Role": "Vote 2"},
        {"Evidence": "Dominant OI", "Value": f"{context.dominant_strike:.0f} {context.dominant_side}" if context.dominant_strike is not None else "—", "Role": "Vote 3"},
        {"Evidence": "Carry-Forward", "Value": context.carry_forward_bias, "Role": "Consensus"},
    ]
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    st.caption(
        "Sprint 3 is advisory only. Carry-forward bias is an opening expectation derived from previous-session closing strength, PCR and dominant OI side; execution impact remains NONE."
    )
