from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

import streamlit as st


CONTROLLED_PAPER_ACTIVATION_VERSION = "CONTROLLED-PAPER-ACTIVATION-V1"


@dataclass(frozen=True)
class PaperActivationControls:
    paper_activation_enabled: bool = False
    live_activation_enabled: bool = False
    durable_idempotency_ready: bool = False
    atomic_reservation_ready: bool = False
    lifecycle_journal_ready: bool = False
    paper_adapter_ready: bool = False
    position_monitor_ready: bool = False
    exit_controller_ready: bool = False
    restart_recovery_ready: bool = False
    rollback_ready: bool = False
    legacy_fallback_ready: bool = True


DEFAULT_CONTROLS = PaperActivationControls()


def _checks(controls: PaperActivationControls) -> list[dict[str, object]]:
    return [
        {"requirement": "Explicit paper activation", "ready": controls.paper_activation_enabled},
        {"requirement": "Durable idempotency store", "ready": controls.durable_idempotency_ready},
        {"requirement": "Atomic capital and slot reservation", "ready": controls.atomic_reservation_ready},
        {"requirement": "Durable lifecycle journal", "ready": controls.lifecycle_journal_ready},
        {"requirement": "Paper execution adapter", "ready": controls.paper_adapter_ready},
        {"requirement": "Active position monitor", "ready": controls.position_monitor_ready},
        {"requirement": "Strategy-owned exit controller", "ready": controls.exit_controller_ready},
        {"requirement": "Restart recovery", "ready": controls.restart_recovery_ready},
        {"requirement": "Rollback controls", "ready": controls.rollback_ready},
        {"requirement": "Legacy fallback retained", "ready": controls.legacy_fallback_ready},
        {"requirement": "Live activation hard disabled", "ready": not controls.live_activation_enabled},
    ]


def build_controlled_paper_activation(
    shadow_router: Mapping[str, object],
    *,
    controls: PaperActivationControls = DEFAULT_CONTROLS,
) -> dict[str, object]:
    """Evaluate paper activation without performing any execution side effect."""
    checks = _checks(controls)
    prerequisites_ready = all(bool(row["ready"]) for row in checks)
    rows: list[dict[str, object]] = []

    for raw in shadow_router.get("rows") or []:
        route = dict(raw)
        route_ready = str(route.get("route_outcome") or "") == "ROUTED_SHADOW_ONLY"
        reasons: list[str] = []
        if not route_ready:
            reasons.append("SHADOW_ROUTE_NOT_READY")
        for check in checks:
            if not check["ready"]:
                reasons.append(str(check["requirement"]).upper().replace(" ", "_"))

        activation_ready = route_ready and prerequisites_ready
        rows.append(
            {
                **route,
                "activation_version": CONTROLLED_PAPER_ACTIVATION_VERSION,
                "activation_outcome": (
                    "PAPER_ACTIVATION_READY_DISABLED"
                    if activation_ready
                    else "PAPER_ACTIVATION_BLOCKED"
                ),
                "activation_reason": (
                    "ALL_PREREQUISITES_READY_EXPLICIT_ENABLEMENT_STILL_REQUIRED"
                    if activation_ready
                    else ", ".join(dict.fromkeys(reasons))
                ),
                "paper_activation_enabled": controls.paper_activation_enabled,
                "paper_execution_allowed": False,
                "live_execution_allowed": False,
                "paper_adapter_attached": False,
                "live_adapter_attached": False,
                "idempotency_persisted": False,
                "capital_reserved": False,
                "bundle_consumed": False,
                "position_created": False,
                "lifecycle_started": False,
                "order_created": False,
                "order_submitted": False,
                "rollback_available": controls.rollback_ready,
                "legacy_fallback_available": controls.legacy_fallback_ready,
                "policy_action": "BLOCK_UNTIL_EXPLICIT_ENABLEMENT",
            }
        )

    counts = Counter(str(row["activation_outcome"]) for row in rows)
    ready = int(counts.get("PAPER_ACTIVATION_READY_DISABLED", 0))
    blocked = int(counts.get("PAPER_ACTIVATION_BLOCKED", 0))
    return {
        "outcome": (
            "PAPER_ACTIVATION_READY_DISABLED"
            if ready
            else "PAPER_ACTIVATION_BLOCKED" if rows
            else "NO_SHADOW_ROUTES"
        ),
        "rows": rows,
        "checks": checks,
        "ready_count": ready,
        "blocked_count": blocked,
        "activation_version": CONTROLLED_PAPER_ACTIVATION_VERSION,
        "paper_activation_enabled": controls.paper_activation_enabled,
        "live_activation_enabled": controls.live_activation_enabled,
        "paper_execution_allowed": False,
        "live_execution_allowed": False,
        "persisted": False,
        "capital_reserved": False,
        "bundle_consumed": False,
        "position_created": False,
        "lifecycle_started": False,
        "order_created": False,
        "order_submitted": False,
        "policy_action": "BLOCK_UNTIL_EXPLICIT_ENABLEMENT",
    }


def render_controlled_paper_activation(result: Mapping[str, object]) -> None:
    st.markdown("### 10E. Controlled Paper-Only Activation")
    st.caption(
        "Evaluates the complete paper-execution lifecycle boundary. The new router remains "
        "unable to create positions until every durable prerequisite is implemented and "
        "paper activation is explicitly enabled. Live execution stays hard-disabled."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Activation outcome", str(result.get("outcome") or "NO_SHADOW_ROUTES"))
    c2.metric("Ready routes", int(result.get("ready_count") or 0))
    c3.metric("Blocked routes", int(result.get("blocked_count") or 0))
    c4.metric("Paper execution", "DISABLED")

    st.dataframe(
        [
            {
                "Requirement": row.get("requirement"),
                "Status": "READY" if row.get("ready") else "MISSING",
            }
            for row in result.get("checks") or []
        ],
        width="stretch",
        hide_index=True,
    )

    rows = [dict(row) for row in result.get("rows") or []]
    if rows:
        st.dataframe(
            [
                {
                    "Route": row.get("route_id"),
                    "Strategy": row.get("strategy_id"),
                    "Signal": row.get("signal_id"),
                    "Candidate": row.get("candidate_id"),
                    "Outcome": row.get("activation_outcome"),
                    "Reason": row.get("activation_reason"),
                    "Lifecycle Started": row.get("lifecycle_started"),
                    "Position Created": row.get("position_created"),
                }
                for row in rows[:500]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No routed Section 10D candidate is available for paper activation review.")

    st.warning(
        "10E control plane is implemented, but the new executor is not active. Legacy RB093 "
        "continues to own paper execution until durable lifecycle components are implemented, "
        "validated, and explicitly enabled."
    )


__all__ = [
    "CONTROLLED_PAPER_ACTIVATION_VERSION",
    "PaperActivationControls",
    "DEFAULT_CONTROLS",
    "build_controlled_paper_activation",
    "render_controlled_paper_activation",
]
