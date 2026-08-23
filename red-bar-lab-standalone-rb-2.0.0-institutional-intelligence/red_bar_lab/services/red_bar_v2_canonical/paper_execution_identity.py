from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}-{payload_sha256(canonical_json(value))[:40].upper()}"


def build_execution_id(
    *,
    bundle_id: str,
    reservation_id: str,
    contract_instrument_key: str,
    quantity: int,
    order_side: str,
    order_type: str,
    limit_price: float | None,
) -> str:
    return _identity(
        "RBV2-PAPER-EXECUTION",
        {
            "bundle_id": bundle_id,
            "reservation_id": reservation_id,
            "contract_instrument_key": contract_instrument_key,
            "quantity": quantity,
            "order_side": order_side,
            "order_type": order_type,
            "limit_price": limit_price,
            "schema_version": "1.0",
        },
    )


def build_command_id(*, execution_id: str, created_at: datetime) -> str:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return _identity(
        "RBV2-PAPER-COMMAND",
        {
            "execution_id": execution_id,
            "created_at": created_at.astimezone(timezone.utc).isoformat(),
            "schema_version": "1.0",
        },
    )


def build_execution_event_id(
    *,
    execution_id: str,
    event_type: str,
    event_timestamp: datetime,
    reason_code: str,
) -> str:
    if event_timestamp.tzinfo is None or event_timestamp.utcoffset() is None:
        raise ValueError("event_timestamp must be timezone-aware")
    return _identity(
        "RBV2-PAPER-EVENT",
        {
            "execution_id": execution_id,
            "event_type": event_type,
            "event_timestamp": event_timestamp.astimezone(timezone.utc).isoformat(),
            "reason_code": reason_code,
            "schema_version": "1.0",
        },
    )
