from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository
from red_bar_lab.ui._shared import _arrow_safe_rows


def _number(value: object, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _render_panel(panel: dict[str, Any], *, morning: bool) -> None:
    st.markdown(f"### {panel.get('name', 'PCR research')}")
    aggregate = panel.get("aggregate") or {}
    metrics = st.columns(6)
    metrics[0].metric("Spot", _number(panel.get("spot"), 2))
    metrics[1].metric("ATM", _number(panel.get("atm"), 0))
    metrics[2].metric("Expiry", panel.get("expiry") or "—")
    metrics[3].metric("Window", f"ATM ±{panel.get('window_steps', '—')}")
    metrics[4].metric("PCR", _number(aggregate.get("pcr")))
    metrics[5].metric("PCR directional evidence", aggregate.get("classification") or "UNAVAILABLE")
    st.caption(
        f"Sessions to expiry: {panel.get('sessions_to_expiry', '—')} · "
        f"Strike interval: {_number(panel.get('strike_interval'), 0)} · "
        f"Contracts: {panel.get('observed_contract_count', 0)}/{panel.get('expected_contract_count', 0)} · "
        f"Snapshot: {panel.get('source_timestamp', '—')}"
    )
    if morning:
        st.caption(
            f"Morning anchor: {panel.get('anchor_timestamp') or 'UNAVAILABLE'} · "
            f"Fixed spot: {_number(panel.get('anchor_spot'), 2)} · "
            f"Fixed ATM: {_number(panel.get('anchor_atm'), 0)} · "
            f"Anchor relevance: {panel.get('anchor_relevance') or 'UNAVAILABLE'}"
        )
    st.dataframe(_arrow_safe_rows(panel.get("rows") or []), width="stretch", hide_index=True)


def render_market_trend_research_panel(database_path: str | Path, *, underlying: str) -> None:
    st.error("OBSERVATIONAL ONLY — this research does not generate signals or trades.")
    projection = MarketTrendResearchRepository(database_path).latest_projection(underlying=underlying)
    if not projection:
        st.info("No persisted Market Trend Research projection is available.")
        st.caption("Final market direction: NOT YET CALCULATED")
        return
    quality = projection.get("quality") or {}
    latency = projection.get("latency") or {}
    current = projection.get("current_panel") or {}
    morning = projection.get("morning_panel")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Final market direction", "NOT YET CALCULATED")
    c2.metric("Current PCR bias", (current.get("aggregate") or {}).get("classification") or "UNAVAILABLE")
    c3.metric("Morning PCR bias", ((morning or {}).get("aggregate") or {}).get("classification") or "UNAVAILABLE")
    c4.metric("Agreement", projection.get("agreement_state") or "UNAVAILABLE")
    c5.metric("Evidence quality", quality.get("state") or "UNAVAILABLE")
    st.caption(
        f"Snapshot age: {_number(quality.get('source_age_seconds'), 1)} seconds · "
        f"End-to-end latency: {_number(latency.get('end_to_end_ms'), 1)} ms"
    )
    _render_panel(current, morning=False)
    if morning:
        _render_panel(morning, morning=True)
    else:
        st.warning("MORNING_ANCHOR_UNAVAILABLE")
    if morning:
        st.markdown("### Current versus Morning PCR")
        current_pcr = (current.get("aggregate") or {}).get("pcr")
        morning_pcr = (morning.get("aggregate") or {}).get("pcr")
        difference = None if current_pcr is None or morning_pcr is None else float(current_pcr) - float(morning_pcr)
        st.dataframe(_arrow_safe_rows([{
            "Current PCR": current_pcr,
            "Morning PCR": morning_pcr,
            "Difference": difference,
            "Current bias": (current.get("aggregate") or {}).get("classification"),
            "Morning bias": (morning.get("aggregate") or {}).get("classification"),
            "Agreement": projection.get("agreement_state"),
        }]), width="stretch", hide_index=True)
    st.markdown("### Performance")
    st.dataframe(_arrow_safe_rows([latency]), width="stretch", hide_index=True)
    with st.expander("What happened?", expanded=False):
        for index, line in enumerate(projection.get("explanation") or (), start=1):
            st.write(f"{index}. {line}")
    st.caption("Authority: OBSERVATIONAL ONLY")
    st.caption("Signal generated: NO")
    st.caption("Canonical bundle created: NO")
    st.caption("Opportunity queued: NO")
    st.caption("Paper trade created: NO")
