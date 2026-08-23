from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json


def canonical_reservation_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def reservation_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reservation identity timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def build_reservation_id(
    *,
    bundle_id: str,
    idempotency_key: str,
    owner_id: str,
    lease_epoch: datetime,
) -> str:
    payload = canonical_reservation_json(
        {
            "bundle_id": bundle_id,
            "idempotency_key": idempotency_key,
            "owner_id": owner_id,
            "lease_epoch_utc": _utc_iso(lease_epoch),
            "schema_version": "1.0",
        }
    )
    return f"RBV2-RESERVATION-{reservation_sha256(payload)[:32].upper()}"


def build_reservation_event_id(
    *,
    reservation_id: str,
    event_type: str,
    event_timestamp: datetime,
    owner_id: str,
    reason_code: str,
) -> str:
    payload = canonical_reservation_json(
        {
            "reservation_id": reservation_id,
            "event_type": event_type,
            "event_timestamp_utc": _utc_iso(event_timestamp),
            "owner_id": owner_id,
            "reason_code": reason_code,
        }
    )
    return f"RBV2-RESERVATION-EVENT-{reservation_sha256(payload)[:32].upper()}"
