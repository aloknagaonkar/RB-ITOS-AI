from __future__ import annotations

from datetime import date

import streamlit as st

from red_bar_lab.intelligence.institutional_sprint2 import InstitutionalSprint2Service


def render_institutional_sprint2_panel(database, instrument_key: str) -> None:
    """Render observation-only institutional intelligence. Never mutates execution state."""
    st.markdown("### Institutional Option Flow — Sprint 2")
    st.caption(
        "Observation only · Execution impact = NONE. Uses persisted ONLINE option-chain snapshots "
        "for OI behaviour, 1/5/15-minute OI and premium velocity, strike rotation, buying/selling "
        "strength and the advisory Institutional Confidence Index (ICI)."
    )
    intel = InstitutionalSprint2Service(database).latest(instrument_key, date.today().isoformat())
    if intel.status != "READY":
        st.info(f"Institutional Intelligence: {intel.reason}")
        return

    strength = intel.strength
    ici = intel.confidence
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Institutional Buying Strength", f"{strength.buying_strength_pct:.1f}%")
    c2.metric("Institutional Selling Strength", f"{strength.selling_strength_pct:.1f}%")
    c3.metric("Institutional Confidence Index", f"{ici.score:.1f}%")
    c4.metric("Institutional Bias", ici.direction)

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Market Conviction", strength.market_conviction)
    c6.metric("OI/Flow Breadth", f"{strength.breadth_pct:.1f}%")
    c7.metric("Strike Rotation", intel.rotation.state)
    c8.metric("Execution Impact", ici.execution_impact)

    st.caption(
        f"Snapshots used: {intel.snapshots_used} · Expiry: {intel.option_expiry or '—'} · "
        f"Data coverage: {ici.data_coverage_pct:.1f}% · ICI quality: {ici.quality}. {strength.reason}"
    )

    flow_rows = [row.as_dict() for row in intel.flow.rows]
    flow_rows.sort(key=lambda row: float(row.get("Confidence %") or 0.0), reverse=True)
    st.markdown("#### OI Behaviour / Buying-Writing")
    st.dataframe(flow_rows[:40], width="stretch", hide_index=True)

    velocity_by_key = {(r.strike, r.option_type): r for r in intel.oi_velocity}
    premium_by_key = {(r.strike, r.option_type): r for r in intel.premium_flow}
    combined = []
    for row in intel.flow.rows:
        key = (row.strike, row.option_type)
        velocity = velocity_by_key.get(key)
        premium = premium_by_key.get(key)
        combined.append({
            "Strike": row.strike,
            "Side": row.option_type,
            "Activity": row.activity,
            "Bias": row.directional_bias,
            "OI 1m %": getattr(velocity, "change_1m_pct", None),
            "OI 5m %": getattr(velocity, "change_5m_pct", None),
            "OI 15m %": getattr(velocity, "change_15m_pct", None),
            "OI State": getattr(velocity, "state", "UNKNOWN"),
            "Premium 1m %": getattr(premium, "change_1m_pct", None),
            "Premium 5m %": getattr(premium, "change_5m_pct", None),
            "Premium 15m %": getattr(premium, "change_15m_pct", None),
            "Premium Flow": getattr(premium, "state", "UNKNOWN"),
        })
    combined.sort(
        key=lambda row: abs(float(row.get("OI 5m %") or 0.0)) + abs(float(row.get("Premium 5m %") or 0.0)),
        reverse=True,
    )
    st.markdown("#### OI Velocity & Premium Flow")
    st.dataframe(combined[:40], width="stretch", hide_index=True)

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Call OI Center Shift", f"{intel.rotation.call_shift_points:+.1f}" if intel.rotation.call_shift_points is not None else "—")
    r2.metric("Put OI Center Shift", f"{intel.rotation.put_shift_points:+.1f}" if intel.rotation.put_shift_points is not None else "—")
    r3.metric("Rotation Confidence", f"{intel.rotation.confidence_pct:.1f}%")
    r4.metric("Net Institutional Strength", f"{strength.net_strength:+.1f}")

    with st.expander("Institutional Confidence Index Components", expanded=False):
        st.dataframe(
            [{"Component": key, "Score %": value} for key, value in ici.components.items()],
            width="stretch",
            hide_index=True,
        )
        st.caption("ICI is advisory and is not used by the Primary Decision Engine in Sprint 2.")
