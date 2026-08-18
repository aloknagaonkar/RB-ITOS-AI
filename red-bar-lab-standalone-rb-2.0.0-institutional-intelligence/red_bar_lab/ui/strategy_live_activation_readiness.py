from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

import streamlit as st


LIVE_ACTIVATION_AUDIT_VERSION = "LIVE-ACTIVATION-READINESS-V1"


@dataclass(frozen=True)
class LiveActivationReadinessPolicy:
    policy_version: str = LIVE_ACTIVATION_AUDIT_VERSION
    require_shadow_handoff: bool = True
    live_activation_enabled: bool = False


DEFAULT_POLICY = LiveActivationReadinessPolicy()


def _present(value: object) -> bool:
    return value not in (None, "", "Unavailable", "UNAVAILABLE", "Not created")


def _audit_id(row: Mapping[str, object]) -> str:
    raw = "|".join(str(row.get(name) or "") for name in (
        "shadow_rehearsal_id", "adapter_mapping_validation_id",
        "broker_payload_preview_id", "order_specification_id", "committee_id",
        "strategy_id", "bundle_id", "signal_id", "candidate_id",
        "payload_fingerprint_sha256",
    ))
    return f"ACTAUD-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def _requirement(name: str, category: str, available: bool, reason: str) -> dict[str, object]:
    return {
        "requirement": name,
        "category": category,
        "status": "AVAILABLE" if available else "NOT_IMPLEMENTED",
        "available": available,
        "reason": reason,
    }


def build_live_activation_readiness(
    shadow_rehearsal: Mapping[str, object],
    *,
    policy: LiveActivationReadinessPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Audit live prerequisites while keeping activation impossible and side-effect free."""
    rows: list[dict[str, object]] = []
    for raw in shadow_rehearsal.get("rows") or []:
        row = dict(raw)
        shadow_ready = (
            str(row.get("shadow_rehearsal_outcome") or "") == "SHADOW_HANDOFF_READY_DISABLED"
            and row.get("shadow_handoff_ready") is True
            and row.get("live_activation_allowed") is False
        )
        lineage_ready = all(_present(row.get(name)) for name in (
            "shadow_rehearsal_id", "adapter_mapping_validation_id",
            "broker_payload_preview_id", "order_specification_id", "committee_id",
            "strategy_id", "bundle_id", "signal_id", "candidate_id",
            "entry_client_order_id", "protective_client_order_id",
            "payload_fingerprint_sha256",
        ))
        disabled_boundary = all(row.get(name) is False for name in (
            "submission_enabled", "broker_client_attached", "credentials_attached",
            "transport_attached", "broker_payload_created", "order_created",
            "order_submitted", "persisted", "reserved", "bundle_consumed", "submitted",
        ))

        prerequisites = [
            _requirement("Shadow chain validated", "VALIDATION", shadow_ready, "Section 9E must be shadow-ready and disabled."),
            _requirement("Execution lineage complete", "VALIDATION", lineage_ready, "All strategy-to-payload identities must be present."),
            _requirement("Disabled boundary intact", "SAFETY", disabled_boundary, "No live dependency may be attached during this audit."),
            _requirement("Durable idempotency registry", "PERSISTENCE", False, "No durable client-order/fingerprint claim store is implemented."),
            _requirement("Atomic capital and risk reservation", "RISK", False, "Read-only proposals are not atomic reservations."),
            _requirement("Broker credential provider", "SECURITY", False, "Credentials are deliberately absent."),
            _requirement("Broker transport adapter", "EXECUTION", False, "No network transport or callable broker client is attached."),
            _requirement("Order acknowledgement reconciliation", "RECOVERY", False, "No broker acknowledgement, timeout or unknown-state reconciler exists."),
            _requirement("Protective-order recovery", "RECOVERY", False, "No live recovery path guarantees protective-stop placement after entry fill."),
            _requirement("Operator approval record", "GOVERNANCE", False, "No explicit two-step production approval has been recorded."),
            _requirement("Kill-switch integration test", "SAFETY", False, "No live transport exists against which to verify kill-switch interruption."),
            _requirement("Production activation configuration", "GOVERNANCE", policy.live_activation_enabled, "Activation remains hard-disabled by policy."),
        ]
        available_count = sum(item["available"] is True for item in prerequisites)
        missing = [str(item["requirement"]) for item in prerequisites if item["available"] is False]
        shadow_validation_complete = shadow_ready and lineage_ready and disabled_boundary
        outcome = (
            "LIVE_ACTIVATION_READY_EXPLICITLY_DISABLED"
            if shadow_validation_complete and not missing and policy.live_activation_enabled
            else "LIVE_ACTIVATION_BLOCKED_READ_ONLY"
        )
        rows.append({
            **row,
            "live_activation_audit_id": _audit_id(row),
            "live_activation_audit_outcome": outcome,
            "live_activation_audit_reason": (
                "ALL_LIVE_PREREQUISITES_AVAILABLE_BUT_ACTIVATION_REQUIRES_EXPLICIT_ENABLEMENT"
                if not missing else "MISSING_LIVE_PREREQUISITES: " + ", ".join(missing)
            ),
            "live_activation_audit_version": policy.policy_version,
            "activation_requirements": prerequisites,
            "activation_requirement_count": len(prerequisites),
            "activation_available_count": available_count,
            "activation_missing_count": len(missing),
            "activation_missing_requirements": missing,
            "shadow_validation_complete": shadow_validation_complete,
            "live_activation_allowed": False,
            "production_approval_recorded": False,
            "submission_enabled": False,
            "broker_client_attached": False,
            "credentials_attached": False,
            "transport_attached": False,
            "broker_payload_created": False,
            "order_created": False,
            "order_submitted": False,
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
            "policy_action": "AUDIT_ONLY",
            "next_step": "Complete and independently validate every missing prerequisite before proposing any live activation change.",
        })

    blocked = sum(row["live_activation_audit_outcome"] == "LIVE_ACTIVATION_BLOCKED_READ_ONLY" for row in rows)
    return {
        "outcome": "LIVE_ACTIVATION_BLOCKED_READ_ONLY" if blocked else "NOT_ELIGIBLE",
        "rows": rows,
        "blocked_count": blocked,
        "live_activation_audit_version": policy.policy_version,
        "live_activation_allowed": False,
        "production_approval_recorded": False,
        "submission_enabled": False,
        "broker_client_attached": False,
        "credentials_attached": False,
        "transport_attached": False,
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
        "policy_action": "AUDIT_ONLY",
    }


def render_live_activation_readiness(result: Mapping[str, object]) -> None:
    st.markdown("#### 9F. Live Activation Readiness Audit")
    st.caption(
        "Separates shadow-chain completeness from production activation readiness. "
        "This is an audit checklist only; live execution remains unavailable."
    )
    rows = [dict(row) for row in result.get("rows") or []]
    c1, c2, c3 = st.columns(3)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Audited candidates", len(rows))
    c3.metric("Live activation", "BLOCKED")
    if not rows:
        st.info("No Section 9E shadow rehearsal is available for activation audit.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "live_activation_audit_id", "shadow_rehearsal_id", "candidate_id",
            "strategy_id", "shadow_validation_complete", "activation_requirement_count",
            "activation_available_count", "activation_missing_count",
            "live_activation_audit_outcome",
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"View live-activation prerequisites for {row.get('candidate_id')}"):
            st.dataframe(list(row.get("activation_requirements") or []), width="stretch", hide_index=True)
            st.write(f"**Outcome:** {row.get('live_activation_audit_outcome')}")
            st.write(f"**Exact reason:** {row.get('live_activation_audit_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
            st.write("**Safety:** This audit cannot enable persistence, credentials, transport or submission.")


__all__ = [
    "LiveActivationReadinessPolicy",
    "DEFAULT_POLICY",
    "LIVE_ACTIVATION_AUDIT_VERSION",
    "build_live_activation_readiness",
    "render_live_activation_readiness",
]
