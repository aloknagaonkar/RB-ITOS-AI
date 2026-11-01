from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Literal

from .domain import Snapshot

MODEL = "LIVE_OBSERVATIONAL_DATA_HEALTH_V1"

HealthState = Literal[
    "HEALTHY",
    "DEGRADED",
    "UNHEALTHY",
    "STALE",
    "MISSING",
    "OUT_OF_ORDER",
]

CRITICAL_STATES = {"UNHEALTHY", "STALE", "MISSING", "OUT_OF_ORDER"}


@dataclass(frozen=True)
class HealthIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class SnapshotHealthReport:
    model: str
    state: HealthState
    checked_at: str
    received_at: str
    collection_latency_ms: float
    spot_feed_age_ms: float | None
    oi_source_age_ms: float | None
    quote_timestamp_available: int
    quote_timestamp_total: int
    stale_quote_count: int
    missing_oi_count: int
    missing_ltp_count: int
    duplicate_contract_count: int
    issues: tuple[HealthIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["issues"] = [asdict(x) for x in self.issues]
        return d


@dataclass(frozen=True)
class DataHealthConfig:
    max_collection_latency_ms: float = 5000.0
    max_spot_feed_age_ms: float = 5000.0
    max_oi_source_age_ms: float = 15000.0
    max_quote_age_ms: float = 15000.0
    degraded_missing_oi_ratio: float = 0.10
    unhealthy_missing_oi_ratio: float = 0.30


def _age_ms(later: datetime, earlier: datetime | None) -> float | None:
    if earlier is None:
        return None
    return (later - earlier).total_seconds() * 1000.0


def evaluate_snapshot_health(
    snapshot: Snapshot,
    *,
    config: DataHealthConfig | None = None,
) -> SnapshotHealthReport:
    c = config or DataHealthConfig()
    issues: list[HealthIssue] = []

    collection_latency = _age_ms(snapshot.received_at, snapshot.started_at) or 0.0
    if collection_latency < 0:
        issues.append(HealthIssue(
            "COLLECTION_TIME_REVERSED", "CRITICAL",
            "received_at precedes started_at",
        ))
    elif collection_latency > c.max_collection_latency_ms:
        issues.append(HealthIssue(
            "COLLECTION_LATENCY_HIGH", "WARN",
            f"collection latency {collection_latency:.0f}ms exceeds {c.max_collection_latency_ms:.0f}ms",
        ))

    spot_age = _age_ms(snapshot.received_at, snapshot.spot_feed_at)
    if snapshot.spot_feed_at is None:
        issues.append(HealthIssue(
            "SPOT_FEED_TIMESTAMP_MISSING", "CRITICAL",
            "spot_feed_at is missing",
        ))
    elif spot_age is not None and spot_age < 0:
        issues.append(HealthIssue(
            "SPOT_FEED_FROM_FUTURE", "CRITICAL",
            "spot_feed_at is later than received_at",
        ))
    elif spot_age is not None and spot_age > c.max_spot_feed_age_ms:
        issues.append(HealthIssue(
            "SPOT_FEED_STALE", "CRITICAL",
            f"spot feed age {spot_age:.0f}ms exceeds {c.max_spot_feed_age_ms:.0f}ms",
        ))

    oi_age = _age_ms(snapshot.received_at, snapshot.oi_source_at)
    if snapshot.oi_source_at is None:
        issues.append(HealthIssue(
            "OI_SOURCE_TIMESTAMP_MISSING", "WARN",
            "oi_source_at is missing",
        ))
    elif oi_age is not None and oi_age < 0:
        issues.append(HealthIssue(
            "OI_SOURCE_FROM_FUTURE", "CRITICAL",
            "oi_source_at is later than received_at",
        ))
    elif oi_age is not None and oi_age > c.max_oi_source_age_ms:
        issues.append(HealthIssue(
            "OI_SOURCE_STALE", "CRITICAL",
            f"OI source age {oi_age:.0f}ms exceeds {c.max_oi_source_age_ms:.0f}ms",
        ))

    identities = [(x.strike, x.side) for x in snapshot.catalog]
    duplicate_contract_count = len(identities) - len(set(identities))

    quote_timestamp_available = 0
    stale_quote_count = 0
    missing_oi_count = 0
    missing_ltp_count = 0

    for q in snapshot.quotes:
        if q.oi is None:
            missing_oi_count += 1
        if q.ltp is None:
            missing_ltp_count += 1
        if q.quote_timestamp is not None:
            quote_timestamp_available += 1
            age = _age_ms(snapshot.received_at, q.quote_timestamp)
            if age is not None and (age < 0 or age > c.max_quote_age_ms):
                stale_quote_count += 1

    total_quotes = len(snapshot.quotes)
    missing_oi_ratio = (
        missing_oi_count / total_quotes if total_quotes else 1.0
    )

    if total_quotes == 0:
        issues.append(HealthIssue(
            "OPTION_QUOTES_MISSING", "CRITICAL",
            "snapshot contains no option quotes",
        ))
    elif missing_oi_ratio >= c.unhealthy_missing_oi_ratio:
        issues.append(HealthIssue(
            "OPTION_OI_COVERAGE_BAD", "CRITICAL",
            f"{missing_oi_ratio:.1%} option quotes are missing OI",
        ))
    elif missing_oi_ratio >= c.degraded_missing_oi_ratio:
        issues.append(HealthIssue(
            "OPTION_OI_COVERAGE_DEGRADED", "WARN",
            f"{missing_oi_ratio:.1%} option quotes are missing OI",
        ))

    if stale_quote_count:
        issues.append(HealthIssue(
            "OPTION_QUOTES_STALE", "CRITICAL",
            f"{stale_quote_count} option quote timestamps are stale/future",
        ))

    if duplicate_contract_count:
        issues.append(HealthIssue(
            "DUPLICATE_CONTRACT_IDENTITY", "CRITICAL",
            f"{duplicate_contract_count} duplicate strike/side identities",
        ))

    critical_codes = {x.code for x in issues if x.severity == "CRITICAL"}
    warn = any(x.severity == "WARN" for x in issues)

    if any("STALE" in code for code in critical_codes):
        state: HealthState = "STALE"
    elif "OPTION_QUOTES_MISSING" in critical_codes:
        state = "MISSING"
    elif "COLLECTION_TIME_REVERSED" in critical_codes:
        state = "OUT_OF_ORDER"
    elif critical_codes:
        state = "UNHEALTHY"
    elif warn:
        state = "DEGRADED"
    else:
        state = "HEALTHY"

    return SnapshotHealthReport(
        model=MODEL,
        state=state,
        checked_at=snapshot.received_at.isoformat(),
        received_at=snapshot.received_at.isoformat(),
        collection_latency_ms=collection_latency,
        spot_feed_age_ms=spot_age,
        oi_source_age_ms=oi_age,
        quote_timestamp_available=quote_timestamp_available,
        quote_timestamp_total=total_quotes,
        stale_quote_count=stale_quote_count,
        missing_oi_count=missing_oi_count,
        missing_ltp_count=missing_ltp_count,
        duplicate_contract_count=duplicate_contract_count,
        issues=tuple(issues),
    )


def strategy_dependency_gate(
    report: SnapshotHealthReport,
    *,
    dependency: str,
) -> tuple[bool, str | None]:
    """
    Fail-closed gate for shadow strategy steps.

    DEGRADED is observable but not automatically fatal.
    STALE/MISSING/OUT_OF_ORDER/UNHEALTHY are fatal.
    """
    if report.state in CRITICAL_STATES:
        return False, f"DATA_HEALTH_{dependency}_{report.state}"
    return True, None
