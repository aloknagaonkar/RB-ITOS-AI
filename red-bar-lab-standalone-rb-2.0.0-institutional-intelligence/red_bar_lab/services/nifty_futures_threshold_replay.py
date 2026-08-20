from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from red_bar_lab.services.nifty_futures_positioning import NiftyFuturesPositioning
from red_bar_lab.services.nifty_futures_positioning_strength import (
    assess_nifty_futures_positioning_strength,
)


@dataclass(frozen=True)
class NiftyFuturesThresholdReplay:
    status: str
    samples: int
    directional_samples: int
    strong: int
    moderate: int
    weak: int
    insufficient: int
    strong_rate_pct: float
    moderate_or_strong_rate_pct: float
    price_threshold_pct: float
    oi_threshold_pct: float
    moderate_relative_volume: float
    strong_relative_volume: float
    execution_impact: str = "NONE"


def _pct(value: int, total: int) -> float:
    return 0.0 if total <= 0 else (value / total) * 100.0


def replay_nifty_futures_strength_thresholds(
    rows: Iterable[Mapping[str, object]],
    *,
    price_threshold_pct: float = 0.02,
    oi_threshold_pct: float = 0.02,
    moderate_relative_volume: float = 0.8,
    strong_relative_volume: float = 1.2,
) -> NiftyFuturesThresholdReplay:
    counts = {"STRONG": 0, "MODERATE": 0, "WEAK": 0, "INSUFFICIENT": 0}
    samples = list(rows)
    directional = 0

    for row in samples:
        state = str(row.get("positioning_state") or row.get("state") or "NEUTRAL")
        if state != "NEUTRAL":
            directional += 1
        positioning = NiftyFuturesPositioning(
            status=str(row.get("positioning_status") or row.get("status") or "READY"),
            reason="Historical threshold replay input.",
            state=state,
            price_change_pct=row.get("price_change_pct"),
            oi_change_pct=row.get("oi_change_pct"),
            relative_volume=row.get("relative_volume"),
        )
        result = assess_nifty_futures_positioning_strength(
            positioning,
            price_threshold_pct=price_threshold_pct,
            oi_threshold_pct=oi_threshold_pct,
            moderate_relative_volume=moderate_relative_volume,
            strong_relative_volume=strong_relative_volume,
        )
        counts[result.strength] = counts.get(result.strength, 0) + 1

    ready_samples = counts["STRONG"] + counts["MODERATE"] + counts["WEAK"]
    return NiftyFuturesThresholdReplay(
        status="READY" if samples else "INSUFFICIENT_DATA",
        samples=len(samples),
        directional_samples=directional,
        strong=counts["STRONG"],
        moderate=counts["MODERATE"],
        weak=counts["WEAK"],
        insufficient=counts["INSUFFICIENT"],
        strong_rate_pct=_pct(counts["STRONG"], ready_samples),
        moderate_or_strong_rate_pct=_pct(
            counts["STRONG"] + counts["MODERATE"], ready_samples
        ),
        price_threshold_pct=abs(float(price_threshold_pct)),
        oi_threshold_pct=abs(float(oi_threshold_pct)),
        moderate_relative_volume=max(0.0, float(moderate_relative_volume)),
        strong_relative_volume=max(
            max(0.0, float(moderate_relative_volume)),
            float(strong_relative_volume),
        ),
    )
