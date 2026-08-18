from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Mapping, Sequence


PRIORITY_VERSION = "ADMISSION-PRIORITY-V1"


@dataclass(frozen=True)
class AdmissionPriorityPolicy:
    policy_version: str = PRIORITY_VERSION
    role_priority: Mapping[str, int] = field(default_factory=lambda: {
        "PRIMARY": 10,
        "ENTRY_1": 10,
        "RANK_1": 10,
        "SECONDARY": 20,
        "ENTRY_2": 20,
        "RANK_2": 20,
    })
    default_role_priority: int = 50


DEFAULT_POLICY = AdmissionPriorityPolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _text(value: object) -> str:
    return str(value or "").strip().upper()


def _first_number(row: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _number(row.get(name))
        if value is not None:
            return value
    return None


def _timestamp(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return float("inf")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")


def _historical_rank(row: Mapping[str, object]) -> int:
    combined = _text(row.get("combined_outcome"))
    authority = _text(row.get("historical_authority"))
    if combined == "FORWARD" or authority == "SUPPORTED":
        return 0
    if combined == "FORWARD_WITHOUT_HISTORICAL_SUPPORT" or authority == "LIMITED":
        return 1
    return 2


def priority_key(
    row: Mapping[str, object],
    *,
    policy: AdmissionPriorityPolicy = DEFAULT_POLICY,
) -> tuple[object, ...]:
    explicit = _number(row.get("admission_priority"))
    explicit_rank = explicit if explicit is not None else float("inf")
    role = _text(row.get("role") or row.get("contract_role"))
    role_rank = int(policy.role_priority.get(role, policy.default_role_priority))
    candidate_score = _first_number(row, "candidate_score", "handoff_score", "candidate_readiness_score")
    contract_score = _first_number(row, "ranking_score", "contract_score", "selection_score", "total_score")
    bundle_time = _timestamp(row.get("bundle_timestamp") or row.get("signal_timestamp") or row.get("created_at"))
    candidate_id = str(row.get("candidate_id") or "")
    return (
        explicit_rank,
        role_rank,
        -(candidate_score if candidate_score is not None else float("-inf")),
        -(contract_score if contract_score is not None else float("-inf")),
        _historical_rank(row),
        bundle_time,
        candidate_id,
    )


def _reason(row: Mapping[str, object], policy: AdmissionPriorityPolicy) -> str:
    role = _text(row.get("role") or row.get("contract_role")) or "UNSPECIFIED"
    explicit = _number(row.get("admission_priority"))
    candidate_score = _first_number(row, "candidate_score", "handoff_score", "candidate_readiness_score")
    contract_score = _first_number(row, "ranking_score", "contract_score", "selection_score", "total_score")
    historical = "SUPPORTED" if _historical_rank(row) == 0 else "LIMITED" if _historical_rank(row) == 1 else "NOT_APPLICABLE"
    parts = []
    if explicit is not None:
        parts.append(f"explicit={explicit:g}")
    parts.append(f"role={role}:{policy.role_priority.get(role, policy.default_role_priority)}")
    parts.append(f"candidate_score={candidate_score if candidate_score is not None else 'UNAVAILABLE'}")
    parts.append(f"contract_score={contract_score if contract_score is not None else 'UNAVAILABLE'}")
    parts.append(f"historical={historical}")
    return "; ".join(parts)


def prioritize_candidates(
    rows: Sequence[Mapping[str, object]] | None,
    *,
    policy: AdmissionPriorityPolicy = DEFAULT_POLICY,
) -> list[dict[str, object]]:
    """Return read-only candidate copies in deterministic account-allocation order."""
    ordered = sorted((dict(row) for row in (rows or [])), key=lambda row: priority_key(row, policy=policy))
    result = []
    for rank, row in enumerate(ordered, start=1):
        result.append({
            **row,
            "admission_priority_rank": rank,
            "admission_priority_reason": _reason(row, policy),
            "admission_priority_version": policy.policy_version,
            "priority_source_read_only": True,
        })
    return result


__all__ = [
    "AdmissionPriorityPolicy",
    "DEFAULT_POLICY",
    "PRIORITY_VERSION",
    "priority_key",
    "prioritize_candidates",
]
