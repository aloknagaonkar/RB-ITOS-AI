from __future__ import annotations

from collections import Counter
import hashlib
from typing import Mapping, Sequence

import streamlit as st


UNIFIED_SHADOW_ROUTER_VERSION = "UNIFIED-SHADOW-EXECUTION-ROUTER-V1"
SUPPORTED_STRATEGIES = frozenset(
    {
        "RED_BAR",
        "REFERENCE_LEVEL",
    }
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _strategy(row: Mapping[str, object]) -> str:
    return _text(
        row.get("strategy_id")
        or row.get("execution_strategy_source")
        or row.get("strategy_source")
    ).upper()


def _route_id(row: Mapping[str, object]) -> str:
    raw = "|".join(
        _text(row.get(name))
        for name in (
            "strategy_id",
            "signal_id",
            "bundle_id",
            "candidate_id",
            "snapshot_timestamp",
            "evaluation_timestamp",
        )
    )
    return f"ROUTE-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def _identity_complete(row: Mapping[str, object]) -> bool:
    return all(
        _text(row.get(name))
        for name in ("strategy_id", "signal_id", "bundle_id", "candidate_id")
    )


def _admitted(row: Mapping[str, object]) -> bool:
    return bool(
        _text(row.get("new_chain_decision")).upper() == "ADMIT_READ_ONLY"
        or row.get("shadow_handoff_ready") is True
        or _text(row.get("shadow_rehearsal_outcome")).upper()
        == "SHADOW_HANDOFF_READY_DISABLED"
    )


def build_unified_shadow_routes(
    shadow_evidence: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Route independently owned strategy evidence through a disabled boundary.

    This router is deterministic and entirely in memory. It never persists,
    reserves capital, consumes a bundle, mutates a queue, creates a position,
    or submits an order.
    """
    rows: list[dict[str, object]] = []
    seen: set[str] = set()

    for raw in shadow_evidence:
        source = dict(raw)
        strategy = _strategy(source)
        normalized = {**source, "strategy_id": strategy}
        route_id = _route_id(normalized)
        reasons: list[str] = []

        if strategy not in SUPPORTED_STRATEGIES:
            reasons.append("UNSUPPORTED_STRATEGY")
        if not _identity_complete(normalized):
            reasons.append("INCOMPLETE_EXECUTION_IDENTITY")
        if not _admitted(normalized):
            reasons.append("NEW_CHAIN_NOT_ADMITTED")
        if route_id in seen:
            reasons.append("DUPLICATE_ROUTE_ID")

        route_outcome = "ROUTED_SHADOW_ONLY" if not reasons else "NOT_ROUTED"
        if route_outcome == "ROUTED_SHADOW_ONLY":
            seen.add(route_id)

        rows.append(
            {
                **normalized,
                "route_id": route_id,
                "router_version": UNIFIED_SHADOW_ROUTER_VERSION,
                "requested_mode": "SHADOW",
                "effective_mode": "SHADOW",
                "route_outcome": route_outcome,
                "route_reason": (
                    "SHADOW_ROUTE_READY_EXECUTION_DISABLED"
                    if not reasons
                    else ", ".join(reasons)
                ),
                "strategy_owner_preserved": True,
                "bundle_owner_preserved": True,
                "idempotency_key": route_id,
                "paper_adapter_attached": False,
                "live_adapter_attached": False,
                "execution_enabled": False,
                "paper_execution_allowed": False,
                "live_execution_allowed": False,
                "persisted": False,
                "queue_mutated": False,
                "capital_reserved": False,
                "bundle_consumed": False,
                "position_created": False,
                "order_created": False,
                "order_submitted": False,
                "policy_action": "OBSERVE_ONLY",
            }
        )

    counts = Counter(str(row["route_outcome"]) for row in rows)
    routed = int(counts.get("ROUTED_SHADOW_ONLY", 0))
    return {
        "outcome": (
            "ROUTED_SHADOW_ONLY"
            if routed
            else "NOT_ROUTED" if rows
            else "NO_SHADOW_EVIDENCE"
        ),
        "rows": rows,
        "route_count": len(rows),
        "routed_count": routed,
        "not_routed_count": int(counts.get("NOT_ROUTED", 0)),
        "strategy_counts": dict(Counter(_strategy(row) for row in rows)),
        "router_version": UNIFIED_SHADOW_ROUTER_VERSION,
        "effective_mode": "SHADOW",
        "execution_enabled": False,
        "paper_adapter_attached": False,
        "live_adapter_attached": False,
        "persisted": False,
        "queue_mutated": False,
        "capital_reserved": False,
        "bundle_consumed": False,
        "position_created": False,
        "order_created": False,
        "order_submitted": False,
        "policy_action": "OBSERVE_ONLY",
    }


def render_unified_shadow_routes(result: Mapping[str, object]) -> None:
    st.markdown("### 10D. Unified Shadow Execution Router")
    st.caption(
        "Routes Red Bar admissions through one deterministic in-memory boundary. "
        "Legacy reference-level evidence remains available for comparison only. "
        "Paper and live execution remain disabled."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Router outcome", str(result.get("outcome") or "NO_SHADOW_EVIDENCE"))
    c2.metric("Shadow routed", int(result.get("routed_count") or 0))
    c3.metric("Not routed", int(result.get("not_routed_count") or 0))
    c4.metric("Execution", "DISABLED")

    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info(
            "No Section 9E shadow evidence is available. The background architecture "
            "runner or a strategy-page evaluation must produce a shadow handoff first."
        )
        return

    st.dataframe(
        [
            {
                "Route": row.get("route_id"),
                "Strategy": row.get("strategy_id"),
                "Signal": row.get("signal_id"),
                "Bundle": row.get("bundle_id"),
                "Candidate": row.get("candidate_id"),
                "Mode": row.get("effective_mode"),
                "Outcome": row.get("route_outcome"),
                "Reason": row.get("route_reason"),
                "Paper Adapter": "ATTACHED" if row.get("paper_adapter_attached") else "DISABLED",
                "Live Adapter": "ATTACHED" if row.get("live_adapter_attached") else "DISABLED",
            }
            for row in rows[:500]
        ],
        width="stretch",
        hide_index=True,
    )
    st.write(
        "**Boundary:** routing is read-only and process-local. No queue write, capital "
        "reservation, bundle consumption, position creation, paper order, or broker "
        "submission can occur in Section 10D."
    )


__all__ = [
    "SUPPORTED_STRATEGIES",
    "UNIFIED_SHADOW_ROUTER_VERSION",
    "build_unified_shadow_routes",
    "render_unified_shadow_routes",
]
