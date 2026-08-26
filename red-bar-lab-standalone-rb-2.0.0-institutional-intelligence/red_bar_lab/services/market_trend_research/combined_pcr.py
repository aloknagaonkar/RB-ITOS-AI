from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from math import isfinite
from typing import Mapping
from zoneinfo import ZoneInfo


AUTHORITY = "OBSERVATIONAL_ONLY"
IST = ZoneInfo("Asia/Kolkata")

# Component weights describe influence on the composite, not literal PCR ratios.
COMPONENT_WEIGHTS: Mapping[str, float] = {
    "NIFTY 50": 0.35,
    "NIFTY TOP 10": 0.30,
    "NIFTY BANK": 0.20,
    "SENSEX": 0.15,
}
INDEX_COMPONENTS = ("NIFTY 50", "NIFTY BANK", "SENSEX")
INDEX_TOTAL_WEIGHT = sum(COMPONENT_WEIGHTS[name] for name in INDEX_COMPONENTS)

# Official NIFTY weights change over time. These relative weights are deliberately
# isolated so a later constituent-sync job can replace them without changing the
# composite calculation.
TOP_TEN_WEIGHTS: Mapping[str, float] = {
    "HDFCBANK": 10.56,
    "ICICIBANK": 8.32,
    "RELIANCE": 8.27,
    "BHARTIARTL": 5.20,
    "LT": 4.43,
    "INFY": 3.77,
    "SBIN": 3.71,
    "AXISBANK": 3.42,
    "KOTAKBANK": 2.62,
    "ITC": 2.56,
}


@dataclass(frozen=True, slots=True)
class CombinedPcrComponent:
    name: str
    weight: float
    pcr: float | None
    signal: float | None
    direction: str
    source_timestamp: datetime | None
    fresh: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CombinedMarketPcr:
    score: float | None
    direction: str
    confidence: float
    coverage: float
    agreement: str
    components: tuple[CombinedPcrComponent, ...]
    reason_code: str
    index_pcr: float | None = None
    authority: str = AUTHORITY


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _pcr(snapshot: Mapping[str, object] | None) -> float | None:
    if not snapshot:
        return None
    panel = snapshot.get("current_panel")
    aggregate = panel.get("aggregate") if isinstance(panel, Mapping) else None
    value = aggregate.get("pcr") if isinstance(aggregate, Mapping) else None
    if type(value) not in (int, float):
        return None
    result = float(value)
    return result if isfinite(result) and result >= 0 else None


def _signal(pcr: float) -> float:
    """Map the approved PCR bands to a bounded directional signal."""
    if pcr < 0.7:
        return -1.0
    if pcr < 1.25:
        return 0.0
    if pcr <= 1.5:
        return 0.65
    return 1.0


def _direction(signal: float | None) -> str:
    if signal is None:
        return "UNAVAILABLE"
    if signal >= 0.25:
        return "BULLISH"
    if signal <= -0.25:
        return "BEARISH"
    return "NEUTRAL"


def _is_fresh(snapshot: Mapping[str, object] | None, *, now: datetime, maximum_age_seconds: float) -> bool:
    timestamp = _timestamp(snapshot.get("source_timestamp")) if snapshot else None
    if timestamp is None:
        return False
    age = (now - timestamp.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= maximum_age_seconds


class CombinedMarketPcrCalculator:
    """Combine independent PCR evidence without creating trading authority."""

    def __init__(self, *, maximum_age_seconds: float = 30.0, minimum_coverage: float = 0.70, accept_same_day_close: bool = False, session_end: time = time(15, 30)) -> None:
        if maximum_age_seconds <= 0 or not 0 < minimum_coverage <= 1:
            raise ValueError("combined PCR policy invalid")
        self.maximum_age_seconds = maximum_age_seconds
        self.minimum_coverage = minimum_coverage
        self.accept_same_day_close = accept_same_day_close
        self.session_end = session_end

    def _usable(self, snapshot: Mapping[str, object] | None, *, now: datetime) -> bool:
        if _is_fresh(snapshot, now=now, maximum_age_seconds=self.maximum_age_seconds):
            return True
        timestamp = _timestamp(snapshot.get("source_timestamp")) if snapshot else None
        if not self.accept_same_day_close or timestamp is None:
            return False
        local_now = now.astimezone(IST)
        local_source = timestamp.astimezone(IST)
        seconds_before_close = (
            datetime.combine(local_source.date(), self.session_end, IST) - local_source
        ).total_seconds()
        return (
            local_now.date() == local_source.date()
            and local_now.time().replace(tzinfo=None) >= self.session_end
            and 0 <= seconds_before_close <= self.maximum_age_seconds
        )

    def _index_component(
        self,
        name: str,
        snapshot: Mapping[str, object] | None,
        *,
        now: datetime,
    ) -> CombinedPcrComponent:
        pcr = _pcr(snapshot)
        fresh = self._usable(snapshot, now=now)
        signal = _signal(pcr) if pcr is not None and fresh else None
        return CombinedPcrComponent(
            name=name,
            weight=COMPONENT_WEIGHTS[name],
            pcr=pcr,
            signal=signal,
            direction=_direction(signal),
            source_timestamp=_timestamp(snapshot.get("source_timestamp")) if snapshot else None,
            fresh=fresh,
            detail="Current OI PCR" if signal is not None else "Missing or stale PCR evidence",
        )

    def _top_ten_component(
        self,
        snapshots: Mapping[str, Mapping[str, object]],
        *,
        now: datetime,
    ) -> CombinedPcrComponent:
        available_weight = 0.0
        weighted_pcr = 0.0
        weighted_signal = 0.0
        newest: datetime | None = None
        available = 0
        for symbol, stock_weight in TOP_TEN_WEIGHTS.items():
            snapshot = snapshots.get(symbol)
            pcr = _pcr(snapshot)
            if pcr is None or not self._usable(snapshot, now=now):
                continue
            available += 1
            available_weight += stock_weight
            weighted_pcr += stock_weight * pcr
            weighted_signal += stock_weight * _signal(pcr)
            timestamp = _timestamp(snapshot.get("source_timestamp"))
            if timestamp is not None and (newest is None or timestamp > newest):
                newest = timestamp
        stock_coverage = available_weight / sum(TOP_TEN_WEIGHTS.values())
        signal = weighted_signal / available_weight if stock_coverage >= self.minimum_coverage else None
        aggregate_pcr = (
            weighted_pcr / available_weight
            if stock_coverage >= self.minimum_coverage
            else None
        )
        return CombinedPcrComponent(
            name="NIFTY TOP 10",
            weight=COMPONENT_WEIGHTS["NIFTY TOP 10"],
            pcr=aggregate_pcr,
            signal=signal,
            direction=_direction(signal),
            source_timestamp=newest,
            fresh=signal is not None,
            detail=f"{available}/10 stocks; index-weight coverage {stock_coverage:.1%}",
        )

    def calculate(
        self,
        snapshots: Mapping[str, Mapping[str, object]],
        *,
        now: datetime | None = None,
    ) -> CombinedMarketPcr:
        evaluated_at = now or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        components = (
            self._index_component("NIFTY 50", snapshots.get("NIFTY 50"), now=evaluated_at),
            self._top_ten_component(snapshots, now=evaluated_at),
            self._index_component("NIFTY BANK", snapshots.get("NIFTY BANK"), now=evaluated_at),
            self._index_component("SENSEX", snapshots.get("SENSEX"), now=evaluated_at),
        )
        index_components = tuple(
            component for component in components
            if component.name in INDEX_COMPONENTS
        )
        usable = tuple(
            component for component in index_components
            if component.signal is not None and component.pcr is not None
        )
        coverage = sum(component.weight for component in usable) / INDEX_TOTAL_WEIGHT
        if len(usable) != len(INDEX_COMPONENTS):
            return CombinedMarketPcr(
                score=None,
                direction="UNAVAILABLE",
                confidence=0.0,
                coverage=coverage,
                agreement="Insufficient fresh evidence",
                components=components,
                reason_code="COMBINED_PCR_COVERAGE_INSUFFICIENT",
                index_pcr=None,
            )
        weighted_index_pcr = sum(
            component.weight * float(component.pcr) for component in usable
        ) / INDEX_TOTAL_WEIGHT
        normalized_signal = _signal(weighted_index_pcr)
        score = 50.0 + (50.0 * normalized_signal)
        direction = _direction(normalized_signal)
        agreeing = sum(component.direction == direction for component in usable)
        return CombinedMarketPcr(
            score=score,
            direction=direction,
            confidence=abs(normalized_signal) * 100.0,
            coverage=coverage,
            agreement=f"{agreeing} of 3 index components agree",
            components=components,
            reason_code="COMBINED_PCR_READY",
            index_pcr=weighted_index_pcr,
        )
