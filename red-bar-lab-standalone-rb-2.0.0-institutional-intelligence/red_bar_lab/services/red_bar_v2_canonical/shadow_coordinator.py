from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter_ns
from typing import Any, Callable

from red_bar_lab.observability.evidence import generate_run_id, with_step_evidence

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
        evidence_database: Any | None = None,
        evidence_writer: Any | None = None,
    ) -> None:
        self._persistence_service = persistence_service
        self._enabled = bool(enabled)
        self._telemetry_sink = telemetry_sink
        # Optional handle to the main RedBarDatabase. Kept for
        # backwards compatibility; new code should pass
        # ``evidence_writer`` instead.
        self._evidence_database = evidence_database
        # A ProcessEvidenceWriter that targets the main RedBarDatabase.
        # When set, the coordinator writes one ``process_evidence`` row
        # per stage so the cadence panel can show a per-stage timeline.
        self._evidence_writer = evidence_writer

    def _emit(self, record: dict[str, object]) -> None:
        if self._telemetry_sink is not None:
            self._telemetry_sink(record)

    def _write_run_correlation(
        self,
        run_id: str,
        event_timestamp: datetime,
        observation: RedBarV2ShadowObservation,
    ) -> None:
        """Best-effort: write the canonical_shadow process's most-recent
        run_id into ``process_run_correlation`` so the cadence panel can
        correlate the shadow with the upstream collector/orchestrator."""
        # We need a database that has ``write_process_run_correlation``.
        # The evidence_writer is a ``ProcessEvidenceWriter``; reach for
        # its database via duck typing.
        database = getattr(self._evidence_writer, "_database", None)
        if database is None:
            return
        try:
            database.write_process_run_correlation(
                process_name="canonical_shadow",
                run_id=run_id,
                started_at=event_timestamp.isoformat(),
                artifacts={
                    "resolution_id": observation.resolution_id,
                    "bundle_id": observation.bundle_id,
                    "parity_matches": observation.parity_matches,
                    "reason_code": observation.reason_code,
                },
            )
        except Exception:  # noqa: BLE001
            pass

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
        run_id: str | None = None,
    ) -> RedBarV2ShadowObservation:
        started = perf_counter_ns()
        run_id = run_id or generate_run_id("canonical_shadow")
        # Wire the run_id into the persistence service so its
        # ``persistence`` step lands in the same process_evidence row
        # group as resolution and parity.
        self._persistence_service.run_id = run_id
        # Best-effort wrapper around the whole observation. If
        # ``evidence_writer`` is None (e.g. in tests) we still want to
        # run, so we fall back to a no-op context.
        if self._evidence_writer is not None:
            outer_cm = _writer_evidence_step(
                self._evidence_writer,
                process_name="canonical_shadow",
                step_name="shadow_observe",
                run_id=run_id,
                artifacts={"source_replay_id": source_replay_id},
            )
        else:
            outer_cm = _noop_cm()

        with outer_cm:
            observation = self._observe_inner(
                started=started,
                run_id=run_id,
                replay=replay,
                health=health,
                replay_event=replay_event,
                market_metadata=market_metadata,
                legacy_result=legacy_result,
                source_replay_id=source_replay_id,
                event_timestamp=event_timestamp,
            )
            # Best-effort: write the most-recent run_id for this process
            # so the page can correlate cross-process cycles.
            self._write_run_correlation(run_id, event_timestamp, observation)
            return observation

    def _observe_inner(
        self,
        *,
        started: int,
        run_id: str,
        replay: object,
        health: object,
        replay_event: object | None,
        market_metadata: LegacyV2MarketMetadata,
        legacy_result: object,
        source_replay_id: str,
        event_timestamp: datetime,
    ) -> RedBarV2ShadowObservation:
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

        stage_timings_ms: dict[str, float] = {}
        try:
            # Stage 1: resolution (assembles Sections 1-3 — Signal Discovery
            # is the section_1 portion of this).
            with _writer_stage_evidence(
                self._evidence_writer,
                self._evidence_database,
                process_name="canonical_shadow",
                step_name="resolution",
                run_id=run_id,
            ):
                stage_started = perf_counter_ns()
                resolution = resolve_red_bar_v2_canonical(
                    replay=replay,
                    health=health,
                    replay_event=replay_event,
                    market_metadata=market_metadata,
                    evidence=None,
                    source_replay_id=source_replay_id,
                    resolved_at=event_timestamp,
                )
                stage_timings_ms["resolution"] = (
                    perf_counter_ns() - stage_started
                ) / 1_000_000.0
                # Per-section sub-steps so the user can see "Signal
                # Discovery" specifically in the per-step evidence panel.
                _record_section_outcome(
                    self._evidence_writer,
                    self._evidence_database,
                    section=resolution.section_1,
                    run_id=run_id,
                    step_name="section_1_signal_discovery",
                )
                _record_section_outcome(
                    self._evidence_writer,
                    self._evidence_database,
                    section=resolution.section_2,
                    run_id=run_id,
                    step_name="section_2_lifecycle_eligibility",
                )
                if resolution.section_3 is not None:
                    _record_section_outcome(
                        self._evidence_writer,
                        self._evidence_database,
                        section=resolution.section_3,
                        run_id=run_id,
                        step_name="section_3_signal_bundle",
                    )

            # Stage 2: parity comparison.
            with _writer_stage_evidence(
                self._evidence_writer,
                self._evidence_database,
                process_name="canonical_shadow",
                step_name="parity",
                run_id=run_id,
            ):
                stage_started = perf_counter_ns()
                parity = compare_legacy_to_canonical(
                    legacy_event=legacy_result,
                    canonical_decision=resolution.section_2,
                    legacy_timeframe=resolution.section_2.evaluation_timeframe,
                )
                stage_timings_ms["parity"] = (
                    perf_counter_ns() - stage_started
                ) / 1_000_000.0

            # Stage 3: persistence (writes to canonical_shadow_evaluations).
            # The persistence service itself records a ``persistence``
            # step via the writer; we don't double-record here.
            stage_started = perf_counter_ns()
            persisted = self._persistence_service.persist(
                resolution=resolution,
                parity=parity,
                instrument_key=market_metadata.underlying_instrument_key,
            )
            stage_timings_ms["persistence"] = (
                perf_counter_ns() - stage_started
            ) / 1_000_000.0
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
                "stage_timings_ms": {
                    name: round(duration, 3)
                    for name, duration in stage_timings_ms.items()
                },
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


@contextmanager
def _noop_cm():
    yield -1


@contextmanager
def _writer_evidence_step(
    writer: Any | None,
    *,
    process_name: str,
    step_name: str,
    run_id: str,
    artifacts: dict[str, object] | None = None,
):
    """Open a top-level evidence row using the ProcessEvidenceWriter."""
    if writer is None:
        yield -1
        return
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter_ns()
    try:
        yield -1
        duration_ms = (perf_counter_ns() - started) / 1_000_000.0
        writer(
            process_name=process_name,
            run_id=run_id,
            step_name=step_name,
            parent_step=None,
            started_at=started_at,
            status="OK",
            duration_ms=duration_ms,
            artifacts=artifacts,
        )
    except Exception as exc:  # noqa: BLE001
        duration_ms = (perf_counter_ns() - started) / 1_000_000.0
        try:
            writer(
                process_name=process_name,
                run_id=run_id,
                step_name=step_name,
                parent_step=None,
                started_at=started_at,
                status="ERROR",
                duration_ms=duration_ms,
                error_message=f"{type(exc).__name__}: {exc}"[:500],
                artifacts=artifacts,
            )
        except Exception:  # noqa: BLE001
            pass
        raise


@contextmanager
def _writer_stage_evidence(
    writer: Any | None,
    database: Any | None,
    *,
    process_name: str,
    step_name: str,
    run_id: str,
):
    """Per-stage evidence row. Uses the writer when available; falls
    back to ``with_step_evidence`` against the raw database if only
    ``database`` was passed (back-compat)."""
    if writer is not None:
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc).isoformat()
        started = perf_counter_ns()
        try:
            yield -1
            duration_ms = (perf_counter_ns() - started) / 1_000_000.0
            writer(
                process_name=process_name,
                run_id=run_id,
                step_name=step_name,
                parent_step="shadow_observe",
                started_at=started_at,
                status="OK",
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001
            duration_ms = (perf_counter_ns() - started) / 1_000_000.0
            try:
                writer(
                    process_name=process_name,
                    run_id=run_id,
                    step_name=step_name,
                    parent_step="shadow_observe",
                    started_at=started_at,
                    status="ERROR",
                    duration_ms=duration_ms,
                    error_message=f"{type(exc).__name__}: {exc}"[:500],
                )
            except Exception:  # noqa: BLE001
                pass
            raise
        return
    # Fallback: legacy with_step_evidence path.
    with _evidence_step(database, process_name, step_name, run_id) as step_id:
        yield step_id


@contextmanager
def _evidence_step(
    database: Any | None,
    process_name: str,
    step_name: str,
    run_id: str,
):
    """Back-compat: tiny wrapper that uses ``with_step_evidence`` when a
    DB is available, otherwise yields a no-op context so callers don't
    have to branch."""
    if database is None:
        yield -1
        return
    with with_step_evidence(
        database,
        process_name=process_name,
        step_name=step_name,
        run_id=run_id,
    ) as step_id:
        yield step_id


def _record_section_outcome(
    writer: Any | None,
    database: Any | None = None,
    *,
    section: object | None = None,
    run_id: str,
    step_name: str,
) -> None:
    """Write a single ``process_evidence`` row summarizing one section's
    outcome. Best-effort: any DB error is swallowed because the
    surrounding shadow run has already succeeded.
    """
    if section is None:
        return
    outcome = getattr(section, "outcome", None) or getattr(
        section, "admission_outcome", None
    )
    outcome_value = outcome.value if hasattr(outcome, "value") else str(outcome or "UNKNOWN")
    artifacts = {
        "outcome": str(outcome_value),
        "reason": getattr(section, "reason", None)
        or getattr(section, "reason_code", None),
    }
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc).isoformat()
    if writer is not None:
        try:
            writer(
                process_name="canonical_shadow",
                run_id=run_id,
                step_name=step_name,
                parent_step="resolution",
                started_at=started_at,
                status="OK",
                duration_ms=0.0,
                artifacts=artifacts,
            )
            return
        except Exception:  # noqa: BLE001
            return
    if database is None:
        return
    try:
        with with_step_evidence(
            database,
            process_name="canonical_shadow",
            step_name=step_name,
            run_id=run_id,
            artifacts=artifacts,
        ):
            pass
    except Exception:  # noqa: BLE001
        pass
