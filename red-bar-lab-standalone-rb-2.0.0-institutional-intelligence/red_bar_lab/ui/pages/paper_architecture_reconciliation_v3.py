from __future__ import annotations

import streamlit as st

import red_bar_lab.ui.pages.paper_architecture_reconciliation_v2 as previous
from red_bar_lab.ui.controlled_paper_activation import (
    build_controlled_paper_activation,
    render_controlled_paper_activation,
)
from red_bar_lab.ui.strategy_shadow_evidence_registry import read_shadow_evidence
from red_bar_lab.ui.unified_shadow_execution_router import build_unified_shadow_routes


SECTION_10_STAGES = tuple(
    {
        **dict(row),
        **(
            {"status": "IMPLEMENTED_DISABLED", "authority": "DISABLED"}
            if row.get("section") == "10E"
            else {"status": "NEXT", "authority": "NOT_EVALUATED"}
            if row.get("section") == "10F"
            else {}
        ),
    }
    for row in previous.SECTION_10_STAGES
)
previous.SECTION_10_STAGES = SECTION_10_STAGES
previous.base.SECTION_10_STAGES = SECTION_10_STAGES


def build_reconciliation_snapshot(orders, shadow_evidence=None):
    snapshot = previous.build_reconciliation_snapshot(orders, shadow_evidence)
    snapshot["stages"] = [dict(row) for row in SECTION_10_STAGES]
    router = snapshot.get("shadow_router") or build_unified_shadow_routes(
        snapshot.get("shadow_evidence") or []
    )
    snapshot["controlled_paper_activation"] = build_controlled_paper_activation(router)
    return snapshot


def _render_activation_and_remaining_roadmap() -> None:
    evidence = read_shadow_evidence()
    router = build_unified_shadow_routes(evidence)
    render_controlled_paper_activation(build_controlled_paper_activation(router))

    st.markdown("### Reconciliation Roadmap")
    st.markdown("#### 10F. Legacy Migration Decision")
    st.info(
        "Next: decide KEEP_LEGACY, HYBRID, NEW_ROUTER_PRIMARY or RETIRE_LEGACY only "
        "after comparison quality, activation readiness and full lifecycle evidence are sufficient."
    )


previous._render_router_and_remaining_roadmap = _render_activation_and_remaining_roadmap


def render_page(
    settings,
    layout,
    database,
    token,
    underlying_name,
    instrument_key,
    interval,
) -> None:
    previous.render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    )


__all__ = [
    "SECTION_10_STAGES",
    "build_reconciliation_snapshot",
    "render_page",
]
