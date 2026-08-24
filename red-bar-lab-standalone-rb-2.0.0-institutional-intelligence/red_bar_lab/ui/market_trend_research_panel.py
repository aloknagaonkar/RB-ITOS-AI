from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)
from red_bar_lab.ui._shared import _arrow_safe_rows


def _number(value: object, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _strike_rows(panel: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in panel.get("rows") or []
        if row.get("position") != "TOTAL"
    ]


def _leader(
    rows: list[dict[str, Any]],
    *,
    field: str,
    largest: bool,
) -> dict[str, object]:
    available = [row for row in rows if row.get(field) is not None]
    if not available:
        return {"strike": "—", "change": None, "percentage": None}
    selected = (max if largest else min)(
        available,
        key=lambda row: float(row[field]),
    )
    prefix = "ce" if field.startswith("ce_") else "pe"
    return {
        "strike": selected.get("strike"),
        "change": selected.get(field),
        "percentage": selected.get(f"{prefix}_change_pct"),
    }


def _render_leaders(panel: dict[str, Any]) -> None:
    rows = _strike_rows(panel)
    leaders = [
        ("Largest CE OI addition", _leader(rows, field="ce_change", largest=True)),
        ("Largest CE OI reduction", _leader(rows, field="ce_change", largest=False)),
        ("Largest PE OI addition", _leader(rows, field="pe_change", largest=True)),
        ("Largest PE OI reduction", _leader(rows, field="pe_change", largest=False)),
    ]
    st.dataframe(
        _arrow_safe_rows(
            [
                {
                    "Leader": label,
                    "Strike": evidence["strike"],
                    "Absolute change": evidence["change"],
                    "Change percentage": evidence["percentage"],
                }
                for label, evidence in leaders
            ]
        ),
        width="stretch",
        hide_index=True,
    )


def _render_panel(panel: dict[str, Any], *, morning: bool) -> None:
    st.markdown(f"### {panel.get('name', 'PCR research')}")
    aggregate = panel.get("aggregate") or {}
    metrics = st.columns(6)
    metrics[0].metric("Spot", _number(panel.get("spot"), 2))
    metrics[1].metric("ATM", _number(panel.get("atm"), 0))
    metrics[2].metric("Expiry", panel.get("expiry") or "—")
    metrics[3].metric("Window", f"ATM ±{panel.get('window_steps', '—')}")
    metrics[4].metric("PCR", _number(aggregate.get("pcr")))
    metrics[5].metric(
        "PCR directional evidence",
        aggregate.get("classification") or "UNAVAILABLE",
    )
    movement = st.columns(5)
    movement[0].metric("Previous PCR", _number(aggregate.get("previous_pcr")))
    movement[1].metric("PCR change", _number(aggregate.get("absolute_change")))
    movement[2].metric(
        "PCR change %",
        _number(aggregate.get("percentage_change"), 2),
    )
    movement[3].metric(
        "PCR slope / minute",
        _number(aggregate.get("slope_per_minute"), 5),
    )
    movement[4].metric(
        "Persistence",
        (
            f"{aggregate.get('persistence_state', 'UNAVAILABLE')} "
            f"×{aggregate.get('consecutive_count', 0)}"
        ),
    )
    strikes = [
        row.get("strike")
        for row in _strike_rows(panel)
        if isinstance(row.get("strike"), (int, float))
    ]
    strike_range = (
        f"{min(strikes):.0f}–{max(strikes):.0f}" if strikes else "—"
    )
    st.caption(
        f"Sessions to expiry: {panel.get('sessions_to_expiry', '—')} · "
        f"Strike interval: {_number(panel.get('strike_interval'), 0)} · "
        f"Selected strikes: {strike_range} · "
        f"Contracts: {panel.get('observed_contract_count', 0)}/"
        f"{panel.get('expected_contract_count', 0)} · "
        f"Snapshot: {panel.get('source_timestamp', '—')}"
    )
    if morning:
        st.caption(
            f"Morning anchor: {panel.get('anchor_timestamp') or 'UNAVAILABLE'} · "
            f"Anchor status: {panel.get('anchor_status') or 'UNAVAILABLE'} · "
            f"Fixed spot: {_number(panel.get('anchor_spot'), 2)} · "
            f"Fixed ATM: {_number(panel.get('anchor_atm'), 0)} · "
            f"Anchor relevance: {panel.get('anchor_relevance') or 'UNAVAILABLE'}"
        )
    st.dataframe(
        _arrow_safe_rows(panel.get("rows") or []),
        width="stretch",
        hide_index=True,
    )
    st.markdown("#### OI leaders")
    _render_leaders(panel)


def render_market_trend_research_panel(
    database_path: str | Path,
    *,
    underlying: str,
) -> None:
    st.error(
        "OBSERVATIONAL ONLY — this research does not generate signals or trades."
    )
    projection = MarketTrendResearchRepository(database_path).latest_projection(
        underlying=underlying
    )
    if not projection:
        st.info("No persisted Market Trend Research projection is available.")
        st.caption("Final market direction: NOT YET CALCULATED")
        st.caption("Signal generated: NO")
        st.caption("Canonical bundle created: NO")
        st.caption("Opportunity queued: NO")
        st.caption("Paper trade created: NO")
        return

    quality = projection.get("quality") or {}
    latency = projection.get("latency") or {}
    current = projection.get("current_panel") or {}
    morning = projection.get("morning_panel")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Final market direction", "NOT YET CALCULATED")
    c2.metric(
        "Current PCR bias",
        (current.get("aggregate") or {}).get("classification") or "UNAVAILABLE",
    )
    c3.metric(
        "Morning PCR bias",
        ((morning or {}).get("aggregate") or {}).get("classification")
        or "UNAVAILABLE",
    )
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
        difference = (
            None
            if current_pcr is None or morning_pcr is None
            else float(current_pcr) - float(morning_pcr)
        )
        st.dataframe(
            _arrow_safe_rows(
                [
                    {
                        "Current PCR": current_pcr,
                        "Morning PCR": morning_pcr,
                        "Difference": difference,
                        "Current bias": (current.get("aggregate") or {}).get(
                            "classification"
                        ),
                        "Morning bias": (morning.get("aggregate") or {}).get(
                            "classification"
                        ),
                        "Agreement": projection.get("agreement_state"),
                        "Interpretation": (
                            "Both windows show the same PCR directional evidence."
                            if projection.get("agreement_state") == "AGREE"
                            else "Current and fixed-morning PCR evidence diverge."
                        ),
                    }
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    st.markdown("### Performance")
    st.dataframe(
        _arrow_safe_rows([latency]),
        width="stretch",
        hide_index=True,
    )
    with st.expander("What happened?", expanded=False):
        for index, line in enumerate(
            projection.get("explanation") or (),
            start=1,
        ):
            st.write(f"{index}. {line}")

    st.caption("Authority: OBSERVATIONAL ONLY")
    st.caption("Signal generated: NO")
    st.caption("Canonical bundle created: NO")
    st.caption("Opportunity queued: NO")
    st.caption("Paper trade created: NO")
