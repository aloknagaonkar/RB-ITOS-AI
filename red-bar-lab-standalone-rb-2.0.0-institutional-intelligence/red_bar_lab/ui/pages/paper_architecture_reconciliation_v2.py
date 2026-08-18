from __future__ import annotations

from typing import Mapping

import streamlit as st

import red_bar_lab.ui.pages.paper_architecture_reconciliation as base
from red_bar_lab.ui.strategy_shadow_evidence_registry import read_shadow_evidence
from red_bar_lab.ui.unified_shadow_execution_router import (
    build_unified_shadow_routes,
    render_unified_shadow_routes,
)


SECTION_10_STAGES = tuple(
    {
        **dict(row),
        **(
            {"status": "COMPLETED", "authority": "SHADOW_ONLY"}
            if row.get("section") == "10D"
            else {"status": "NEXT", "authority": "DISABLED"}
            if row.get("section") == "10E"
            else {}
        ),
    }
    for row in base.SECTION_10_STAGES
)
base.SECTION_10_STAGES = SECTION_10_STAGES


def build_reconciliation_snapshot(orders, shadow_evidence=None):
    snapshot = base.build_reconciliation_snapshot(orders, shadow_evidence)
    snapshot["stages"] = [dict(row) for row in SECTION_10_STAGES]
    snapshot["shadow_router"] = build_unified_shadow_routes(
        snapshot.get("shadow_evidence") or []
    )
    return snapshot


def _render_router_and_remaining_roadmap() -> None:
    evidence = read_shadow_evidence()
    render_unified_shadow_routes(build_unified_shadow_routes(evidence))

    st.markdown("### Reconciliation Roadmap")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 10E. Controlled Paper-Only Activation")
        st.info(
            "Next. Requires explicit paper enablement, durable idempotency, atomic "
            "reservation, restart recovery, lifecycle ownership and rollback controls."
        )
    with c2:
        st.markdown("#### 10F. Legacy Migration Decision")
        st.caption(
            "Pending. KEEP_LEGACY, HYBRID, NEW_ROUTER_PRIMARY or RETIRE_LEGACY will "
            "be selected only from comparison and lifecycle evidence."
        )


base._render_pending_architecture = _render_router_and_remaining_roadmap


def render_page(
    settings,
    layout,
    database,
    token,
    underlying_name,
    instrument_key,
    interval,
) -> None:
    base.render_page(
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
