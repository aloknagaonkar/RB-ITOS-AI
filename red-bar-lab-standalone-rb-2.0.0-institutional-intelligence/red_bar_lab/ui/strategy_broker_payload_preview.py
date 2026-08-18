from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Mapping

import streamlit as st


BROKER_PAYLOAD_PREVIEW_VERSION = "BROKER-PAYLOAD-PREVIEW-V1"


@dataclass(frozen=True)
class BrokerPayloadPreviewPolicy:
    policy_version: str = BROKER_PAYLOAD_PREVIEW_VERSION
    adapter_name: str = "GENERIC_BROKER_DISABLED"
    product_type: str = "INTRADAY"
    entry_transaction_type: str = "BUY"
    protective_transaction_type: str = "SELL"
    entry_order_type: str = "LIMIT"
    protective_order_type: str = "STOP_LOSS_LIMIT"
    validity: str = "DAY"
    submission_enabled: bool = False


DEFAULT_POLICY = BrokerPayloadPreviewPolicy()

_SENSITIVE_KEYS = frozenset({
    "access_token", "api_key", "api_secret", "client_id", "account_id",
    "password", "pin", "totp", "authorization", "cookie", "endpoint",
})


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _present(value: object) -> bool:
    return value not in (None, "", "Unavailable", "UNAVAILABLE", "Not created")


def _payload_id(row: Mapping[str, object]) -> str:
    raw = "|".join(str(row.get(name) or "") for name in (
        "order_specification_id", "committee_id", "strategy_id", "bundle_id",
        "signal_id", "candidate_id", "exchange", "instrument_token",
        "instrument_key", "trading_symbol", "order_quantity", "limit_price",
        "protective_stop_trigger",
    ))
    return f"PAYLOAD-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).strip().lower() in _SENSITIVE_KEYS:
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, (list, tuple, set)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def build_broker_payload_preview(
    order_specification: Mapping[str, object],
    *,
    policy: BrokerPayloadPreviewPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Translate ready order specifications into inert, credential-free payload previews."""
    rows: list[dict[str, object]] = []
    for raw in order_specification.get("rows") or []:
        row = dict(raw)
        waits: list[str] = []
        checks: list[dict[str, object]] = []

        def check(name: str, passed: bool, reason: str) -> None:
            checks.append({"check": name, "status": "PASS" if passed else "WAIT", "detail": reason})
            if not passed:
                waits.append(reason)

        spec_ready = (
            str(row.get("order_specification_outcome") or "") == "ORDER_SPEC_READY_READ_ONLY"
            and row.get("order_prepared_read_only") is True
        )
        check("Order-specification authority", spec_ready, "ORDER_SPECIFICATION_NOT_READY")

        identity_ok = all(_present(row.get(name)) for name in (
            "strategy_id", "bundle_id", "signal_id", "candidate_id",
            "exchange", "trading_symbol",
        )) and (_present(row.get("instrument_token")) or _present(row.get("instrument_key")))
        check("Broker instrument identity", identity_ok, "BROKER_INSTRUMENT_IDENTITY_INCOMPLETE")

        quantity = _number(row.get("order_quantity"))
        limit_price = _number(row.get("limit_price"))
        stop_trigger = _number(row.get("protective_stop_trigger"))
        quantity_ok = quantity is not None and quantity > 0 and quantity.is_integer()
        price_ok = limit_price is not None and limit_price > 0
        stop_ok = stop_trigger is not None and stop_trigger > 0 and limit_price is not None and stop_trigger < limit_price
        check("Payload quantity", quantity_ok, "PAYLOAD_QUANTITY_INVALID")
        check("Payload entry price", price_ok, "PAYLOAD_LIMIT_PRICE_INVALID")
        check("Payload protective stop", stop_ok, "PAYLOAD_PROTECTIVE_STOP_INVALID")

        preview_id = _payload_id(row)
        entry_payload = {
            "preview_only": True,
            "submission_enabled": False,
            "adapter": policy.adapter_name,
            "client_order_id": f"{preview_id}-ENTRY",
            "exchange": row.get("exchange"),
            "instrument_token": row.get("instrument_token"),
            "instrument_key": row.get("instrument_key"),
            "trading_symbol": row.get("trading_symbol"),
            "transaction_type": policy.entry_transaction_type,
            "product_type": policy.product_type,
            "order_type": policy.entry_order_type,
            "validity": policy.validity,
            "quantity": int(quantity) if quantity_ok else None,
            "price": limit_price,
            "trigger_price": None,
            "tag": str(row.get("strategy_id") or "")[:20],
        }
        protective_payload = {
            "preview_only": True,
            "submission_enabled": False,
            "adapter": policy.adapter_name,
            "client_order_id": f"{preview_id}-STOP",
            "parent_preview_order_id": f"{preview_id}-ENTRY",
            "activation_condition": "AFTER_ENTRY_FILL",
            "exchange": row.get("exchange"),
            "instrument_token": row.get("instrument_token"),
            "instrument_key": row.get("instrument_key"),
            "trading_symbol": row.get("trading_symbol"),
            "transaction_type": policy.protective_transaction_type,
            "product_type": policy.product_type,
            "order_type": policy.protective_order_type,
            "validity": policy.validity,
            "quantity": int(quantity) if quantity_ok else None,
            "price": stop_trigger,
            "trigger_price": stop_trigger,
            "tag": str(row.get("strategy_id") or "")[:20],
        }
        payload = {
            "preview_id": preview_id,
            "preview_version": policy.policy_version,
            "submission_enabled": False,
            "broker_client_attached": False,
            "credentials_attached": False,
            "entry_order": entry_payload,
            "protective_stop_order": protective_payload,
        }
        sensitive_free = not _contains_sensitive_key(payload)
        check("Credential and transport exclusion", sensitive_free, "SENSITIVE_OR_TRANSPORT_FIELD_PRESENT")
        hard_disabled = (
            policy.submission_enabled is False
            and payload["submission_enabled"] is False
            and entry_payload["submission_enabled"] is False
            and protective_payload["submission_enabled"] is False
            and payload["broker_client_attached"] is False
        )
        check("Submission hard-disable", hard_disabled, "PAYLOAD_SUBMISSION_NOT_HARD_DISABLED")

        outcome = "PAYLOAD_PREVIEW_READY_DISABLED" if not waits else "WAIT"
        payload_fingerprint = _fingerprint(payload) if not waits else None
        rows.append({
            **row,
            "broker_payload_preview_id": preview_id,
            "broker_payload_preview_outcome": outcome,
            "broker_payload_preview_reason": ", ".join(waits) if waits else "DISABLED_CREDENTIAL_FREE_PAYLOAD_PREVIEW_COMPLETE",
            "broker_payload_preview_checks": checks,
            "broker_payload_preview_version": policy.policy_version,
            "broker_adapter": policy.adapter_name,
            "entry_payload_preview": entry_payload,
            "protective_payload_preview": protective_payload,
            "payload_preview": payload,
            "payload_fingerprint_sha256": payload_fingerprint,
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
                "Section 9D may validate adapter mapping and idempotency without submission."
                if outcome == "PAYLOAD_PREVIEW_READY_DISABLED"
                else "Resolve the exact payload-preview wait reason."
            ),
        })

    ready = sum(row["broker_payload_preview_outcome"] == "PAYLOAD_PREVIEW_READY_DISABLED" for row in rows)
    waiting = sum(row["broker_payload_preview_outcome"] == "WAIT" for row in rows)
    return {
        "outcome": "PAYLOAD_PREVIEW_READY_DISABLED" if ready else "WAIT" if waiting else "NOT_ELIGIBLE",
        "rows": rows,
        "ready_count": ready,
        "waiting_count": waiting,
        "broker_payload_preview_version": policy.policy_version,
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


def render_broker_payload_preview(result: Mapping[str, object]) -> None:
    st.markdown("#### 9C. Disabled Broker Payload Preview")
    st.caption(
        "Translates ready order specifications into credential-free, transport-free previews. "
        "Submission is hard-disabled and no broker client is attached."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Ready previews", int(result.get("ready_count") or 0))
    c3.metric("Submission", "DISABLED")
    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info("No Section 9B order specification is available for payload preview.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "broker_payload_preview_id", "order_specification_id", "candidate_id",
            "strategy_id", "broker_adapter", "exchange", "trading_symbol",
            "order_quantity", "limit_price", "protective_stop_trigger",
            "broker_payload_preview_outcome", "broker_payload_preview_reason",
            "submission_enabled",
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"View disabled payload preview for {row.get('candidate_id')}"):
            st.dataframe(list(row.get("broker_payload_preview_checks") or []), width="stretch", hide_index=True)
            st.json(row.get("payload_preview") or {})
            st.write(f"**Fingerprint:** {row.get('payload_fingerprint_sha256') or 'UNAVAILABLE'}")
            st.write(f"**Outcome:** {row.get('broker_payload_preview_outcome')}")
            st.write(f"**Exact reason:** {row.get('broker_payload_preview_reason')}")
            st.write("**Safety:** Credentials, transport configuration, broker client and submission capability are absent.")


__all__ = [
    "BrokerPayloadPreviewPolicy",
    "DEFAULT_POLICY",
    "BROKER_PAYLOAD_PREVIEW_VERSION",
    "build_broker_payload_preview",
    "render_broker_payload_preview",
]
