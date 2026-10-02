from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Mapping, Sequence


class PositioningState(str, Enum):
    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    LONG_UNWINDING = "LONG_UNWINDING"
    SHORT_COVERING = "SHORT_COVERING"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class CombinedStrikeObservation(str, Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SidePoint:
    timestamp: datetime
    instrument_key: str
    strike: float
    side: str  # CE / PE
    close: float | None
    open_interest: float | None


@dataclass(frozen=True)
class PositioningConfig:
    price_change_threshold_pct: float = 0.0
    oi_change_threshold_pct: float = 0.0


@dataclass(frozen=True)
class SidePositioningResult:
    timestamp: datetime
    horizon_minutes: int
    instrument_key: str
    strike: float
    side: str
    current_close: float | None
    baseline_close: float | None
    current_oi: float | None
    baseline_oi: float | None
    premium_change_pct: float | None
    oi_change_pct: float | None
    state: PositioningState
    reason: str | None = None


@dataclass(frozen=True)
class StrikePositioningResult:
    timestamp: datetime
    horizon_minutes: int
    strike: float
    ce: SidePositioningResult
    pe: SidePositioningResult
    combined: CombinedStrikeObservation


def _pct_change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return ((current - baseline) / baseline) * 100.0


def classify_side(
    *,
    premium_change_pct: float | None,
    oi_change_pct: float | None,
    config: PositioningConfig,
) -> PositioningState:
    if premium_change_pct is None or oi_change_pct is None:
        return PositioningState.UNAVAILABLE

    p = premium_change_pct
    o = oi_change_pct
    pt = abs(config.price_change_threshold_pct)
    ot = abs(config.oi_change_threshold_pct)

    if abs(p) <= pt or abs(o) <= ot:
        return PositioningState.NEUTRAL
    if p > 0 and o > 0:
        return PositioningState.LONG_BUILDUP
    if p < 0 and o > 0:
        return PositioningState.SHORT_BUILDUP
    if p < 0 and o < 0:
        return PositioningState.LONG_UNWINDING
    if p > 0 and o < 0:
        return PositioningState.SHORT_COVERING
    return PositioningState.NEUTRAL


def combine_ce_pe(
    ce: PositioningState,
    pe: PositioningState,
) -> CombinedStrikeObservation:
    if ce == PositioningState.UNAVAILABLE or pe == PositioningState.UNAVAILABLE:
        return CombinedStrikeObservation.UNAVAILABLE

    if ce == PositioningState.LONG_BUILDUP and pe == PositioningState.SHORT_BUILDUP:
        return CombinedStrikeObservation.STRONG_BULLISH
    if ce == PositioningState.SHORT_BUILDUP and pe == PositioningState.LONG_BUILDUP:
        return CombinedStrikeObservation.STRONG_BEARISH

    bullish_states = {
        PositioningState.LONG_BUILDUP,
        PositioningState.SHORT_COVERING,
    }
    bearish_states = {
        PositioningState.SHORT_BUILDUP,
        PositioningState.LONG_UNWINDING,
    }

    ce_bull = ce in bullish_states
    ce_bear = ce in bearish_states
    pe_bull = pe in bearish_states  # bearish PE positioning can support bullish underlying
    pe_bear = pe in bullish_states  # bullish PE positioning can support bearish underlying

    if ce_bull and pe_bull:
        return CombinedStrikeObservation.BULLISH
    if ce_bear and pe_bear:
        return CombinedStrikeObservation.BEARISH
    if ce == PositioningState.NEUTRAL and pe == PositioningState.NEUTRAL:
        return CombinedStrikeObservation.NEUTRAL
    return CombinedStrikeObservation.MIXED


def build_side_positioning(
    *,
    current: SidePoint,
    baseline: SidePoint | None,
    horizon_minutes: int,
    config: PositioningConfig,
) -> SidePositioningResult:
    if baseline is None:
        return SidePositioningResult(
            timestamp=current.timestamp,
            horizon_minutes=horizon_minutes,
            instrument_key=current.instrument_key,
            strike=current.strike,
            side=current.side,
            current_close=current.close,
            baseline_close=None,
            current_oi=current.open_interest,
            baseline_oi=None,
            premium_change_pct=None,
            oi_change_pct=None,
            state=PositioningState.UNAVAILABLE,
            reason="EXACT_BASELINE_NOT_FOUND",
        )

    if baseline.instrument_key != current.instrument_key:
        return SidePositioningResult(
            timestamp=current.timestamp,
            horizon_minutes=horizon_minutes,
            instrument_key=current.instrument_key,
            strike=current.strike,
            side=current.side,
            current_close=current.close,
            baseline_close=baseline.close,
            current_oi=current.open_interest,
            baseline_oi=baseline.open_interest,
            premium_change_pct=None,
            oi_change_pct=None,
            state=PositioningState.UNAVAILABLE,
            reason="INSTRUMENT_CHANGED",
        )

    premium_change_pct = _pct_change(current.close, baseline.close)
    oi_change_pct = _pct_change(current.open_interest, baseline.open_interest)
    state = classify_side(
        premium_change_pct=premium_change_pct,
        oi_change_pct=oi_change_pct,
        config=config,
    )

    reason = None if state != PositioningState.UNAVAILABLE else "MISSING_OR_ZERO_BASELINE_VALUE"
    return SidePositioningResult(
        timestamp=current.timestamp,
        horizon_minutes=horizon_minutes,
        instrument_key=current.instrument_key,
        strike=current.strike,
        side=current.side,
        current_close=current.close,
        baseline_close=baseline.close,
        current_oi=current.open_interest,
        baseline_oi=baseline.open_interest,
        premium_change_pct=premium_change_pct,
        oi_change_pct=oi_change_pct,
        state=state,
        reason=reason,
    )


def build_positioning_index(points: Iterable[SidePoint]) -> dict[tuple[str, datetime], SidePoint]:
    return {(p.instrument_key, p.timestamp): p for p in points}


def exact_baseline(
    *,
    current: SidePoint,
    horizon_minutes: int,
    index: Mapping[tuple[str, datetime], SidePoint],
) -> SidePoint | None:
    target = current.timestamp - timedelta(minutes=horizon_minutes)
    return index.get((current.instrument_key, target))


def build_strike_positioning(
    *,
    ce_current: SidePoint,
    pe_current: SidePoint,
    horizon_minutes: int,
    index: Mapping[tuple[str, datetime], SidePoint],
    config: PositioningConfig,
) -> StrikePositioningResult:
    if ce_current.timestamp != pe_current.timestamp or ce_current.strike != pe_current.strike:
        raise ValueError("CE and PE must represent the same timestamp and strike")

    ce = build_side_positioning(
        current=ce_current,
        baseline=exact_baseline(current=ce_current, horizon_minutes=horizon_minutes, index=index),
        horizon_minutes=horizon_minutes,
        config=config,
    )
    pe = build_side_positioning(
        current=pe_current,
        baseline=exact_baseline(current=pe_current, horizon_minutes=horizon_minutes, index=index),
        horizon_minutes=horizon_minutes,
        config=config,
    )
    return StrikePositioningResult(
        timestamp=ce_current.timestamp,
        horizon_minutes=horizon_minutes,
        strike=ce_current.strike,
        ce=ce,
        pe=pe,
        combined=combine_ce_pe(ce.state, pe.state),
    )


def result_to_dict(result: StrikePositioningResult) -> dict:
    def convert(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "__dataclass_fields__"):
            return {k: convert(v) for k, v in asdict(value).items()}
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        return value
    return convert(result)
