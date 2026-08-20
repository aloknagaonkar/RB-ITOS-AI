from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from red_bar_lab.services.nifty_futures_market_data import (
    NiftyFuturesMarketData,
    assess_nifty_futures_market_data,
)
from red_bar_lab.services.nifty_futures_positioning import NiftyFuturesPositioning
from red_bar_lab.services.nifty_futures_positioning_monitor import assess_futures_positioning
from red_bar_lab.services.nifty_futures_positioning_strength import (
    NiftyFuturesPositioningStrength,
    assess_nifty_futures_positioning_strength,
)
from red_bar_lab.services.nifty_futures_readiness import (
    NiftyFuturesReadiness,
    assess_nifty_futures_readiness,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    persist_nifty_futures_snapshot,
)


@dataclass(frozen=True)
class NiftyFuturesPhase2Result:
    contract: object
    market: NiftyFuturesMarketData
    positioning: NiftyFuturesPositioning
    strength: NiftyFuturesPositioningStrength
    readiness: NiftyFuturesReadiness
    persisted: bool
    persistence_error: str | None = None


def run_nifty_futures_phase2_pipeline(
    provider,
    *,
    database_path: str | Path,
    contract,
    now: datetime,
    underlying_name: str = "NIFTY 50",
    applicable: bool = True,
    persist: bool = True,
) -> NiftyFuturesPhase2Result:
    """Run Phase 2 futures diagnostics as a read-only observational pipeline."""

    market = assess_nifty_futures_market_data(provider, contract=contract, now=now)
    positioning = assess_futures_positioning(market)
    strength = assess_nifty_futures_positioning_strength(positioning)
    readiness = assess_nifty_futures_readiness(
        contract=contract,
        market=market,
        positioning=positioning,
        applicable=applicable,
    )

    persisted = False
    persistence_error = None
    if persist:
        try:
            persist_nifty_futures_snapshot(
                database_path,
                observed_at=now,
                underlying_name=underlying_name,
                contract=contract,
                market=market,
                positioning=positioning,
                strength=strength,
                readiness=readiness,
            )
            persisted = True
        except Exception as exc:  # diagnostics persistence must never stop monitoring
            persistence_error = f"{type(exc).__name__}:{exc}"

    return NiftyFuturesPhase2Result(
        contract=contract,
        market=market,
        positioning=positioning,
        strength=strength,
        readiness=readiness,
        persisted=persisted,
        persistence_error=persistence_error,
    )
