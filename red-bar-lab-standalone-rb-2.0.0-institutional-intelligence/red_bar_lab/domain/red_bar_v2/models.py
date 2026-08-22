from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite

from .enums import (
    AdmissionOutcome,
    BundleLifecycleStatus,
    ContextStatus,
    Direction,
    EntryType,
    OptionSide,
    RedBarV2Section1Outcome,
    RedBarV2State,
    TrendStrength,
)
from .exceptions import BundleIdentityError, DomainValidationError

_SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m"})
_MIDPOINT_ABS_TOLERANCE = 1e-9


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{name} must be a non-empty string")


def _require_v2_strategy(name: str, value: str) -> None:
    _require_text(name, value)
    if value != "RED_BAR_V2":
        raise DomainValidationError(f"{name} must be RED_BAR_V2")


def _require_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise DomainValidationError(f"{name} must be a bool")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware")


def _require_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise DomainValidationError(f"{name} must be a finite number")


def _require_positive(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) <= 0:
        raise DomainValidationError(f"{name} must be greater than zero")


def _require_entry_timeframe(entry_type: EntryType, evaluation_timeframe: str) -> None:
    expected = "1m" if entry_type is EntryType.INITIAL else "5m"
    if evaluation_timeframe != expected:
        raise DomainValidationError(
            f"{entry_type.value} entry requires {expected} evaluation_timeframe"
        )


def _require_alignment_truth(
    *,
    evidence_name: str,
    bullish_aligned: bool,
    bearish_aligned: bool,
    expected_bullish: bool,
    expected_bearish: bool,
) -> None:
    if bullish_aligned is not expected_bullish or bearish_aligned is not expected_bearish:
        raise DomainValidationError(
            f"{evidence_name} alignment flags must match numeric evidence"
        )


@dataclass(frozen=True, slots=True)
class RedBarV2Reference:
    """Canonical Red Bar V2 reference range."""

    reference_id: str
    trading_date: date
    timestamp: datetime
    high: float
    low: float
    midpoint: float
    source: str

    def __post_init__(self) -> None:
        _require_text("reference_id", self.reference_id)
        _require_text("source", self.source)
        _require_aware("timestamp", self.timestamp)
        for name, value in (("high", self.high), ("low", self.low), ("midpoint", self.midpoint)):
            _require_finite(name, value)
        if self.high <= self.low:
            raise DomainValidationError("reference high must be greater than low")
        if not self.low <= self.midpoint <= self.high:
            raise DomainValidationError("reference midpoint must be within [low, high]")
        if self.timestamp.date() != self.trading_date:
            raise DomainValidationError("reference timestamp date must match trading_date")


@dataclass(frozen=True, slots=True)
class MarketTimestampEvidence:
    """Freshness and alignment evidence for canonical market inputs."""

    latest_index_1m: datetime | None
    latest_index_5m: datetime | None
    latest_futures_1m: datetime | None
    latest_futures_5m: datetime | None
    evaluated_at: datetime
    context_status: ContextStatus
    maximum_age_seconds: int
    reason: str

    def __post_init__(self) -> None:
        _require_aware("evaluated_at", self.evaluated_at)
        for name in ("latest_index_1m", "latest_index_5m", "latest_futures_1m", "latest_futures_5m"):
            value = getattr(self, name)
            if value is not None:
                _require_aware(name, value)
        if isinstance(self.maximum_age_seconds, bool) or not isinstance(self.maximum_age_seconds, int):
            raise DomainValidationError("maximum_age_seconds must be an int")
        if self.maximum_age_seconds <= 0:
            raise DomainValidationError("maximum_age_seconds must be greater than zero")
        _require_text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class RedBarV2InputReadiness:
    """Section 1 canonical input-readiness resolution."""

    strategy_id: str
    strategy_version: str
    trading_date: date
    outcome: RedBarV2Section1Outcome
    reference: RedBarV2Reference | None
    timestamps: MarketTimestampEvidence
    futures_instrument_key: str | None
    futures_expiry: date | None
    futures_volume_available: bool
    futures_vwap_available: bool
    source_name: str
    source_version: str
    reason_code: str
    reason: str

    def __post_init__(self) -> None:
        _require_v2_strategy("strategy_id", self.strategy_id)
        for name in ("strategy_version", "source_name", "source_version", "reason_code", "reason"):
            _require_text(name, getattr(self, name))
        _require_bool("futures_volume_available", self.futures_volume_available)
        _require_bool("futures_vwap_available", self.futures_vwap_available)
        if self.reference is not None and self.reference.trading_date != self.trading_date:
            raise DomainValidationError("reference trading_date must match readiness trading_date")
        if self.outcome is RedBarV2Section1Outcome.REFERENCE_READY:
            if self.reference is None:
                raise DomainValidationError("REFERENCE_READY requires reference")
            if self.timestamps.context_status is not ContextStatus.FRESH:
                raise DomainValidationError("REFERENCE_READY requires fresh context")
            if not isinstance(self.futures_instrument_key, str) or not self.futures_instrument_key.strip():
                raise DomainValidationError("REFERENCE_READY requires futures instrument")
            if not self.futures_volume_available:
                raise DomainValidationError("REFERENCE_READY requires futures volume")
            if not self.futures_vwap_available:
                raise DomainValidationError("REFERENCE_READY requires futures VWAP")


@dataclass(frozen=True, slots=True)
class RsiEvidence:
    """RSI values and precomputed directional alignment."""

    value: float
    bullish_threshold: float
    bearish_threshold: float
    bullish_aligned: bool
    bearish_aligned: bool

    def __post_init__(self) -> None:
        for name in ("value", "bullish_threshold", "bearish_threshold"):
            _require_finite(name, getattr(self, name))
        _require_bool("bullish_aligned", self.bullish_aligned)
        _require_bool("bearish_aligned", self.bearish_aligned)
        if not 0 <= self.value <= 100:
            raise DomainValidationError("RSI value must be within [0, 100]")
        if not 0 <= self.bearish_threshold < self.bullish_threshold <= 100:
            raise DomainValidationError("RSI thresholds must satisfy 0 <= bearish < bullish <= 100")
        _require_alignment_truth(
            evidence_name="RSI",
            bullish_aligned=self.bullish_aligned,
            bearish_aligned=self.bearish_aligned,
            expected_bullish=self.value > self.bullish_threshold,
            expected_bearish=self.value < self.bearish_threshold,
        )


@dataclass(frozen=True, slots=True)
class FuturesVwapEvidence:
    """Futures price, VWAP, volume and directional alignment."""

    instrument_key: str
    comparison_price: float
    vwap: float
    volume: float
    bullish_aligned: bool
    bearish_aligned: bool
    fresh: bool

    def __post_init__(self) -> None:
        _require_text("instrument_key", self.instrument_key)
        _require_positive("comparison_price", self.comparison_price)
        _require_positive("vwap", self.vwap)
        _require_finite("volume", self.volume)
        _require_bool("bullish_aligned", self.bullish_aligned)
        _require_bool("bearish_aligned", self.bearish_aligned)
        _require_bool("fresh", self.fresh)
        if self.volume < 0:
            raise DomainValidationError("volume must be non-negative")
        _require_alignment_truth(
            evidence_name="futures VWAP",
            bullish_aligned=self.bullish_aligned,
            bearish_aligned=self.bearish_aligned,
            expected_bullish=self.comparison_price > self.vwap,
            expected_bearish=self.comparison_price < self.vwap,
        )


@dataclass(frozen=True, slots=True)
class MidpointEvidence:
    """Index-close relation to the canonical reference midpoint."""

    index_close: float
    midpoint: float
    bullish_aligned: bool
    bearish_aligned: bool

    def __post_init__(self) -> None:
        _require_positive("index_close", self.index_close)
        _require_positive("midpoint", self.midpoint)
        _require_bool("bullish_aligned", self.bullish_aligned)
        _require_bool("bearish_aligned", self.bearish_aligned)
        _require_alignment_truth(
            evidence_name="midpoint",
            bullish_aligned=self.bullish_aligned,
            bearish_aligned=self.bearish_aligned,
            expected_bullish=self.index_close > self.midpoint,
            expected_bearish=self.index_close < self.midpoint,
        )


@dataclass(frozen=True, slots=True)
class RedBarV2Decision:
    """Section 2 canonical decision contract without strategy calculations."""

    strategy_id: str
    strategy_version: str
    evaluation_timestamp: datetime
    evaluation_timeframe: str
    entry_type: EntryType | None
    previous_state: RedBarV2State
    current_state: RedBarV2State
    direction: Direction | None
    option_side: OptionSide | None
    trend_strength: TrendStrength | None
    reference: RedBarV2Reference | None
    rsi: RsiEvidence | None
    futures_vwap: FuturesVwapEvidence | None
    midpoint: MidpointEvidence | None
    context_status: ContextStatus
    admission_outcome: AdmissionOutcome
    admission_code: str
    admission_reason: str

    def __post_init__(self) -> None:
        _require_v2_strategy("strategy_id", self.strategy_id)
        _require_text("strategy_version", self.strategy_version)
        _require_aware("evaluation_timestamp", self.evaluation_timestamp)
        if self.evaluation_timeframe not in _SUPPORTED_TIMEFRAMES:
            raise DomainValidationError(f"unsupported evaluation_timeframe: {self.evaluation_timeframe!r}")
        if self.direction is Direction.BULLISH and self.option_side is not OptionSide.CE:
            raise DomainValidationError("BULLISH direction requires CE option side")
        if self.direction is Direction.BEARISH and self.option_side is not OptionSide.PE:
            raise DomainValidationError("BEARISH direction requires PE option side")
        state_direction = {
            RedBarV2State.PROVISIONAL_BULLISH: Direction.BULLISH,
            RedBarV2State.CONFIRMED_BULLISH: Direction.BULLISH,
            RedBarV2State.PROVISIONAL_BEARISH: Direction.BEARISH,
            RedBarV2State.CONFIRMED_BEARISH: Direction.BEARISH,
        }.get(self.current_state)
        if state_direction is not None and self.direction is not state_direction:
            raise DomainValidationError("direction must match provisional/confirmed current_state")
        state_strength = {
            RedBarV2State.PROVISIONAL_BULLISH: TrendStrength.PROVISIONAL,
            RedBarV2State.PROVISIONAL_BEARISH: TrendStrength.PROVISIONAL,
            RedBarV2State.CONFIRMED_BULLISH: TrendStrength.CONFIRMED,
            RedBarV2State.CONFIRMED_BEARISH: TrendStrength.CONFIRMED,
        }.get(self.current_state)
        if state_strength is not None and self.trend_strength is not state_strength:
            raise DomainValidationError("trend_strength must match provisional/confirmed current_state")
        if self.admission_outcome is AdmissionOutcome.ALLOWED:
            required = {
                "entry_type": self.entry_type,
                "direction": self.direction,
                "option_side": self.option_side,
                "reference": self.reference,
                "rsi": self.rsi,
                "futures_vwap": self.futures_vwap,
                "midpoint": self.midpoint,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise DomainValidationError(f"ALLOWED decision missing: {', '.join(missing)}")
            assert self.entry_type is not None
            assert self.direction is not None
            assert self.reference is not None
            assert self.rsi is not None
            assert self.futures_vwap is not None
            assert self.midpoint is not None
            if self.context_status is not ContextStatus.FRESH:
                raise DomainValidationError("ALLOWED decision requires fresh context")
            if not self.futures_vwap.fresh:
                raise DomainValidationError("ALLOWED decision requires fresh futures VWAP evidence")
            _require_entry_timeframe(self.entry_type, self.evaluation_timeframe)
            rsi_vwap_aligned = (
                self.rsi.bullish_aligned
                and not self.rsi.bearish_aligned
                and self.futures_vwap.bullish_aligned
                and not self.futures_vwap.bearish_aligned
            ) if self.direction is Direction.BULLISH else (
                self.rsi.bearish_aligned
                and not self.rsi.bullish_aligned
                and self.futures_vwap.bearish_aligned
                and not self.futures_vwap.bullish_aligned
            )
            if not rsi_vwap_aligned:
                raise DomainValidationError("ALLOWED decision RSI/VWAP evidence must align with direction")
            midpoint_aligned = (
                self.midpoint.bullish_aligned
                and not self.midpoint.bearish_aligned
            ) if self.direction is Direction.BULLISH else (
                self.midpoint.bearish_aligned
                and not self.midpoint.bullish_aligned
            )
            expected_state = (
                RedBarV2State.CONFIRMED_BULLISH
                if self.direction is Direction.BULLISH
                else RedBarV2State.CONFIRMED_BEARISH
            ) if midpoint_aligned else (
                RedBarV2State.PROVISIONAL_BULLISH
                if self.direction is Direction.BULLISH
                else RedBarV2State.PROVISIONAL_BEARISH
            )
            expected_strength = TrendStrength.CONFIRMED if midpoint_aligned else TrendStrength.PROVISIONAL
            if self.entry_type is EntryType.INITIAL:
                if not midpoint_aligned:
                    raise DomainValidationError("INITIAL admission requires midpoint alignment")
                if self.current_state is not expected_state or self.trend_strength is not TrendStrength.CONFIRMED:
                    raise DomainValidationError("INITIAL admission must be confirmed")
            else:
                if self.current_state is not expected_state or self.trend_strength is not expected_strength:
                    raise DomainValidationError(
                        "REVERSAL state and trend_strength must match midpoint confirmation"
                    )
            if not isclose(
                float(self.midpoint.midpoint),
                float(self.reference.midpoint),
                rel_tol=0.0,
                abs_tol=_MIDPOINT_ABS_TOLERANCE,
            ):
                raise DomainValidationError("midpoint evidence must match reference midpoint")
            _require_text("admission_code", self.admission_code)
            _require_text("admission_reason", self.admission_reason)


@dataclass(frozen=True, slots=True)
class RedBarV2SignalBundle:
    """Section 3 canonical immutable Red Bar V2 signal bundle."""

    schema_version: str
    bundle_id: str
    signal_id: str
    strategy_id: str
    strategy_version: str
    trading_date: date
    evaluation_timestamp: datetime
    evaluation_timeframe: str
    entry_type: EntryType
    direction: Direction
    option_side: OptionSide
    decision: RedBarV2Decision
    idempotency_key: str
    lifecycle_status: BundleLifecycleStatus
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("schema_version", "bundle_id", "signal_id", "strategy_version", "idempotency_key"):
            _require_text(name, getattr(self, name))
        _require_v2_strategy("strategy_id", self.strategy_id)
        _require_aware("evaluation_timestamp", self.evaluation_timestamp)
        _require_aware("created_at", self.created_at)
        if self.evaluation_timeframe not in _SUPPORTED_TIMEFRAMES:
            raise DomainValidationError(f"unsupported evaluation_timeframe: {self.evaluation_timeframe!r}")
        _require_entry_timeframe(self.entry_type, self.evaluation_timeframe)
        if self.direction is Direction.BULLISH and self.option_side is not OptionSide.CE:
            raise DomainValidationError("BULLISH bundle requires CE")
        if self.direction is Direction.BEARISH and self.option_side is not OptionSide.PE:
            raise DomainValidationError("BEARISH bundle requires PE")
        decision = self.decision
        if decision.admission_outcome is not AdmissionOutcome.ALLOWED:
            raise DomainValidationError("signal bundle requires ALLOWED decision")
        comparisons = {
            "strategy_id": (self.strategy_id, decision.strategy_id),
            "strategy_version": (self.strategy_version, decision.strategy_version),
            "evaluation_timestamp": (self.evaluation_timestamp, decision.evaluation_timestamp),
            "evaluation_timeframe": (self.evaluation_timeframe, decision.evaluation_timeframe),
            "entry_type": (self.entry_type, decision.entry_type),
            "direction": (self.direction, decision.direction),
            "option_side": (self.option_side, decision.option_side),
        }
        mismatched = [name for name, values in comparisons.items() if values[0] != values[1]]
        if mismatched:
            raise DomainValidationError(f"bundle fields mismatch decision: {', '.join(mismatched)}")
        if self.evaluation_timestamp.date() != self.trading_date:
            raise DomainValidationError("bundle evaluation timestamp date must match trading_date")
        if decision.reference is None or decision.reference.trading_date != self.trading_date:
            raise DomainValidationError("bundle reference trading_date must match bundle trading_date")
        if decision.futures_vwap is None:
            raise DomainValidationError("signal bundle requires futures VWAP evidence")

        from .identity import (
            build_red_bar_v2_bundle_id,
            build_red_bar_v2_idempotency_key,
            build_red_bar_v2_signal_id,
        )

        expected_signal = build_red_bar_v2_signal_id(
            strategy_version=self.strategy_version,
            instrument_key=decision.futures_vwap.instrument_key,
            trading_date=self.trading_date,
            reference_id=decision.reference.reference_id,
            evaluation_timestamp=self.evaluation_timestamp,
            entry_type=self.entry_type,
            direction=self.direction,
        )
        expected_bundle = build_red_bar_v2_bundle_id(
            signal_id=expected_signal,
            schema_version=self.schema_version,
        )
        expected_idempotency = build_red_bar_v2_idempotency_key(
            signal_id=expected_signal,
            option_side=self.option_side,
        )
        if self.signal_id != expected_signal:
            raise BundleIdentityError("signal_id does not match canonical bundle fields")
        if self.bundle_id != expected_bundle:
            raise BundleIdentityError("bundle_id does not match canonical signal and schema")
        if self.idempotency_key != expected_idempotency:
            raise BundleIdentityError("idempotency_key does not match canonical signal and option side")
