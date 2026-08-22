from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Mapping

from .enums import Direction, EntryType, OptionSide
from .exceptions import DomainValidationError


def _normalized_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError("identity timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_identity(prefix: str, fields: Mapping[str, object]) -> str:
    """Return a readable deterministic identifier from canonical JSON bytes."""
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:24].upper()
    return f"{prefix}-{digest}"


def build_red_bar_v2_signal_id(
    *,
    strategy_version: str,
    instrument_key: str,
    trading_date: date,
    reference_id: str,
    evaluation_timestamp: datetime,
    entry_type: EntryType,
    direction: Direction,
) -> str:
    """Build a stable signal identifier normalized to UTC."""
    if not strategy_version.strip() or not instrument_key.strip() or not reference_id.strip():
        raise DomainValidationError("signal identity text fields must be non-empty")
    return _canonical_identity(
        "RBV2-SIGNAL",
        {
            "strategy_id": "RED_BAR_V2",
            "strategy_version": strategy_version,
            "instrument_key": instrument_key,
            "trading_date": trading_date.isoformat(),
            "reference_id": reference_id,
            "evaluation_timestamp": _normalized_datetime(evaluation_timestamp),
            "entry_type": entry_type.value,
            "direction": direction.value,
        },
    )


def build_red_bar_v2_bundle_id(*, signal_id: str, schema_version: str) -> str:
    """Build a stable bundle identifier from signal and schema identity."""
    if not signal_id.strip() or not schema_version.strip():
        raise DomainValidationError("bundle identity fields must be non-empty")
    return _canonical_identity(
        "RBV2-BUNDLE",
        {"signal_id": signal_id, "schema_version": schema_version},
    )


def build_red_bar_v2_idempotency_key(*, signal_id: str, option_side: OptionSide) -> str:
    """Build a stable execution-neutral idempotency key."""
    if not signal_id.strip():
        raise DomainValidationError("signal_id must be non-empty")
    return _canonical_identity(
        "RBV2-IDEMPOTENCY",
        {"signal_id": signal_id, "option_side": option_side.value},
    )
