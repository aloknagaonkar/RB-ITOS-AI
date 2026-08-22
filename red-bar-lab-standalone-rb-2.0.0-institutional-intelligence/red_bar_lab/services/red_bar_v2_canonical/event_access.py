from __future__ import annotations

from datetime import datetime
from typing import Mapping

from .exceptions import LegacyMappingError

_TOP_LEVEL_FIELDS = frozenset(
    {
        "timestamp",
        "event_type",
        "direction",
        "option_side",
        "admission_code",
        "candidate_allowed",
        "trade_id",
    }
)


def event_details(event: object | None) -> Mapping[str, object]:
    """Return the real ReplayEvent details mapping without flattening it."""
    if event is None:
        return {}
    details = getattr(event, "details", None)
    if details is None and isinstance(event, Mapping):
        details = event.get("details")
    if details is None:
        return {}
    if not isinstance(details, Mapping):
        raise LegacyMappingError("legacy replay event details must be a mapping")
    return details


def event_value(event: object | None, field: str, default: object = None) -> object:
    """Read a ReplayEvent field from its authoritative owner."""
    if event is None:
        return default
    if field in _TOP_LEVEL_FIELDS:
        if isinstance(event, Mapping):
            return event.get(field, default)
        return getattr(event, field, default)
    return event_details(event).get(field, default)


def event_conditions(event: object | None) -> Mapping[str, object]:
    value = event_value(event, "conditions", {})
    if not isinstance(value, Mapping):
        raise LegacyMappingError("legacy replay event conditions must be a mapping")
    return value


def event_text(event: object | None, field: str) -> str | None:
    value = event_value(event, field)
    value = getattr(value, "value", value)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LegacyMappingError(f"legacy {field} must be a non-empty string when present")
    return value


def event_bool(event: object | None, field: str) -> bool | None:
    value = event_value(event, field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise LegacyMappingError(f"legacy {field} must be a bool when present")
    return value


def event_datetime(event: object | None, field: str) -> datetime | None:
    value = event_value(event, field)
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LegacyMappingError(f"legacy {field} must be an ISO datetime") from exc
    else:
        raise LegacyMappingError(f"legacy {field} must be a datetime or ISO string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LegacyMappingError(f"legacy {field} must be timezone-aware")
    return parsed
