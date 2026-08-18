from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

import streamlit as st


ADAPTER_MAPPING_VERSION = "ADAPTER-MAPPING-VALIDATION-V1"


@dataclass(frozen=True)
class AdapterMappingPolicy:
    policy_version: str = ADAPTER_MAPPING_VERSION
    require_two_legs: bool = True
    require_parent_link: bool = True
    require_fingerprint_match: bool = True
    require_hard_disabled: bool = True


DEFAULT_POLICY = AdapterMappingPolicy()


def _present(value: object) -> bool:
    return value not in (None, "", "Unavailable", "UNAVAILABLE", "Not created")


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


def _mapping_id(row: Mapping[str, object]) -> str:
    raw = "|".join(str(row.get(name) or "") for name in (
        "broker_payload_preview_id", "order_specification_id", "committee_id",
        "strategy_id", "bundle_id", "signal_id", "candidate_id",
        "payload_fingerprint_sha256",
    ))
    return f"MAPVAL-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def _same(left: Mapping[str, object], right: Mapping[str, object], field: str) -> bool:
    return left.get(field) == right.get(field) and _present(left.get(field))


def build_adapter_mapping_validation(
    payload_preview: Mapping[str, object],
    *,
    policy: AdapterMappingPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Validate disabled adapter mapping and deterministic idempotency without submission."""
    rows: list[dict[str, object]] = []
    for raw in payload_preview.get("rows") or []:
        row = dict(raw)
        payload = dict(row.get("payload_preview") or {})
        entry = dict(payload.get("entry_order") or {})
        stop = dict(payload.get("protective_stop_order") or {})
        waits: list[str] = []
        checks: list[dict[str, object]] = []

        def check(name: str, passed: bool, reason: str) -> None:
            checks.append({"check": name, "status": "PASS" if passed else "WAIT", "detail": reason})
            if not passed:
                waits.append(reason)

        preview_ready = str(row.get("broker_payload_preview_outcome") or "") == "PAYLOAD_PREVIEW_READY_DISABLED"
        check("Section 9C authority", preview_ready, "PAYLOAD_PREVIEW_NOT_READY")

        two_legs = bool(entry) and bool(stop)
        if policy.require_two_legs:
            check("Entry and protective legs", two_legs, "ENTRY_OR_PROTECTIVE_LEG_MISSING")

        identity_fields = ("adapter", "exchange", "instrument_token", "instrument_key", "trading_symbol")
        identity_consistent = two_legs and all(entry.get(field) == stop.get(field) for field in identity_fields)
        check("Instrument mapping consistency", identity_consistent, "ENTRY_STOP_INSTRUMENT_MAPPING_MISMATCH")

        commercial_fields = ("product_type", "validity", "quantity")
        commercial_consistent = two_legs and all(_same(entry, stop, field) for field in commercial_fields)
        check("Quantity and product consistency", commercial_consistent, "ENTRY_STOP_COMMERCIAL_MAPPING_MISMATCH")

        entry_id = entry.get("client_order_id")
        stop_id = stop.get("client_order_id")
        ids_present = _present(entry_id) and _present(stop_id) and entry_id != stop_id
        check("Distinct deterministic leg IDs", ids_present, "LEG_CLIENT_ORDER_IDS_INVALID")

        parent_link_ok = stop.get("parent_preview_order_id") == entry_id and stop.get("activation_condition") == "AFTER_ENTRY_FILL"
        if policy.require_parent_link:
            check("Protective parent linkage", parent_link_ok, "PROTECTIVE_PARENT_LINK_INVALID")

        transaction_ok = entry.get("transaction_type") == "BUY" and stop.get("transaction_type") == "SELL"
        check("Entry and exit transaction mapping", transaction_ok, "TRANSACTION_DIRECTION_MAPPING_INVALID")

        price_ok = (
            entry.get("order_type") == "LIMIT"
            and stop.get("order_type") == "STOP_LOSS_LIMIT"
            and entry.get("price") is not None
            and stop.get("price") is not None
            and stop.get("trigger_price") == stop.get("price")
        )
        check("Order-type and price mapping", price_ok, "ORDER_TYPE_OR_PRICE_MAPPING_INVALID")

        hard_disabled = (
            payload.get("submission_enabled") is False
            and payload.get("broker_client_attached") is False
            and payload.get("credentials_attached") is False
            and entry.get("submission_enabled") is False
            and stop.get("submission_enabled") is False
            and entry.get("preview_only") is True
            and stop.get("preview_only") is True
            and row.get("transport_attached") is False
        )
        if policy.require_hard_disabled:
            check("Execution hard-disable", hard_disabled, "ADAPTER_MAPPING_NOT_HARD_DISABLED")

        expected_fingerprint = _fingerprint(payload) if payload else None
        fingerprint_ok = (
            _present(row.get("payload_fingerprint_sha256"))
            and row.get("payload_fingerprint_sha256") == expected_fingerprint
        )
        if policy.require_fingerprint_match:
            check("Payload fingerprint idempotency", fingerprint_ok, "PAYLOAD_FINGERPRINT_MISMATCH")

        preview_id = row.get("broker_payload_preview_id")
        preview_identity_ok = payload.get("preview_id") == preview_id and _present(preview_id)
        check("Preview identity idempotency", preview_identity_ok, "PAYLOAD_PREVIEW_ID_MISMATCH")

        outcome = "ADAPTER_MAPPING_VALIDATED_READ_ONLY" if not waits else "WAIT"
        rows.append({
            **row,
            "adapter_mapping_validation_id": _mapping_id(row),
            "adapter_mapping_outcome": outcome,
            "adapter_mapping_reason": ", ".join(waits) if waits else "ADAPTER_MAPPING_AND_IDEMPOTENCY_VALIDATED",
            "adapter_mapping_checks": checks,
            "adapter_mapping_version": policy.policy_version,
            "recomputed_payload_fingerprint_sha256": expected_fingerprint,
            "fingerprint_matches": fingerprint_ok,
            "entry_client_order_id": entry_id,
            "protective_client_order_id": stop_id,
            "protective_parent_order_id": stop.get("parent_preview_order_id"),
            "duplicate_submission_prevented": hard_disabled and fingerprint_ok and ids_present,
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
                "Section 9E may audit execution-boundary readiness without enabling submission."
                if outcome == "ADAPTER_MAPPING_VALIDATED_READ_ONLY"
                else "Resolve the exact adapter-mapping or idempotency wait reason."
            ),
        })

    ready = sum(row["adapter_mapping_outcome"] == "ADAPTER_MAPPING_VALIDATED_READ_ONLY" for row in rows)
    waiting = sum(row["adapter_mapping_outcome"] == "WAIT" for row in rows)
    return {
        "outcome": "ADAPTER_MAPPING_VALIDATED_READ_ONLY" if ready else "WAIT" if waiting else "NOT_ELIGIBLE",
        "rows": rows,
        "validated_count": ready,
        "waiting_count": waiting,
        "adapter_mapping_version": policy.policy_version,
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


def render_adapter_mapping_validation(result: Mapping[str, object]) -> None:
    st.markdown("#### 9D. Adapter Mapping and Idempotency Validation")
    st.caption(
        "Verifies the disabled entry/stop mapping, deterministic client-order identities and payload fingerprint. "
        "No payload is persisted or transmitted."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Validated", int(result.get("validated_count") or 0))
    c3.metric("Submission", "DISABLED")
    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info("No Section 9C payload preview is available for mapping validation.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "adapter_mapping_validation_id", "broker_payload_preview_id", "candidate_id",
            "strategy_id", "broker_adapter", "entry_client_order_id",
            "protective_client_order_id", "protective_parent_order_id",
            "fingerprint_matches", "duplicate_submission_prevented",
            "adapter_mapping_outcome", "adapter_mapping_reason",
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"View adapter mapping validation for {row.get('candidate_id')}"):
            st.dataframe(list(row.get("adapter_mapping_checks") or []), width="stretch", hide_index=True)
            st.write(f"**Stored fingerprint:** {row.get('payload_fingerprint_sha256') or 'UNAVAILABLE'}")
            st.write(f"**Recomputed fingerprint:** {row.get('recomputed_payload_fingerprint_sha256') or 'UNAVAILABLE'}")
            st.write(f"**Outcome:** {row.get('adapter_mapping_outcome')}")
            st.write(f"**Exact reason:** {row.get('adapter_mapping_reason')}")
            st.write("**Safety:** No broker client, credentials, transport, persistence or submission capability is attached.")


__all__ = [
    "AdapterMappingPolicy",
    "DEFAULT_POLICY",
    "ADAPTER_MAPPING_VERSION",
    "build_adapter_mapping_validation",
    "render_adapter_mapping_validation",
]
