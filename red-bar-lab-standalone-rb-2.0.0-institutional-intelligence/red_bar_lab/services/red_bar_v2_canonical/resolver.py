from __future__ import annotations

from datetime import datetime
from time import perf_counter_ns
from typing import Mapping

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome
from red_bar_lab.intelligence.red_bar_v2_futures_context import RedBarV2VwapSourceHealth

from .bundle_factory import create_red_bar_v2_signal_bundle
from .event_access import event_bool, event_details
from .evidence_producer import evidence_from_event_details
from .exceptions import CanonicalResolutionError, LegacyMappingError
from .legacy_adapter import build_canonical_decision, build_canonical_input_readiness
from .models import LegacyV2DecisionEvidence, LegacyV2MarketMetadata, RedBarV2CanonicalResolution


def _optional_timestamp(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CanonicalResolutionError(f"event-time health {field} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalResolutionError(f"event-time health {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanonicalResolutionError(f"event-time health {field} must be timezone-aware")
    return parsed


def _event_time_health(replay_event: object | None, fallback: object) -> object:
    """Prefer the health snapshot captured with the replay event.

    The health returned by a full-day replay represents the latest/final replay
    state and may differ from the earlier health that admitted a candidate.
    Canonical event resolution must therefore use the health serialized beside
    that event when available.
    """
    payload = event_details(replay_event).get("vwap_source_health")
    if payload is None:
        return fallback
    if not isinstance(payload, Mapping):
        raise CanonicalResolutionError("event-time vwap_source_health must be a mapping")

    def text(name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise CanonicalResolutionError(
                f"event-time health {name} must be a non-empty string"
            )
        return value

    def integer(name: str) -> int:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise CanonicalResolutionError(f"event-time health {name} must be an int")
        return value

    coverage = payload.get("alignment_coverage_pct")
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
        raise CanonicalResolutionError(
            "event-time health alignment_coverage_pct must be numeric"
        )

    return RedBarV2VwapSourceHealth(
        status=text("status"),
        reason=text("reason"),
        price_source_instrument=text("price_source_instrument"),
        rsi_source_instrument=text("rsi_source_instrument"),
        vwap_source_instrument=text("vwap_source_instrument"),
        timeframe=text("timeframe"),
        index_rows=integer("index_rows"),
        futures_rows=integer("futures_rows"),
        aligned_rows=integer("aligned_rows"),
        alignment_coverage_pct=float(coverage),
        positive_volume_rows=integer("positive_volume_rows"),
        index_timestamp=_optional_timestamp(payload.get("index_timestamp"), "index_timestamp"),
        futures_timestamp=_optional_timestamp(payload.get("futures_timestamp"), "futures_timestamp"),
        last_aligned_timestamp=_optional_timestamp(
            payload.get("last_aligned_timestamp"), "last_aligned_timestamp"
        ),
        execution_scope=text("execution_scope"),
    )


def resolve_red_bar_v2_canonical(
    *,
    replay: object,
    health: object,
    replay_event: object | None,
    market_metadata: LegacyV2MarketMetadata,
    evidence: LegacyV2DecisionEvidence | None = None,
    source_replay_id: str,
    resolved_at: datetime,
    schema_version: str = "1.1",
) -> RedBarV2CanonicalResolution:
    """Assemble canonical Sections 1-3 without changing legacy authority."""
    if not isinstance(source_replay_id, str) or not source_replay_id.strip():
        raise CanonicalResolutionError("source_replay_id must be non-empty")
    if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
        raise CanonicalResolutionError("resolved_at must be timezone-aware")

    effective_health = _event_time_health(replay_event, health)
    section_1 = build_canonical_input_readiness(
        replay=replay,
        health=effective_health,
        market_metadata=market_metadata,
    )

    resolved_evidence = evidence
    if resolved_evidence is None and event_bool(replay_event, "candidate_allowed") is True:
        try:
            resolved_evidence = evidence_from_event_details(event_details(replay_event))
        except LegacyMappingError as exc:
            raise CanonicalResolutionError(
                "allowed replay event does not expose complete authoritative event-time evidence"
            ) from exc

    if resolved_evidence is not None:
        if resolved_evidence.underlying_instrument_key != market_metadata.underlying_instrument_key:
            raise CanonicalResolutionError(
                "event evidence underlying instrument disagrees with replay metadata"
            )
        if resolved_evidence.futures_instrument_key != market_metadata.futures_instrument_key:
            raise CanonicalResolutionError(
                "event evidence futures instrument disagrees with health metadata"
            )

    section_2 = build_canonical_decision(
        replay_event=replay_event,
        readiness=section_1,
        evidence=resolved_evidence,
    )

    section_3 = None
    if section_2.admission_outcome is AdmissionOutcome.ALLOWED:
        if resolved_evidence is None:
            raise CanonicalResolutionError("allowed resolution requires event-time evidence")
        section_3 = create_red_bar_v2_signal_bundle(
            instrument_key=resolved_evidence.underlying_instrument_key,
            decision=section_2,
            created_at=resolved_at,
            schema_version=schema_version,
        )

    return RedBarV2CanonicalResolution(
        section_1=section_1,
        section_2=section_2,
        section_3=section_3,
        source_replay_id=source_replay_id,
        resolved_at=resolved_at,
    )


def benchmark_resolver_mapping(iterations: int, resolve_once) -> float:
    """Return average resolver overhead in milliseconds for a prepared fixture."""
    if not isinstance(iterations, int) or iterations <= 0:
        raise CanonicalResolutionError("iterations must be a positive integer")
    started = perf_counter_ns()
    for _ in range(iterations):
        resolve_once()
    elapsed = perf_counter_ns() - started
    return elapsed / iterations / 1_000_000.0
