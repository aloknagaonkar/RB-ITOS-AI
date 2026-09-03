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
_SUPPORTED_BUNDLE_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
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
    """Only a reversal is judged on five minutes.

    A reversal is a counter-trend re-entry inside a band roughly sixty points
    wide, so a one-minute close would fire, invalidate and re-fire around the
    midpoint; the extra four minutes buy evidence where it is worth most. The
    initial entry and the working-reference entry both act on a one-minute close.
    """
    expected = "5m" if entry_type is EntryType.REVERSAL else "1m"
    if evaluation_timeframe != expected:
        raise DomainValidationError(f"{entry_type.value} entry requires {expected} evaluation_timeframe")



def _require_alignment_truth(
    *, evidence_name: str, bullish_aligned: bool, bearish_aligned: bool,
    expected_bullish: bool, expected_bearish: bool,
) -> None:
    if bullish_aligned is not expected_bullish or bearish_aligned is not expected_bearish:
        raise DomainValidationError(f"{evidence_name} alignment flags must match numeric evidence")


@dataclass(frozen=True, slots=True)
class RedBarV2Reference:
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
            evidence_name="RSI", bullish_aligned=self.bullish_aligned,
            bearish_aligned=self.bearish_aligned,
            expected_bullish=self.value > self.bullish_threshold,
            expected_bearish=self.value < self.bearish_threshold,
        )


@dataclass(frozen=True, slots=True)
class FuturesVwapEvidence:
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
            evidence_name="futures VWAP", bullish_aligned=self.bullish_aligned,
            bearish_aligned=self.bearish_aligned,
            expected_bullish=self.comparison_price > self.vwap,
            expected_bearish=self.comparison_price < self.vwap,
        )


@dataclass(frozen=True, slots=True)
class MidpointEvidence:
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
            evidence_name="midpoint", bullish_aligned=self.bullish_aligned,
            bearish_aligned=self.bearish_aligned,
            expected_bullish=self.index_close > self.midpoint,
            expected_bearish=self.index_close < self.midpoint,
        )


@dataclass(frozen=True, slots=True)
class RedBarV2Decision:
    """One evaluation of the strategy, with the evidence that justifies it.

    `reference` carries the **governing** reference -- the level this particular
    decision was judged against, not always the red bar. On an INITIAL or
    REVERSAL entry that is the red bar. On a WORKING entry it is the deputy
    candle, with `source="WORKING_OPPOSITE_CANDLE"`, because the deputy is what
    the close was actually compared to while price was outside the red bar's band.

    There is deliberately no second `governing_reference` slot. One slot means the
    midpoint-match and grade invariants below re-derive their claims against
    whichever level was in force, without having to know which path produced the
    decision; `entry_type` and `reference.source` remain the machine-readable
    markers for readers that care.
    """

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
            # Two evidence blocks are deliberately absent from this set.
            #
            # `rsi` is informational under the futures gates, and requiring the
            # evidence block made an otherwise-valid warm-up admission
            # unrepresentable.
            #
            # `futures_vwap` is required for the two red bar paths and not for
            # WORKING. A working entry is judged against the deputy that governs
            # the space outside the red bar's band, and that path consults no VWAP
            # at all -- the deputy's body and its close beyond the previous
            # five-minute extreme are its evidence. Requiring VWAP here would make
            # every working entry unrepresentable, exactly as requiring RSI did for
            # a warm-up admission.
            requires_vwap = self.entry_type is not EntryType.WORKING
            required = {
                "entry_type": self.entry_type, "direction": self.direction,
                "option_side": self.option_side, "reference": self.reference,
                "midpoint": self.midpoint,
            }
            if requires_vwap:
                required["futures_vwap"] = self.futures_vwap
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise DomainValidationError(f"ALLOWED decision missing: {', '.join(missing)}")
            assert self.entry_type is not None and self.direction is not None
            assert self.reference is not None
            assert self.midpoint is not None
            if self.context_status is not ContextStatus.FRESH:
                raise DomainValidationError("ALLOWED decision requires fresh context")
            if requires_vwap:
                assert self.futures_vwap is not None
                if not self.futures_vwap.fresh:
                    raise DomainValidationError("ALLOWED decision requires fresh futures VWAP evidence")
            _require_entry_timeframe(self.entry_type, self.evaluation_timeframe)
            # RSI is informational under the futures gates (RedBar reference +
            # VWAP decide direction), so RSI evidence must not invalidate an
            # ALLOWED decision. It is still carried for observability.
            if requires_vwap:
                vwap_aligned = (
                    self.futures_vwap.bullish_aligned and not self.futures_vwap.bearish_aligned
                ) if self.direction is Direction.BULLISH else (
                    self.futures_vwap.bearish_aligned and not self.futures_vwap.bullish_aligned
                )
                if not vwap_aligned:
                    raise DomainValidationError("ALLOWED decision VWAP evidence must align with direction")

            midpoint_aligned = (
                self.midpoint.bullish_aligned and not self.midpoint.bearish_aligned
            ) if self.direction is Direction.BULLISH else (
                self.midpoint.bearish_aligned and not self.midpoint.bullish_aligned
            )
            # The midpoint is a gate, and it applies to every Red Bar entry.
            # REVERSAL used to be exempt, with the midpoint demoted to a grade,
            # which let a decision be admitted with the index close on the wrong
            # side of the level the strategy is named for.
            if not midpoint_aligned:
                raise DomainValidationError("ALLOWED admission requires midpoint alignment")
            # The grade is separate geometry: CONFIRMED means the close took out
            # the governing reference candle's own extreme, so the whole candle was
            # cleared rather than just its midpoint. It is a strength label, not a
            # statement about R -- the initial stop comes from the five-minute
            # candle that crossed the level, which is a different candle, so the
            # two numbers are unrelated. Every admitted entry cleared the midpoint,
            # so the midpoint cannot be what distinguishes the two grades. The
            # comparison is restated here rather than imported from
            # ``strategy.red_bar_v2.grade_against_reference``: this validator
            # exists to re-derive the claim from the attached evidence, and code it
            # shared with the producer could never contradict it.

            cleared = (
                self.midpoint.index_close > self.reference.high
                if self.direction is Direction.BULLISH
                else self.midpoint.index_close < self.reference.low
            )
            expected_state = (
                RedBarV2State.CONFIRMED_BULLISH if self.direction is Direction.BULLISH else RedBarV2State.CONFIRMED_BEARISH
            ) if cleared else (
                RedBarV2State.PROVISIONAL_BULLISH if self.direction is Direction.BULLISH else RedBarV2State.PROVISIONAL_BEARISH
            )
            expected_strength = TrendStrength.CONFIRMED if cleared else TrendStrength.PROVISIONAL
            if self.current_state is not expected_state or self.trend_strength is not expected_strength:
                raise DomainValidationError(
                    "state and trend_strength must match the reference-candle grade"
                )
            if not isclose(float(self.midpoint.midpoint), float(self.reference.midpoint), rel_tol=0.0, abs_tol=_MIDPOINT_ABS_TOLERANCE):
                raise DomainValidationError("midpoint evidence must match reference midpoint")
            _require_text("admission_code", self.admission_code)
            _require_text("admission_reason", self.admission_reason)


@dataclass(frozen=True, slots=True)
class RedBarV2SignalBundle:
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
    instrument_key: str | None = None

    def __post_init__(self) -> None:
        for name in ("schema_version", "bundle_id", "signal_id", "strategy_version", "idempotency_key"):
            _require_text(name, getattr(self, name))
        if self.schema_version not in _SUPPORTED_BUNDLE_SCHEMA_VERSIONS:
            raise DomainValidationError(f"unsupported bundle schema_version: {self.schema_version}")
        if self.schema_version == "1.1" and self.instrument_key is None:
            raise DomainValidationError("schema 1.1 requires underlying instrument_key")
        if self.instrument_key is not None:
            _require_text("instrument_key", self.instrument_key)
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
        # Futures VWAP evidence is absent on a working-reference entry by design.
        # It is also the fallback that names the instrument on a schema-1.0
        # bundle, so a bundle without it has to carry its own `instrument_key` --
        # which schema 1.1 requires of every bundle anyway.
        if decision.futures_vwap is None and decision.entry_type is not EntryType.WORKING:
            raise DomainValidationError("signal bundle requires futures VWAP evidence")

        from .identity import build_red_bar_v2_bundle_id, build_red_bar_v2_idempotency_key, build_red_bar_v2_signal_id

        identity_instrument = self.instrument_key or (
            None if decision.futures_vwap is None else decision.futures_vwap.instrument_key
        )
        if identity_instrument is None:
            raise DomainValidationError(
                "signal bundle without futures VWAP evidence requires instrument_key"
            )

        expected_signal = build_red_bar_v2_signal_id(
            strategy_version=self.strategy_version,
            instrument_key=identity_instrument,
            trading_date=self.trading_date,
            reference_id=decision.reference.reference_id,
            evaluation_timestamp=self.evaluation_timestamp,
            entry_type=self.entry_type,
            direction=self.direction,
        )
        expected_bundle = build_red_bar_v2_bundle_id(signal_id=expected_signal, schema_version=self.schema_version)
        expected_idempotency = build_red_bar_v2_idempotency_key(signal_id=expected_signal, option_side=self.option_side)
        if self.signal_id != expected_signal:
            raise BundleIdentityError("signal_id does not match canonical bundle fields")
        if self.bundle_id != expected_bundle:
            raise BundleIdentityError("bundle_id does not match canonical signal and schema")
        if self.idempotency_key != expected_idempotency:
            raise BundleIdentityError("idempotency_key does not match canonical signal and option side")
