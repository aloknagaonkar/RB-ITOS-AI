from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Mapping

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome, Direction, EntryType


def canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_sha256(payload_json: str) -> str:
    return sha256(payload_json.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("identity timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _identity(prefix: str, payload: Mapping[str, object]) -> str:
    digest = payload_sha256(canonical_json(payload))
    return f"{prefix}-{digest[:24]}"


def build_canonical_resolution_id(
    *,
    strategy_id: str,
    strategy_version: str,
    instrument_key: str,
    trading_date: date,
    source_replay_id: str,
    evaluation_timestamp: datetime,
    entry_type: EntryType | None,
    direction: Direction | None,
    admission_outcome: AdmissionOutcome,
) -> str:
    return _identity(
        "RBV2-RESOLUTION",
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "instrument_key": instrument_key,
            "trading_date": trading_date.isoformat(),
            "source_replay_id": source_replay_id,
            "evaluation_timestamp": _timestamp(evaluation_timestamp),
            "entry_type": entry_type.value if entry_type else "WAITING",
            "direction": direction.value if direction else "NONE",
            "admission_outcome": admission_outcome.value,
        },
    )


def build_canonical_bundle_event_id(
    *,
    bundle_id: str,
    event_type: str,
    event_timestamp: datetime,
    source: str,
    reason_code: str,
) -> str:
    return _identity(
        "RBV2-BUNDLE-EVENT",
        {
            "bundle_id": bundle_id,
            "event_type": event_type,
            "event_timestamp": _timestamp(event_timestamp),
            "source": source,
            "reason_code": reason_code,
        },
    )
