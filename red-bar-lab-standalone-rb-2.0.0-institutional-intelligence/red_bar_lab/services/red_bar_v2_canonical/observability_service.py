from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from .observability_models import (
    CanonicalBundleEventView,
    CanonicalEvidenceView,
    CanonicalHistoryRow,
    CanonicalParityRow,
    CanonicalParityView,
    CanonicalPersistenceView,
    CanonicalSection1View,
    CanonicalSection2View,
    CanonicalSection3View,
    CanonicalShadowObservationView,
    CanonicalShadowPageStatus,
)
from .observability_repository import ObservabilityResolutionRecord, RedBarV2CanonicalObservabilityRepository
from .persistence_models import CanonicalPersistenceCorruptionError, CanonicalPersistenceUnavailableError

_LOGGER = logging.getLogger(__name__)
INDIA_MARKET_TZ = ZoneInfo("Asia/Kolkata")
CLOCK_SKEW_TOLERANCE_SECONDS = 5.0


def _value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalPersistenceCorruptionError(f"naive {field}")
    return value.astimezone(INDIA_MARKET_TZ)


def _alignment(bullish: bool, bearish: bool) -> str:
    if bullish:
        return "BULLISH"
    if bearish:
        return "BEARISH"
    return "NEUTRAL"


def _freshness(record: ObservabilityResolutionRecord, now: datetime) -> tuple[str, float | None]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(INDIA_MARKET_TZ)
    event_time = _require_aware(record.envelope.section_2.evaluation_timestamp, "event timestamp")
    _require_aware(record.persisted_at, "persisted_at")
    trading_date = record.envelope.trading_date
    if trading_date > current.date():
        raise CanonicalPersistenceCorruptionError("future trading date")
    if event_time.date() != trading_date:
        raise CanonicalPersistenceCorruptionError("event timestamp market date mismatch")
    if trading_date < current.date():
        return "HISTORICAL", None
    age = (current - event_time).total_seconds()
    if age < -CLOCK_SKEW_TOLERANCE_SECONDS:
        raise CanonicalPersistenceCorruptionError("event timestamp materially in the future")
    age = max(age, 0.0)
    threshold = float(record.envelope.section_1.timestamps.maximum_age_seconds)
    return ("FRESH" if age <= threshold else "STALE"), age


def _section_1(record: ObservabilityResolutionRecord) -> CanonicalSection1View:
    section = record.envelope.section_1
    reference = section.reference
    timestamps = section.timestamps
    outcome = _value(section.outcome) or "UNAVAILABLE"
    if outcome == "REFERENCE_READY":
        explanation = "The persisted reference, NIFTY evidence and futures VWAP context were available at event time."
    elif outcome == "REFERENCE_WAITING":
        explanation = "The persisted event could not evaluate direction because its reference was not ready."
    elif outcome in {"CANDLES_STALE", "SESSION_MISALIGNED"}:
        explanation = "Persisted evidence existed, but its event-time timestamps were stale or misaligned."
    else:
        explanation = section.reason
    return CanonicalSection1View(
        outcome=outcome,
        reference_status="AVAILABLE" if reference is not None else "WAITING",
        trading_date=section.trading_date,
        reference_id=reference.reference_id if reference else None,
        reference_high=reference.high if reference else None,
        reference_low=reference.low if reference else None,
        reference_midpoint=reference.midpoint if reference else None,
        underlying_instrument=record.envelope.instrument_key,
        futures_instrument=section.futures_instrument_key,
        futures_expiry=section.futures_expiry,
        context_status=_value(timestamps.context_status) or "UNAVAILABLE",
        futures_volume_available=section.futures_volume_available,
        futures_vwap_available=section.futures_vwap_available,
        latest_index_timestamp=timestamps.latest_index_1m,
        latest_futures_timestamp=timestamps.latest_futures_1m,
        reason_code=section.reason_code,
        explanation=explanation,
    )


def _section_2(record: ObservabilityResolutionRecord) -> CanonicalSection2View:
    decision = record.envelope.section_2
    evidence: list[CanonicalEvidenceView] = []
    if decision.rsi is not None:
        evidence.append(CanonicalEvidenceView("RSI", f"{decision.rsi.value:.2f}", f"> {decision.rsi.bullish_threshold:.2f} bullish / < {decision.rsi.bearish_threshold:.2f} bearish", _alignment(decision.rsi.bullish_aligned, decision.rsi.bearish_aligned)))
    if decision.futures_vwap is not None:
        evidence.append(CanonicalEvidenceView("Futures vs VWAP", f"Price {decision.futures_vwap.comparison_price:.2f} / VWAP {decision.futures_vwap.vwap:.2f}", "Price above VWAP bullish / below VWAP bearish", _alignment(decision.futures_vwap.bullish_aligned, decision.futures_vwap.bearish_aligned)))
    if decision.midpoint is not None:
        evidence.append(CanonicalEvidenceView("Index vs midpoint", f"Close {decision.midpoint.index_close:.2f} / Midpoint {decision.midpoint.midpoint:.2f}", "Close above midpoint bullish / below midpoint bearish", _alignment(decision.midpoint.bullish_aligned, decision.midpoint.bearish_aligned)))
    outcome = _value(decision.admission_outcome) or "UNAVAILABLE"
    return CanonicalSection2View(
        admission_outcome=outcome,
        previous_state=_value(decision.previous_state) or "UNAVAILABLE",
        current_state=_value(decision.current_state) or "UNAVAILABLE",
        direction=_value(decision.direction),
        option_side=_value(decision.option_side),
        entry_type=_value(decision.entry_type),
        evaluation_timeframe=decision.evaluation_timeframe,
        trend_strength=_value(decision.trend_strength),
        admission_code=decision.admission_code,
        admission_reason=decision.admission_reason,
        evidence=tuple(evidence),
        explanation=f"Canonical admission was {outcome}. {decision.admission_reason} This observational result did not alter the legacy decision.",
    )


def _section_3(record: ObservabilityResolutionRecord, events: tuple[object, ...]) -> CanonicalSection3View:
    bundle = record.envelope.section_3
    if bundle is None:
        return CanonicalSection3View(False, None, None, None, None, None, None, None, None, None, None, None, (), "No bundle was created because canonical admission was not ALLOWED.")
    projected = tuple(
        CanonicalBundleEventView(
            event_type=_value(event.event_type) or "UNAVAILABLE",
            event_timestamp=event.event_timestamp,
            source=event.source,
            reason_code=event.reason_code,
        )
        for event in events
    )
    return CanonicalSection3View(
        bundle_available=True,
        bundle_id=bundle.bundle_id,
        signal_id=bundle.signal_id,
        idempotency_key=bundle.idempotency_key,
        underlying_instrument=bundle.instrument_key,
        trading_date=bundle.trading_date,
        direction=_value(bundle.direction),
        option_side=_value(bundle.option_side),
        entry_type=_value(bundle.entry_type),
        evaluation_timeframe=bundle.evaluation_timeframe,
        lifecycle_status=_value(bundle.lifecycle_status),
        created_at=bundle.created_at,
        event_history=projected,
        explanation="RED BAR V2 CANONICAL BUNDLE is available as immutable evidence. AVAILABLE does not mean executed.",
    )


def _parity(record: ObservabilityResolutionRecord) -> CanonicalParityView:
    parity = record.envelope.parity
    if parity is None:
        return CanonicalParityView("NOT AVAILABLE", None, (), (), "No persisted parity comparison is available for this observation.")
    values = (
        ("Direction", parity.legacy_direction, _value(parity.canonical_direction), "direction"),
        ("Option side", parity.legacy_option_side, _value(parity.canonical_option_side), "option_side"),
        ("Admission", str(parity.legacy_allowed), str(parity.canonical_allowed), "admission"),
        ("Entry type", parity.legacy_entry_type, _value(parity.canonical_entry_type), "entry_type"),
        ("Timeframe", parity.legacy_timeframe, parity.canonical_timeframe, "timeframe"),
        ("Trend strength", parity.legacy_trend_strength, _value(parity.canonical_trend_strength), "trend_strength"),
        ("Admission code", parity.legacy_admission_code, parity.canonical_admission_code, "admission_code"),
    )
    rows = tuple(CanonicalParityRow(label, str(legacy) if legacy is not None else "—", str(canonical) if canonical is not None else "—", "MISMATCH" if key in parity.mismatches else "MATCH") for label, legacy, canonical, key in values)
    return CanonicalParityView(
        "MATCH" if parity.matches else "MISMATCH",
        parity.matches,
        parity.mismatches,
        rows,
        "Canonical and legacy decisions agreed." if parity.matches else "Mismatch is observational architecture evidence only; legacy execution remained unchanged.",
    )


def _history(records: tuple[ObservabilityResolutionRecord, ...], now: datetime) -> tuple[CanonicalHistoryRow, ...]:
    rows: list[CanonicalHistoryRow] = []
    for record in records:
        envelope = record.envelope
        freshness, _ = _freshness(record, now)
        rows.append(CanonicalHistoryRow(
            event_time=envelope.section_2.evaluation_timestamp.astimezone(INDIA_MARKET_TZ).isoformat(),
            trading_date=envelope.trading_date.isoformat(),
            section_1_outcome=_value(envelope.section_1.outcome) or "UNAVAILABLE",
            admission_outcome=_value(envelope.section_2.admission_outcome) or "UNAVAILABLE",
            direction=_value(envelope.section_2.direction) or "—",
            option_side=_value(envelope.section_2.option_side) or "—",
            entry_type=_value(envelope.section_2.entry_type) or "—",
            parity="NOT AVAILABLE" if envelope.parity is None else ("MATCH" if envelope.parity.matches else "MISMATCH"),
            bundle_available="YES" if envelope.section_3 else "NO",
            resolution_id=envelope.resolution_id,
            freshness=freshness,
        ))
    return tuple(rows)


def _empty_status(*, availability: str, feature_enabled: bool, freshness: str, reason_code: str, error_category: str | None, database_display: str) -> CanonicalShadowObservationView:
    status = CanonicalShadowPageStatus(
        availability=availability,
        authority="LEGACY_RED_BAR_V2",
        canonical_authority="NONE",
        feature_enabled=feature_enabled,
        latest_event_timestamp=None,
        persisted_at=None,
        age_seconds=None,
        freshness=freshness,
        reason_code=reason_code,
        error_category=error_category,
        database_display=database_display,
    )
    return CanonicalShadowObservationView(status, None, None, None, None, None, ())


class RedBarV2CanonicalObservabilityService:
    """Build immutable read-only UI projections from persisted canonical evidence."""

    def __init__(self, repository: RedBarV2CanonicalObservabilityRepository, *, database_path: Path) -> None:
        self._repository = repository
        self._database_path = Path(database_path)

    def load(self, *, instrument_key: str, feature_enabled: bool, limit: int = 25, trading_date: date | None = None, now: datetime | None = None) -> CanonicalShadowObservationView:
        current = now or datetime.now(INDIA_MARKET_TZ)
        if current.tzinfo is None or current.utcoffset() is None:
            return _empty_status(availability="CANONICAL_READ_FAILED", feature_enabled=feature_enabled, freshness="UNAVAILABLE", reason_code="NAIVE_OBSERVABILITY_CLOCK", error_category="ValueError", database_display=f"…/{self._database_path.parent.name}/{self._database_path.name}")
        short_path = f"…/{self._database_path.parent.name}/{self._database_path.name}"
        if not feature_enabled:
            return _empty_status(availability="SHADOW_DISABLED", feature_enabled=False, freshness="UNAVAILABLE", reason_code="SHADOW_DISABLED", error_category=None, database_display=short_path)
        try:
            records = self._repository.recent_resolutions(instrument_key=instrument_key, trading_date=trading_date, limit=limit)
            if not records:
                return _empty_status(availability="WAITING_FOR_FIRST_OBSERVATION", feature_enabled=True, freshness="UNAVAILABLE", reason_code="NO_CANONICAL_OBSERVATIONS", error_category=None, database_display=short_path)
            latest = records[0]
            events = self._repository.bundle_events(bundle_id=latest.envelope.section_3.bundle_id) if latest.envelope.section_3 else ()
            freshness, age = _freshness(latest, current)
            delay = (latest.persisted_at - latest.envelope.section_2.evaluation_timestamp).total_seconds()
            persistence = CanonicalPersistenceView(
                resolution_id=latest.envelope.resolution_id,
                source_replay_id=latest.envelope.source_replay_id,
                schema_version=latest.envelope.schema_version,
                bundle_schema_version=latest.envelope.section_3.schema_version if latest.envelope.section_3 else None,
                persisted_at=latest.persisted_at,
                event_timestamp=latest.envelope.section_2.evaluation_timestamp,
                persistence_delay_seconds=delay,
                payload_integrity="VERIFIED",
                event_count=len(events),
                persistence_outcome="PERSISTED",
                explanation="Digest and canonical schema validation succeeded during the read-only query.",
            )
            status = CanonicalShadowPageStatus(
                availability="CANONICAL_DATA_AVAILABLE",
                authority="LEGACY_RED_BAR_V2",
                canonical_authority="NONE",
                feature_enabled=True,
                latest_event_timestamp=latest.envelope.section_2.evaluation_timestamp,
                persisted_at=latest.persisted_at,
                age_seconds=age,
                freshness=freshness,
                reason_code="PERSISTED_CANONICAL_OBSERVATION",
                error_category=None,
                database_display=short_path,
            )
            return CanonicalShadowObservationView(status, _section_1(latest), _section_2(latest), _section_3(latest, events), _parity(latest), persistence, _history(records, current))
        except CanonicalPersistenceCorruptionError as exc:
            return _empty_status(availability="CANONICAL_DATA_CORRUPT", feature_enabled=True, freshness="CORRUPT", reason_code="CANONICAL_DATA_CORRUPT", error_category=type(exc).__name__, database_display=short_path)
        except CanonicalPersistenceUnavailableError as exc:
            return _empty_status(availability="CANONICAL_DATABASE_UNAVAILABLE", feature_enabled=True, freshness="UNAVAILABLE", reason_code="CANONICAL_DATABASE_UNAVAILABLE", error_category=type(exc).__name__, database_display=short_path)
        except Exception as exc:
            _LOGGER.exception(
                "red_bar_v2_canonical_observability_read_failed",
                extra={"instrument_key": instrument_key, "exception_class": type(exc).__name__},
            )
            return _empty_status(availability="CANONICAL_READ_FAILED", feature_enabled=True, freshness="UNAVAILABLE", reason_code="CANONICAL_READ_FAILED", error_category=type(exc).__name__, database_display=short_path)
