from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class GlobalReadinessShadowReport:
    observations: int
    ready: int
    degraded: int
    blocked: int
    unavailable: int
    signals_seen: int
    signals_scored: int
    orders_opened: int
    orders_skipped: int
    successful_trades: int
    unsuccessful_trades: int
    execution_impact: str = "OBSERVATIONAL_ONLY"

    @property
    def ready_rate_pct(self) -> float:
        return (self.ready / self.observations * 100.0) if self.observations else 0.0


@dataclass(frozen=True)
class GlobalReadinessReplayReport:
    observations: int
    status_counts: Mapping[str, int]
    component_failure_counts: Mapping[str, int]
    blocking_reason_counts: Mapping[str, int]
    advisory_reason_counts: Mapping[str, int]
    outcome_by_status: Mapping[str, Mapping[str, int]]
    execution_impact: str = "OBSERVATIONAL_ONLY"


def _items(value) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return tuple(item for item in value.split(",") if item)
    return tuple(str(item) for item in value)


def build_global_readiness_shadow_report(rows: Iterable[Mapping[str, object]]) -> GlobalReadinessShadowReport:
    items = list(rows)
    statuses = Counter(str(row.get("overall_status") or "UNAVAILABLE") for row in items)
    outcomes = Counter(str(row.get("trade_outcome") or "").upper() for row in items)
    return GlobalReadinessShadowReport(
        observations=len(items),
        ready=statuses["READY"],
        degraded=statuses["DEGRADED"],
        blocked=statuses["BLOCKED"],
        unavailable=statuses["UNAVAILABLE"],
        signals_seen=sum(int(row.get("signals_seen") or 0) for row in items),
        signals_scored=sum(int(row.get("signals_scored") or 0) for row in items),
        orders_opened=sum(int(row.get("orders_opened") or 0) for row in items),
        orders_skipped=sum(int(row.get("orders_skipped") or 0) for row in items),
        successful_trades=outcomes["SUCCESS"] + outcomes["WIN"],
        unsuccessful_trades=outcomes["FAILURE"] + outcomes["LOSS"],
    )


def replay_global_readiness(rows: Iterable[Mapping[str, object]]) -> GlobalReadinessReplayReport:
    items = list(rows)
    status_counts: Counter[str] = Counter()
    component_failures: Counter[str] = Counter()
    blocking: Counter[str] = Counter()
    advisory: Counter[str] = Counter()
    outcome_by_status: dict[str, Counter[str]] = {}
    component_fields = (
        "underlying_status", "option_chain_status", "option_quote_status", "pcr_status",
        "futures_status", "v2_alignment_status", "execution_source_status", "market_hours_status",
    )
    acceptable = {"READY", "APPLICABLE", "NOT_APPLICABLE", "OPEN", "ENTRY_OPEN", "ALIGNED", "ENABLED"}
    for row in items:
        status = str(row.get("overall_status") or "UNAVAILABLE")
        status_counts[status] += 1
        for field in component_fields:
            value = str(row.get(field) or "UNAVAILABLE")
            if value not in acceptable:
                component_failures[f"{field}:{value}"] += 1
        blocking.update(_items(row.get("blocking_reasons")))
        advisory.update(_items(row.get("advisory_reasons")))
        outcome = str(row.get("trade_outcome") or "UNKNOWN").upper()
        outcome_by_status.setdefault(status, Counter())[outcome] += 1
    return GlobalReadinessReplayReport(
        observations=len(items),
        status_counts=dict(status_counts),
        component_failure_counts=dict(component_failures.most_common()),
        blocking_reason_counts=dict(blocking.most_common()),
        advisory_reason_counts=dict(advisory.most_common()),
        outcome_by_status={key: dict(value) for key, value in outcome_by_status.items()},
    )
