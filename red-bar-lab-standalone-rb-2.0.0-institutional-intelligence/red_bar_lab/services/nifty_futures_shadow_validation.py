from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable, Mapping


@dataclass(frozen=True)
class NiftyFuturesShadowValidation:
    status: str
    reason: str
    observations: int
    market_hours_observations: int
    ready_observations: int
    directional_observations: int
    strong_or_moderate_observations: int
    readiness_rate_pct: float
    directional_rate_pct: float
    participation_rate_pct: float
    execution_impact: str = "NONE"


def _is_market_hours(value: object) -> bool:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    local_time = parsed.timetz().replace(tzinfo=None)
    return time(9, 15) <= local_time <= time(15, 30)


def _pct(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else (numerator / denominator) * 100.0


def validate_nifty_futures_shadow_session(
    snapshots: Iterable[Mapping[str, object]],
) -> NiftyFuturesShadowValidation:
    """Summarize persisted market-hours futures observations in shadow mode."""

    rows = list(snapshots)
    market_rows = [row for row in rows if _is_market_hours(row.get("observed_at"))]
    ready = [row for row in market_rows if row.get("readiness_status") == "READY"]
    directional = [
        row for row in ready
        if row.get("positioning_state") not in {None, "", "NEUTRAL"}
    ]
    participating = [
        row for row in directional
        if row.get("strength") in {"STRONG", "MODERATE"}
    ]

    if not market_rows:
        return NiftyFuturesShadowValidation(
            status="INSUFFICIENT_DATA",
            reason="No persisted market-hours futures observations are available.",
            observations=len(rows),
            market_hours_observations=0,
            ready_observations=0,
            directional_observations=0,
            strong_or_moderate_observations=0,
            readiness_rate_pct=0.0,
            directional_rate_pct=0.0,
            participation_rate_pct=0.0,
        )

    return NiftyFuturesShadowValidation(
        status="READY",
        reason="Market-hours futures readiness and positioning were summarized in shadow mode.",
        observations=len(rows),
        market_hours_observations=len(market_rows),
        ready_observations=len(ready),
        directional_observations=len(directional),
        strong_or_moderate_observations=len(participating),
        readiness_rate_pct=_pct(len(ready), len(market_rows)),
        directional_rate_pct=_pct(len(directional), len(ready)),
        participation_rate_pct=_pct(len(participating), len(directional)),
    )
