from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paper_market_data_readiness_models import MarketDataReadinessReport
from .paper_market_data_readiness_store import (
    AtomicJsonMarketDataReadinessStore,
    ReadinessStateCorruptionError,
    ReadinessStateUnavailableError,
)


@dataclass(frozen=True, slots=True)
class MarketDataReadinessObservation:
    status: str
    report: MarketDataReadinessReport | None
    age_seconds: float | None
    integrity: str


class MarketDataReadinessObservabilityService:
    def __init__(self, path: Path, *, stale_after_seconds: float = 300.0) -> None:
        self.store = AtomicJsonMarketDataReadinessStore(path)
        self.stale_after_seconds = float(stale_after_seconds)

    def load(self, *, enabled: bool, now: datetime | None = None) -> MarketDataReadinessObservation:
        if not enabled:
            return MarketDataReadinessObservation("READINESS_DISABLED", None, None, "NOT_APPLICABLE")
        try:
            report = self.store.load()
        except ReadinessStateCorruptionError:
            return MarketDataReadinessObservation("READINESS_REPORT_CORRUPT", None, None, "CORRUPT")
        except ReadinessStateUnavailableError:
            return MarketDataReadinessObservation("READINESS_REPORT_UNAVAILABLE", None, None, "UNAVAILABLE")
        if report is None:
            return MarketDataReadinessObservation("READINESS_NOT_RUN", None, None, "NOT_AVAILABLE")
        current = now or datetime.now(timezone.utc)
        age = (current.astimezone(timezone.utc) - report.evaluated_at.astimezone(timezone.utc)).total_seconds()
        status = "READINESS_REPORT_STALE" if age > self.stale_after_seconds else "READINESS_REPORT_AVAILABLE"
        return MarketDataReadinessObservation(status, report, age, "VERIFIED")
