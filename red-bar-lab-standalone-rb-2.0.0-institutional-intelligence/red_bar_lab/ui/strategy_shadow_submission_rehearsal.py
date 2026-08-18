from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

import streamlit as st


SHADOW_REHEARSAL_VERSION = "SHADOW-SUBMISSION-REHEARSAL-V1"


@dataclass(frozen=True)
class ShadowSubmissionPolicy:
    policy_version: str = SHADOW_REHEARSAL_VERSION
    require_validated_mapping: bool = True
    require_all_live_dependencies_absent: bool = True


DEFAULT_POLICY = ShadowSubmissionPolicy()


def _present(value: object) -> bool:
    return value not in (None, "", "Unavailable", "UNAVAILABLE", "Not created")


def _rehearsal_id(row: Mapping[str, object]) -> str:
    raw = "|".join(str(row.get(name) or "") for name in (
        "adapter_mapping_validation_id", "broker_payload_preview_id",
        "order_specification_id", "committee_id", "strategy_id",
        "bundle_id", "signal_id", "candidate_id",
        "payload_fingerprint_sha256",
    ))
    return f"SHADOW-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def build_shadow_submission_rehearsal(
    adapter_mapping: Mapping[str, object],
    *,
    policy: ShadowSubmissionPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Rehearse the final broker boundary without persistence, transport or submission."""
    rows: list[dict[str, object]] = []
    for raw in adapter_mapping.get("rows") or []:
        row = dict(raw)
        waits: list[str] = []
        checks: list[dict[str, object]] = []

        def check(name: str, passed: bool, reason: str) -> None:
            checks.append({"check": name, "status": "PASS" if passed else "WAIT", "detail": reason})
            if not passed:
                waits.append(reason)

        mapping_ready = (
            str(row.get("adapter_mapping_outcome") or "")
            == "ADAPTER_MAPPING_VALIDATED_READ_ONLY"
        )
        if policy.require_validated_mapping:
            check("Section 9D authority", mapping_ready, "ADAPTER_MAPPING_NOT_VALIDATED")

        identities_ready = all(_present(row.get(name)) for name in (
            "adapter_mapping_validation_id", "broker_payload_preview_id",
            "order_specification_id", "committee_id", "strategy_id",
            "bundle_id", "signal_id", "candidate_id",
            "entry_client_order_id", "protective_client_order_id",
            "payload_fingerprint_sha256",
        ))
        check("Execution lineage completeness", identities_ready, "EXECUTION_LINEAGE_INCOMPLETE")

        idempotency_ready = (
            row.get("fingerprint_matches") is True
            and row.get("duplicate_submission_prevented") is True
            and row.get("entry_client_order_id") != row.get("protective_client_order_id")
        )
        check("Idempotency and duplicate prevention", idempotency_ready, "IDEMPOTENCY_NOT_CONFIRMED")

        live_dependencies_absent = (
            row.get("submission_enabled") is False
            and row.get("broker_client_attached") is False
            and row.get("credentials_attached") is False
            and row.get("transport_attached") is False
            and row.get("persisted") is False
            and row.get("reserved") is False
            and row.get("bundle_consumed") is False
            and row.get("submitted") is False
            and row.get("order_created") is False
            and row.get("order_submitted") is False
            and row.get("broker_payload_created") is False
        )
        if policy.require_all_live_dependencies_absent:
            check("Live-execution dependencies absent", live_dependencies_absent, "LIVE_EXECUTION_DEPENDENCY_ATTACHED")

        payload = dict(row.get("payload_preview") or {})
        payload_disabled = (
            payload.get("submission_enabled") is False
            and payload.get("broker_client_attached") is False
            and payload.get("credentials_attached") is False
        )
        check("Payload remains disabled", payload_disabled, "PAYLOAD_NO_LONGER_HARD_DISABLED")

        boundary_state = {
            "validation_complete": mapping_ready and identities_ready and idempotency_ready,
            "persistence_available": False,
            "transport_available": False,
            "credentials_available": False,
            "broker_client_available": False,
            "submission_available": False,
            "first_live_action": "PERSIST_IDEMPOTENCY_RESERVATION_AND_ATTACH_BROKER_TRANSPORT",
        }
        outcome = "SHADOW_HANDOFF_READY_DISABLED" if not waits else "WAIT"
        rows.append({
            **row,
            "shadow_rehearsal_id": _rehearsal_id(row),
            "shadow_rehearsal_outcome": outcome,
            "shadow_rehearsal_reason": ", ".join(waits) if waits else "FINAL_BROKER_BOUNDARY_REHEARSED_WITH_EXECUTION_DISABLED",
            "shadow_rehearsal_checks": checks,
            "shadow_rehearsal_version": policy.policy_version,
            "execution_boundary_state": boundary_state,
            "shadow_handoff_ready": outcome == "SHADOW_HANDOFF_READY_DISABLED",
            "live_activation_allowed": False,
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
            "policy_action": "OBSERVE_ONLY",
            "next_step": (
                "Section 10 may define an explicitly disabled activation checklist and approval boundary."
                if outcome == "SHADOW_HANDOFF_READY_DISABLED"
                else "Resolve the exact shadow-rehearsal wait reason."
            ),
        })

    ready = sum(row["shadow_rehearsal_outcome"] == "SHADOW_HANDOFF_READY_DISABLED" for row in rows)
    waiting = sum(row["shadow_rehearsal_outcome"] == "WAIT" for row in rows)
    return {
        "outcome": "SHADOW_HANDOFF_READY_DISABLED" if ready else "WAIT" if waiting else "NOT_ELIGIBLE",
        "rows": rows,
        "ready_count": ready,
        "waiting_count": waiting,
        "shadow_rehearsal_version": policy.policy_version,
        "live_activation_allowed": False,
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
        "policy_action": "OBSERVE_ONLY",
    }


def render_shadow_submission_rehearsal(result: Mapping[str, object]) -> None:
    st.markdown("#### 9E. Shadow Submission Rehearsal and Execution Boundary Gate")
    st.caption(
        "Rehearses the final handoff entirely in memory. It identifies the first live-action boundary "
        "while proving that persistence, credentials, transport, broker client and submission remain absent."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Shadow ready", int(result.get("ready_count") or 0))
    c3.metric("Live activation", "DISABLED")
    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info("No Section 9D validated mapping is available for shadow rehearsal.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "shadow_rehearsal_id", "adapter_mapping_validation_id", "candidate_id",
            "strategy_id", "broker_adapter", "entry_client_order_id",
            "protective_client_order_id", "fingerprint_matches",
            "duplicate_submission_prevented", "shadow_handoff_ready",
            "shadow_rehearsal_outcome", "shadow_rehearsal_reason",
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"View shadow execution-boundary rehearsal for {row.get('candidate_id')}"):
            st.dataframe(list(row.get("shadow_rehearsal_checks") or []), width="stretch", hide_index=True)
            st.json(row.get("execution_boundary_state") or {})
            st.write(f"**Outcome:** {row.get('shadow_rehearsal_outcome')}")
            st.write(f"**Exact reason:** {row.get('shadow_rehearsal_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
            st.write("**Safety:** Live activation is not allowed and no external side effect occurred.")


__all__ = [
    "ShadowSubmissionPolicy",
    "DEFAULT_POLICY",
    "SHADOW_REHEARSAL_VERSION",
    "build_shadow_submission_rehearsal",
    "render_shadow_submission_rehearsal",
]
