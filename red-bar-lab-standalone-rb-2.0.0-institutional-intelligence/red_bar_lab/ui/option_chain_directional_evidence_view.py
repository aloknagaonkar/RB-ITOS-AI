from __future__ import annotations

from typing import Mapping

import streamlit as st


def render_option_chain_directional_evidence_5e(result: Mapping[str, object]) -> None:
    st.markdown("##### Supporting Option-Chain Directional Evidence")
    st.caption(
        "Supporting read-only evidence attached to Section 5E from the exact Section 5A "
        "snapshot and nearest earlier ONLINE snapshot. It does not create another numbered "
        "stage and does not change strategy direction, selected contracts, or admission."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("OI direction", str(result.get("direction") or "UNAVAILABLE"))
    c2.metric("Confidence", str(result.get("confidence") or "NONE"))
    c3.metric("Bullish score", f"{float(result.get('bullish_score') or 0.0):.1%}")
    c4.metric("Bearish score", f"{float(result.get('bearish_score') or 0.0):.1%}")
    st.write(f"**Previous snapshot:** {result.get('previous_snapshot_timestamp')}")
    st.write(f"**Current snapshot:** {result.get('current_snapshot_timestamp')}")
    st.write(f"**Comparison interval:** {result.get('comparison_seconds')} seconds")
    st.write(f"**ATM / strikes evaluated:** {result.get('atm_strike')} / {result.get('strikes_evaluated')}")
    st.write(f"**Dominant evidence:** {result.get('dominant_reason')}")
    st.write("**Policy action:** OBSERVE_ONLY — supporting evidence only")
    rows = list(result.get("rows") or [])
    with st.expander("View strike-level Call/Put OI evidence"):
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No comparable strike-level OI evidence is available.")
