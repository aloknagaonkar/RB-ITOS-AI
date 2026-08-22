from __future__ import annotations

from datetime import datetime
from time import perf_counter_ns

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome

from .bundle_factory import create_red_bar_v2_signal_bundle
from .event_access import event_bool, event_details
from .evidence_producer import evidence_from_event_details
from .exceptions import CanonicalResolutionError, LegacyMappingError
from .legacy_adapter import build_canonical_decision, build_canonical_input_readiness
from .models import LegacyV2DecisionEvidence, LegacyV2MarketMetadata, RedBarV2CanonicalResolution


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

    section_1 = build_canonical_input_readiness(
        replay=replay,
        health=health,
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
            raise CanonicalResolutionError("event evidence underlying instrument disagrees with replay metadata")
        if resolved_evidence.futures_instrument_key != market_metadata.futures_instrument_key:
            raise CanonicalResolutionError("event evidence futures instrument disagrees with health metadata")

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
