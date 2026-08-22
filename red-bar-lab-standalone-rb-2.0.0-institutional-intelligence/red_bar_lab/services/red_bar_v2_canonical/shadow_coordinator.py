from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import perf_counter_ns
from typing import Callable

from .exceptions import CanonicalResolutionError, LegacyMappingError
from .models import LegacyV2MarketMetadata
from .parity import compare_legacy_to_canonical
from .persistence_models import (
    CanonicalPersistenceConflictError,
    CanonicalPersistenceCorruptionError,
    CanonicalPersistenceUnavailableError,
    PersistenceOutcome,
)
from .persistence_service import RedBarV2CanonicalPersistenceService
from .resolver import resolve_red_bar_v2_canonical


@dataclass(frozen=True, slots=True)
class RedBarV2ShadowObservation:
    attempted: bool
    persisted: bool
    outcome: PersistenceOutcome | None
    resolution_id: str | None
    bundle_id: str | None
    parity_matches: bool | None
    reason_code: str
    duration_ms: float
    error_category: str | None
    mismatch_fields: tuple[str, ...] = ()


class RedBarV2CanonicalShadowCoordinator:
    """Observe one authoritative legacy event without execution authority."""

    def __init__(
        self,
        persistence_service: RedBarV2CanonicalPersistenceService,
        *,
        enabled: bool,
        telemetry_sink: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._persistence_service = persistence_service
        self._enabled = bool(enabled)
        self._telemetry_sink = telemetry_sink

    def _emit(self, record: dict[str, object]) -> None:
        if self._telemetry_sink is not None:
            self._telemetry_sink(record)

    def observe(
        self,
        *,
        replay: object,
        health: object,
        replay_event: object | None,
        market_metadata: LegacyV2MarketMetadata,
        legacy_result: object,
        source_replay_id: str,
        event_timestamp: datetime,
    ) -> RedBarV2ShadowObservation:
        started = perf_counter_ns()
        if not self._enabled:
            return RedBarV2ShadowObservation(
                attempted=False, persisted=False, outcome=None,
                resolution_id=None, bundle_id=None, parity_matches=None,
                reason_code="SHADOW_DISABLED", duration_ms=0.0,
                error_category="SHADOW_DISABLED",
            )
        if event_timestamp.tzinfo is None or event_timestamp.utcoffset() is None:
            return RedBarV2ShadowObservation(
                attempted=True, persisted=False, outcome=None,
                resolution_id=None, bundle_id=None, parity_matches=None,
                reason_code="NAIVE_EVENT_TIMESTAMP",
                duration_ms=(perf_counter_ns() - started) / 1_000_000.0,
                error_category="INPUT_UNAVAILABLE",
            )

        try:
            resolution = resolve_red_bar_v2_canonical(
                replay=replay,
                health=health,
                replay_event=replay_event,
                market_metadata=market_metadata,
                evidence=None,
                source_replay_id=source_replay_id,
                resolved_at=event_timestamp,
            )
            parity = compare_legacy_to_canonical(
                legacy_event=legacy_result,
                canonical_decision=resolution.section_2,
                legacy_timeframe=resolution.section_2.evaluation_timeframe,
            )
            persisted = self._persistence_service.persist(
                resolution=resolution,
                parity=parity,
                instrument_key=market_metadata.underlying_instrument_key,
            )
            mismatch_fields = tuple(parity.mismatches)
            reason_code = (
                "PARITY_MISMATCH" if not parity.matches
                else "IDEMPOTENT_REPLAY" if persisted.outcome is PersistenceOutcome.IDEMPOTENT_REPLAY
                else "PERSISTED"
            )
            observation = RedBarV2ShadowObservation(
                attempted=True,
                persisted=True,
                outcome=persisted.outcome,
                resolution_id=persisted.resolution_id,
                bundle_id=persisted.bundle_id,
                parity_matches=parity.matches,
                reason_code=reason_code,
                duration_ms=(perf_counter_ns() - started) / 1_000_000.0,
                error_category=None if parity.matches else "PARITY_MISMATCH",
                mismatch_fields=mismatch_fields,
            )
            self._emit({
                "strategy_id": resolution.section_2.strategy_id,
                "strategy_version": resolution.section_2.strategy_version,
                "source_replay_id": source_replay_id,
                "evaluation_timestamp": event_timestamp.isoformat(),
                "underlying_instrument": market_metadata.underlying_instrument_key,
                "futures_instrument": market_metadata.futures_instrument_key,
                "admission_outcome": resolution.section_2.admission_outcome.value,
                "direction": resolution.section_2.direction.value if resolution.section_2.direction else None,
                "option_side": resolution.section_2.option_side.value if resolution.section_2.option_side else None,
                "entry_type": resolution.section_2.entry_type.value if resolution.section_2.entry_type else None,
                "parity_matches": parity.matches,
                "parity_mismatches": mismatch_fields,
                "persistence_outcome": persisted.outcome.value,
                "resolution_id": persisted.resolution_id,
                "bundle_id": persisted.bundle_id,
                "duration_ms": observation.duration_ms,
                "error_category": observation.error_category,
                "reason_code": reason_code,
            })
            return observation
        except (CanonicalResolutionError, LegacyMappingError) as error:
            category = "RESOLUTION_FAILED"
            error_type = type(error).__name__
        except CanonicalPersistenceConflictError as error:
            category = "PERSISTENCE_CONFLICT"
            error_type = type(error).__name__
        except CanonicalPersistenceCorruptionError as error:
            category = "PERSISTENCE_CORRUPTION"
            error_type = type(error).__name__
        except CanonicalPersistenceUnavailableError as error:
            category = "PERSISTENCE_UNAVAILABLE"
            error_type = type(error).__name__
        except Exception as error:  # shadow boundary: never interrupt legacy authority
            category = "UNEXPECTED_SHADOW_FAILURE"
            error_type = type(error).__name__

        duration_ms = (perf_counter_ns() - started) / 1_000_000.0
        self._emit({
            "strategy_id": "RED_BAR_V2",
            "source_replay_id": source_replay_id,
            "evaluation_timestamp": event_timestamp.isoformat(),
            "underlying_instrument": market_metadata.underlying_instrument_key,
            "futures_instrument": market_metadata.futures_instrument_key,
            "duration_ms": duration_ms,
            "error_category": category,
            "reason_code": category,
            "error_type": error_type,
        })
        return RedBarV2ShadowObservation(
            attempted=True, persisted=False, outcome=None,
            resolution_id=None, bundle_id=None, parity_matches=None,
            reason_code=category, duration_ms=duration_ms,
            error_category=category,
        )
