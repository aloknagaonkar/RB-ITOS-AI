from red_bar_lab.ui._shared import *
from red_bar_lab.intelligence.institutional_sprint2 import InstitutionalSprint2Service


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Institutional Intelligence")
    st.markdown(
        _decision_badge_html(
            "SHADOW / ADVISORY INTELLIGENCE · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Live option-chain intelligence built from persisted ONLINE snapshots. "
        "It measures buying/selling strength and institutional conviction but cannot "
        "change Primary, Committee, Portfolio, Queue or Exit decisions."
    )

    trading_date = date.today().isoformat()

    st.markdown("### Sprint 1 — OI Behaviour & Buying/Writing")
    try:
        flow = InstitutionalFlowService(database).latest(instrument_key, trading_date)
        if flow.status != "READY":
            st.info(f"Institutional Flow: {flow.reason}")
        else:
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Bullish Institutional Flow", f"{flow.bullish_flow_pct:.1f}%")
            a2.metric("Bearish Institutional Flow", f"{flow.bearish_flow_pct:.1f}%")
            a3.metric("Dominant Activity", flow.dominant_activity)
            a4.metric("Expiry", flow.option_expiry or "—")
            a5, a6, a7, a8 = st.columns(4)
            a5.metric("Strongest Bullish", flow.strongest_bullish or "—")
            a6.metric("Strongest Bearish", flow.strongest_bearish or "—")
            a7.metric("Flow Samples", len(flow.rows))
            a8.metric("Execution Impact", "NONE")
            rows = [row.as_dict() for row in flow.rows]
            rows.sort(key=lambda row: float(row.get("Confidence %") or 0.0), reverse=True)
            st.dataframe(_arrow_safe_rows(rows[:40]), width="stretch", hide_index=True)
    except Exception as exc:
        st.warning(f"Sprint-1 institutional flow unavailable: {exc}")

    st.markdown("### Sprint 2 — Velocity, Rotation & Institutional Strength")
    try:
        snapshot = InstitutionalSprint2Service(database).latest(instrument_key, trading_date)
        if snapshot.status != "READY":
            st.info(snapshot.reason)
            return

        strength = snapshot.strength
        ici = snapshot.confidence
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Buying Strength", f"{strength.buying_strength_pct:.1f}%")
        b2.metric("Selling Strength", f"{strength.selling_strength_pct:.1f}%")
        b3.metric("Net Strength", f"{strength.net_strength:+.1f}")
        b4.metric("Market Conviction", strength.market_conviction)

        b5, b6, b7, b8 = st.columns(4)
        b5.metric("Institutional Confidence Index", f"{ici.score:.1f}%")
        b6.metric("ICI Direction", ici.direction)
        b7.metric("ICI Quality", ici.quality)
        b8.metric("Execution Impact", ici.execution_impact)

        st.caption(
            f"Snapshots used: {snapshot.snapshots_used} · Latest: {snapshot.snapshot_timestamp or '—'} · "
            f"Previous: {snapshot.previous_snapshot_timestamp or '—'} · Coverage: {ici.data_coverage_pct:.1f}%"
        )
        st.info(strength.reason)

        st.markdown("#### Buying / Selling Strength Explanation")
        st.caption(
            "Read-only audit trace of the existing strength calculation: base Sprint-1 confidence × OI-velocity alignment × contract-quality weight. "
            "This section explains the current Buying/Selling Strength; it does not change the calculation or execution."
        )
        contribution_rows = [row.as_dict() for row in strength.contributions]
        bullish_rows = [row for row in contribution_rows if row.get("Direction") == "BULLISH"]
        bearish_rows = [row for row in contribution_rows if row.get("Direction") == "BEARISH"]
        bullish_rows.sort(key=lambda row: float(row.get("Weighted Contribution") or 0.0), reverse=True)
        bearish_rows.sort(key=lambda row: float(row.get("Weighted Contribution") or 0.0), reverse=True)
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Buying Strength", f"{strength.buying_strength_pct:.1f}%")
        e2.metric("Selling Strength", f"{strength.selling_strength_pct:.1f}%")
        e3.metric("Net Institutional Strength", f"{strength.net_strength:+.1f}")
        e4.metric("Directional Breadth", f"{strength.breadth_pct:.1f}%")
        left, right = st.columns(2)
        with left:
            st.markdown("##### Top Buying Contributors")
            if bullish_rows:
                st.dataframe(_arrow_safe_rows(bullish_rows[:15]), width="stretch", hide_index=True)
            else:
                st.info("No bullish institutional contributors in the current snapshot.")
        with right:
            st.markdown("##### Top Selling Contributors")
            if bearish_rows:
                st.dataframe(_arrow_safe_rows(bearish_rows[:15]), width="stretch", hide_index=True)
            else:
                st.info("No bearish institutional contributors in the current snapshot.")

        st.markdown("#### Contract Quality Weighting")
        quality_rows = [row.as_dict() for row in snapshot.contract_quality]
        qualified = sum(1 for row in snapshot.contract_quality if row.eligible)
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Contracts Assessed", len(snapshot.contract_quality))
        q2.metric("Qualified", qualified)
        q3.metric("Low Quality", max(0, len(snapshot.contract_quality) - qualified))
        inferred_atm = next((row.inferred_atm for row in snapshot.contract_quality if row.inferred_atm is not None), None)
        q4.metric("Inferred ATM", f"{inferred_atm:.0f}" if inferred_atm is not None else "—")
        st.caption(
            "Raw OI and Premium Velocity remain unchanged. Contract Quality only weights each contract's contribution "
            "to Buying/Selling Strength and ICI using ATM proximity, premium, OI and volume. Execution impact remains NONE."
        )
        quality_rows.sort(key=lambda row: float(row.get("Contract Quality %") or 0.0), reverse=True)
        st.dataframe(_arrow_safe_rows(quality_rows[:50]), width="stretch", hide_index=True)

        st.markdown("#### Strike Rotation")
        rotation = snapshot.rotation
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Rotation State", rotation.state)
        r2.metric("Call OI Shift", f"{rotation.call_shift_points:+.1f}" if rotation.call_shift_points is not None else "—")
        r3.metric("Put OI Shift", f"{rotation.put_shift_points:+.1f}" if rotation.put_shift_points is not None else "—")
        r4.metric("Rotation Confidence", f"{rotation.confidence_pct:.1f}%")

        st.markdown("#### Institutional Confidence Components")
        component_rows = [
            {"Component": name, "Score %": value}
            for name, value in ici.components.items()
        ]
        st.dataframe(_arrow_safe_rows(component_rows), width="stretch", hide_index=True)

        st.markdown("#### OI Velocity")
        velocity_rows = [row.as_dict() for row in snapshot.oi_velocity]
        velocity_rows.sort(
            key=lambda row: abs(float(row.get("OI Velocity 5m %") or 0.0)),
            reverse=True,
        )
        st.dataframe(_arrow_safe_rows(velocity_rows[:50]), width="stretch", hide_index=True)

        st.markdown("#### Premium Flow")
        premium_rows = [row.as_dict() for row in snapshot.premium_flow]
        premium_rows.sort(
            key=lambda row: float(row.get("Premium Strength %") or 0.0),
            reverse=True,
        )
        st.dataframe(_arrow_safe_rows(premium_rows[:50]), width="stretch", hide_index=True)

        with st.expander("How Sprint 2 is used", expanded=False):
            st.markdown(
                "- **Contract Quality** weights aggregate contribution using ATM proximity, premium, OI and volume; raw velocity remains unchanged.\n"
                "- **OI Velocity** measures 1m/5m/15m changes and acceleration.\n"
                "- **Premium Flow** identifies expansion, compression, decay, exhaustion and reversal expansion.\n"
                "- **Strike Rotation** measures migration of call/put OI concentration.\n"
                "- **Buying/Selling Strength** combines Sprint-1 directional evidence with OI velocity alignment and contract quality.\n"
                "- **ICI** combines directional edge, quality-weighted OI velocity, quality-weighted premium flow, rotation and breadth.\n\n"
                "All Sprint-2 outputs are **informational only** and have execution impact = NONE."
            )
    except Exception as exc:
        st.warning(f"Sprint-2 institutional intelligence unavailable: {exc}")
