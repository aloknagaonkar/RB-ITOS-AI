from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Mapping, Sequence

from red_bar_lab.ui.strategy_attribution import normalize_strategy_source


PAPER_ARCHITECTURE_COMPARISON_VERSION = "PAPER-ARCHITECTURE-COMPARISON-V1"
COMPARISON_CATEGORIES = (
    "AGREE_EXECUTE",
    "AGREE_REJECT",
    "LEGACY_ONLY_EXECUTE",
    "NEW_ONLY_ADMIT",
    "NOT_COMPARABLE",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _parse_timestamp(value: object) -> datetime | None:
    text = _text(value)
    if not text or text.upper() in {"UNAVAILABLE", "NOT RECORDED"}:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _legacy_timestamp(row: Mapping[str, object]) -> datetime | None:
    for name in (
        "entry_timestamp", "execution_timestamp", "opened_at", "created_at",
        "updated_at", "timestamp",
    ):
        parsed = _parse_timestamp(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _evidence_timestamp(row: Mapping[str, object]) -> datetime | None:
    for name in (
        "evaluation_timestamp", "snapshot_timestamp", "bundle_timestamp",
        "committee_timestamp", "created_at", "timestamp",
    ):
        parsed = _parse_timestamp(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _strategy(row: Mapping[str, object]) -> str:
    source = normalize_strategy_source(dict(row))
    if source != "UNATTRIBUTED_LEGACY":
        return source
    return _text(row.get("strategy_id") or row.get("strategy_source")).upper()


def _new_admitted(row: Mapping[str, object]) -> bool:
    return _text(row.get("new_chain_decision")).upper() == "ADMIT_READ_ONLY"


def _match_score(order: Mapping[str, object], evidence: Mapping[str, object]) -> int | None:
    order_time = _legacy_timestamp(order)
    evidence_time = _evidence_timestamp(evidence)
    if order_time is None or evidence_time is None:
        return None
    try:
        if evidence_time > order_time:
            return None
    except TypeError:
        return None
    if order_time.date() != evidence_time.date():
        return None

    score = 0
    order_strategy = _strategy(order)
    evidence_strategy = _strategy(evidence)
    if order_strategy and evidence_strategy:
        if order_strategy != evidence_strategy:
            return None
        score += 4

    for name, points in (("signal_id", 8), ("bundle_id", 5), ("candidate_id", 6)):
        left = _text(order.get(name)).upper()
        right = _text(evidence.get(name)).upper()
        if left and right:
            if left != right:
                return None
            score += points

    order_symbol = _text(order.get("tradingsymbol") or order.get("candidate_symbol")).upper()
    evidence_symbol = _text(
        evidence.get("trading_symbol") or evidence.get("tradingsymbol")
        or evidence.get("candidate_symbol")
    ).upper()
    if order_symbol and evidence_symbol:
        if order_symbol != evidence_symbol:
            return None
        score += 3

    return score if score >= 8 else None


def build_paper_architecture_comparison(
    legacy_orders: Sequence[Mapping[str, object]],
    shadow_evidence: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Compare executed legacy orders with time-safe read-only Section 4-9F evidence."""
    orders = [dict(row) for row in legacy_orders]
    evidence_rows = [dict(row) for row in shadow_evidence]
    used: set[int] = set()
    rows: list[dict[str, object]] = []

    for order in orders:
        candidates: list[tuple[int, datetime, int, dict[str, object]]] = []
        for index, evidence in enumerate(evidence_rows):
            if index in used:
                continue
            score = _match_score(order, evidence)
            timestamp = _evidence_timestamp(evidence)
            if score is not None and timestamp is not None:
                candidates.append((score, timestamp, index, evidence))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

        if not candidates:
            category = "NOT_COMPARABLE"
            evidence = {}
            reason = "NO_TIME_SAFE_IDENTITY_MATCHED_SECTION_4_9F_EVIDENCE"
        else:
            _, _, index, evidence = candidates[0]
            used.add(index)
            if _new_admitted(evidence):
                category = "AGREE_EXECUTE"
                reason = "LEGACY_EXECUTED_AND_NEW_CHAIN_ADMITTED_READ_ONLY"
            else:
                category = "LEGACY_ONLY_EXECUTE"
                reason = "LEGACY_EXECUTED_BUT_NEW_CHAIN_DID_NOT_ADMIT"

        rows.append({
            "comparison_category": category,
            "comparison_reason": reason,
            "order_id": order.get("order_id"),
            "legacy_strategy": _strategy(order),
            "legacy_signal_id": order.get("signal_id"),
            "legacy_bundle_id": order.get("bundle_id"),
            "legacy_candidate_id": order.get("candidate_id"),
            "legacy_contract": order.get("tradingsymbol"),
            "legacy_decision_timestamp": _text(
                order.get("entry_timestamp") or order.get("execution_timestamp")
            ),
            "legacy_decision": "EXECUTED",
            "new_strategy": _strategy(evidence) if evidence else None,
            "new_signal_id": evidence.get("signal_id") if evidence else None,
            "new_bundle_id": evidence.get("bundle_id") if evidence else None,
            "new_candidate_id": evidence.get("candidate_id") if evidence else None,
            "new_evaluation_timestamp": _text(
                evidence.get("evaluation_timestamp") or evidence.get("snapshot_timestamp")
            ) if evidence else None,
            "new_chain_decision": evidence.get("new_chain_decision") if evidence else "NOT_AVAILABLE",
            "new_chain_reason": evidence.get("new_chain_reason") if evidence else reason,
            "source_read_only": True,
            "persisted": False,
            "execution_allowed": False,
        })

    for index, evidence in enumerate(evidence_rows):
        if index in used or not _new_admitted(evidence):
            continue
        rows.append({
            "comparison_category": "NEW_ONLY_ADMIT",
            "comparison_reason": "NEW_CHAIN_ADMITTED_WITHOUT_MATCHED_LEGACY_EXECUTION",
            "order_id": None,
            "legacy_strategy": None,
            "legacy_signal_id": None,
            "legacy_bundle_id": None,
            "legacy_candidate_id": None,
            "legacy_contract": None,
            "legacy_decision_timestamp": None,
            "legacy_decision": "NOT_FOUND",
            "new_strategy": _strategy(evidence),
            "new_signal_id": evidence.get("signal_id"),
            "new_bundle_id": evidence.get("bundle_id"),
            "new_candidate_id": evidence.get("candidate_id"),
            "new_evaluation_timestamp": _text(
                evidence.get("evaluation_timestamp") or evidence.get("snapshot_timestamp")
            ),
            "new_chain_decision": evidence.get("new_chain_decision"),
            "new_chain_reason": evidence.get("new_chain_reason"),
            "source_read_only": True,
            "persisted": False,
            "execution_allowed": False,
        })

    counts = Counter(str(row["comparison_category"]) for row in rows)
    return {
        "comparison_version": PAPER_ARCHITECTURE_COMPARISON_VERSION,
        "rows": rows,
        "counts": {category: counts.get(category, 0) for category in COMPARISON_CATEGORIES},
        "legacy_order_count": len(orders),
        "shadow_evidence_count": len(evidence_rows),
        "comparable_count": sum(
            counts.get(name, 0)
            for name in ("AGREE_EXECUTE", "AGREE_REJECT", "LEGACY_ONLY_EXECUTE")
        ),
        "source_read_only": True,
        "persisted": False,
        "execution_allowed": False,
    }


__all__ = [
    "PAPER_ARCHITECTURE_COMPARISON_VERSION",
    "COMPARISON_CATEGORIES",
    "build_paper_architecture_comparison",
]
