from __future__ import annotations

from collections.abc import Iterable
from typing import Any


NOT_ELIGIBLE_STATES = {
    "NOT_ELIGIBLE",
    "REJECTED",
    "CONFIRMATION_FAILED",
    "TIMEOUT",
}


def _value(row: Any, *names: str) -> object:
    if isinstance(row, dict):
        for name in names:
            if name in row:
                return row.get(name)
        return None
    for name in names:
        if hasattr(row, name):
            return getattr(row, name)
    return None


def candidate_state(row: Any) -> str:
    value = _value(
        row,
        "lifecycle_state",
        "candidate_state",
        "final_outcome",
        "state",
    )
    return str(value or "").strip().upper()


def is_not_eligible(row: Any) -> bool:
    """Return True when a candidate belongs only in investigation history."""
    archived = bool(_value(row, "archived", "is_archived"))
    state = candidate_state(row)
    return archived or state in NOT_ELIGIBLE_STATES


def active_candidate_rows(rows: Iterable[Any]) -> list[Any]:
    """Rows allowed in active rank, opportunity and execution screens."""
    return [row for row in rows if not is_not_eligible(row)]


def investigation_candidate_rows(rows: Iterable[Any]) -> list[Any]:
    """Rows retained for diagnostics and historical investigation."""
    return [row for row in rows if is_not_eligible(row)]


def archive_payload(
    *,
    evaluation: Any,
    candidate: Any = None,
    decision_timestamp: str | None = None,
) -> dict[str, object]:
    """Build a stable investigation record without mutating execution logic."""
    contract = getattr(candidate, "contract", None) if candidate is not None else None
    return {
        "candidate_id": _value(evaluation, "candidate_id"),
        "signal_id": _value(evaluation, "signal_id"),
        "tradingsymbol": (
            getattr(contract, "tradingsymbol", None)
            if contract is not None
            else _value(evaluation, "candidate_symbol")
        ),
        "instrument_token": (
            getattr(contract, "instrument_token", None)
            if contract is not None
            else _value(evaluation, "instrument_token")
        ),
        "lifecycle_state": "NOT_ELIGIBLE",
        "final_outcome": "NOT_ELIGIBLE",
        "archived": True,
        "visible_in_active_views": False,
        "reason": _value(evaluation, "reason"),
        "action": _value(evaluation, "action"),
        "health_score": _value(evaluation, "health_score"),
        "market_drift": _value(evaluation, "market_drift"),
        "created_session": _value(evaluation, "created_session"),
        "current_session": _value(evaluation, "current_session"),
        "decision_timestamp": decision_timestamp,
        "order_id": None,
    }
