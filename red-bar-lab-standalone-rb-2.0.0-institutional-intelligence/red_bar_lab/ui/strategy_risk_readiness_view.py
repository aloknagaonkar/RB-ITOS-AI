from __future__ import annotations

import json
from typing import Mapping

import streamlit as st


def _display_value(value: object) -> object:
    """Return an Arrow-safe display value without changing the underlying context."""
    if isinstance(value, (list, tuple, set, Mapping)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)
    return value


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
    st.write(f"**Account-context status:** {result.get('account_context_status') or 'UNAVAILABLE'}")
    st.write(f"**Account-context adapter:** {result.get('account_context_source_version') or 'UNAVAILABLE'}")
    st.write(f"**Context evaluated at:** {result.get('account_context_evaluated_at') or 'UNAVAILABLE'}")
    st.write("**Policy action:** OBSERVE_ONLY — no persistence, reservation, bundle consumption or order submission")

    provenance = result.get("account_context_provenance")
    if isinstance(provenance, Mapping) and provenance:
        with st.expander("Where did the account and risk values come from?"):
            st.dataframe(
                [
                    {
                        "field": field,
                        "value": _display_value(
                            details.get("value") if isinstance(details, Mapping) else None
                        ),
                        "source": details.get("source") if isinstance(details, Mapping) else "UNAVAILABLE",
                        "authoritative": details.get("authoritative") if isinstance(details, Mapping) else False,
                        "evaluated_at": details.get("evaluated_at") if isinstance(details, Mapping) else None,
                    }
                    for field, details in provenance.items()
                ],
                width="stretch",
                hide_index=True,
            )

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
