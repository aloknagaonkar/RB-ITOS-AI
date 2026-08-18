from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Mapping, Sequence


SHADOW_EVIDENCE_REGISTRY_VERSION = "SHADOW-EVIDENCE-REGISTRY-V1"
_MAX_ROWS = 500
_LOCK = RLock()
_ROWS: list[dict[str, object]] = []


def _text(value: object) -> str:
    return str(value or "").strip()


def _timestamp(row: Mapping[str, object], fallback: object = None) -> str:
    for name in (
        "evaluation_timestamp", "snapshot_timestamp", "bundle_timestamp",
        "refreshed_at", "committee_timestamp", "created_at", "timestamp",
    ):
        value = row.get(name)
        if value not in (None, "", "Unavailable", "UNAVAILABLE"):
            return str(value)
    return str(fallback or "")


def _decision(row: Mapping[str, object]) -> tuple[str, str]:
    if row.get("shadow_handoff_ready") is True or str(
        row.get("shadow_rehearsal_outcome") or ""
    ).upper() == "SHADOW_HANDOFF_READY_DISABLED":
        return "ADMIT_READ_ONLY", "SHADOW_HANDOFF_READY_DISABLED"
    for name in (
        "committee_decision", "committee_outcome", "final_admission_decision",
        "admission_decision", "final_decision", "decision", "outcome",
    ):
        value = str(row.get(name) or "").upper()
        if not value:
            continue
        if any(token in value for token in ("APPROVE", "ADMIT", "READY")) and not any(
            token in value for token in ("NOT_READY", "BLOCK", "REJECT", "WAIT")
        ):
            return "ADMIT_READ_ONLY", f"{name}={value}"
        if any(token in value for token in ("REJECT", "BLOCK", "WAIT", "NOT_ELIGIBLE")):
            return "REJECT_OR_WAIT_READ_ONLY", f"{name}={value}"
    return "NOT_EVALUATED", "NO_TERMINAL_NEW_CHAIN_DECISION"


def _identity(row: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        _text(row.get(name)).upper()
        for name in (
            "strategy_id", "signal_id", "bundle_id", "candidate_id",
            "snapshot_timestamp", "evaluation_timestamp",
        )
    )


def _store(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    copied = [deepcopy(dict(row)) for row in rows]
    with _LOCK:
        for evidence in copied:
            key = _identity(evidence)
            _ROWS[:] = [row for row in _ROWS if _identity(row) != key]
            _ROWS.append(evidence)
        if len(_ROWS) > _MAX_ROWS:
            del _ROWS[:-_MAX_ROWS]
        size = len(_ROWS)
    return {
        "captured_count": len(copied),
        "registry_size": size,
        "registry_version": SHADOW_EVIDENCE_REGISTRY_VERSION,
        "source_read_only": True,
        "persisted": False,
    }


def record_shadow_result(result: Mapping[str, object]) -> dict[str, object]:
    """Capture a completed Section 9E result in bounded process memory."""
    captured: list[dict[str, object]] = []
    for raw in result.get("rows") or []:
        row = dict(raw)
        decision, reason = _decision(row)
        captured.append({
            **row,
            "strategy_id": _text(row.get("strategy_id")),
            "signal_id": _text(row.get("signal_id")),
            "bundle_id": _text(row.get("bundle_id")),
            "candidate_id": _text(row.get("candidate_id")),
            "snapshot_timestamp": _text(row.get("snapshot_timestamp")),
            "evaluation_timestamp": _timestamp(row),
            "new_chain_decision": decision,
            "new_chain_reason": reason,
            "registry_version": SHADOW_EVIDENCE_REGISTRY_VERSION,
            "source_read_only": True,
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })
    return _store(captured)


def record_shadow_evidence(
    *,
    page: str,
    strategy_id: str,
    gate: Mapping[str, object],
    readiness: Mapping[str, object],
    final_admission: Mapping[str, object],
    committee_result: Mapping[str, object],
    shadow_rehearsal: Mapping[str, object],
    evaluation_timestamp: object = None,
) -> dict[str, object]:
    """Capture bounded, process-local Section 4-9F evidence without persistence."""
    sources: Sequence[Mapping[str, object]] = (
        list(shadow_rehearsal.get("rows") or [])
        or list(committee_result.get("rows") or [])
        or list(final_admission.get("rows") or [])
    )
    captured: list[dict[str, object]] = []
    for raw in sources:
        row = dict(raw)
        decision, reason = _decision(row)
        captured.append({
            **row,
            "page": page,
            "strategy_id": _text(row.get("strategy_id") or strategy_id),
            "signal_id": _text(row.get("signal_id") or gate.get("signal_id")),
            "bundle_id": _text(row.get("bundle_id") or gate.get("bundle_id")),
            "candidate_id": _text(row.get("candidate_id")),
            "snapshot_timestamp": _text(
                row.get("snapshot_timestamp") or readiness.get("snapshot_timestamp")
            ),
            "evaluation_timestamp": _timestamp(row, evaluation_timestamp),
            "new_chain_decision": decision,
            "new_chain_reason": reason,
            "registry_version": SHADOW_EVIDENCE_REGISTRY_VERSION,
            "source_read_only": True,
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })
    return _store(captured)


def read_shadow_evidence() -> list[dict[str, object]]:
    with _LOCK:
        return deepcopy(_ROWS)


def clear_shadow_evidence_for_tests() -> None:
    with _LOCK:
        _ROWS.clear()


__all__ = [
    "SHADOW_EVIDENCE_REGISTRY_VERSION",
    "record_shadow_result",
    "record_shadow_evidence",
    "read_shadow_evidence",
    "clear_shadow_evidence_for_tests",
]
