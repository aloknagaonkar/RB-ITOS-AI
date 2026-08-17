from __future__ import annotations

from typing import Mapping

import streamlit as st


def render_risk_readiness_8a(result: Mapping[str, object]) -> None:
    st.markdown("### 8. Account, Risk and Execution Approval")
    st.markdown("#### 8A. Account and Risk Readiness")
    st.caption(
        "Consumes only Section 7 forward-eligible candidates. This remains a read-only "
        "affordability, exposure and loss-limit evaluation."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Risk ready", int(result.get("risk_ready_count") or 0))
    c3.metric("Waiting", int(result.get("waiting_count") or 0))
    c4.metric("Blocked", int(result.get("blocked_count") or 0))
    st.write(f"**Risk policy:** {result.get('policy_version')}")
    st.write(f"**Risk context available:** {'YES' if result.get('risk_context_available') else 'NO'}")
    st.write("**Policy action:** OBSERVE_ONLY — no persistence, reservation, bundle consumption or order submission")

    rows = list(result.get("rows") or [])
    if not rows:
        st.info("No Section 7 forward-eligible candidate is available for account/risk evaluation.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "candidate_id", "strategy_id", "bundle_id", "role", "contract_side",
            "trading_symbol", "lot_size", "proposed_lots", "ltp", "required_premium",
            "available_cash", "projected_portfolio_exposure", "risk_outcome", "exact_reason"
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"Why is {row.get('candidate_id')} risk-ready, waiting, or blocked?"):
            st.dataframe(list(row.get("checks") or []), width="stretch", hide_index=True)
            st.write(f"**Outcome:** {row.get('risk_outcome')}")
            st.write(f"**Exact reason:** {row.get('exact_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
