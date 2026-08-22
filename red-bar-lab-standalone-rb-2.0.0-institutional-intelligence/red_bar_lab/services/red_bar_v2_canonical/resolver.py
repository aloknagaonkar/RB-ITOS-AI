from __future__ import annotations

from datetime import datetime

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome

from .bundle_factory import create_red_bar_v2_signal_bundle
from .exceptions import CanonicalResolutionError
from .legacy_adapter import build_canonical_decision, build_canonical_input_readiness
from .models import (
    LegacyV2DecisionEvidence,
    LegacyV2MarketMetadata,
    RedBarV2CanonicalResolution,
)


def resolve_red_bar_v2_canonical(
    *,
    replay: object | None,
    health: object | None,
    replay_event: object | None,
    market_metadata: LegacyV2MarketMetadata,
    evidence: LegacyV2DecisionEvidence | None,
    source_replay_id: str,
    resolved_at: datetime,
    schema_version: str = "1.0",
) -> RedBarV2CanonicalResolution:
    """Assemble canonical Sections 1-3 from one legacy V2 result.

    This service is pure orchestration. It does not query market data, persist
    bundles, publish paper signals, or alter legacy execution authority.
    """
    if not isinstance(source_replay_id, str) or not source_replay_id.strip():
        raise CanonicalResolutionError("source_replay_id must be non-empty")
    if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
        raise CanonicalResolutionError("resolved_at must be timezone-aware")

    section_1 = build_canonical_input_readiness(
        replay=replay,
        health=health,
        market_metadata=market_metadata,
    )
    section_2 = build_canonical_decision(
        replay_event=replay_event,
        readiness=section_1,
        evidence=evidence,
    )

    section_3 = None
    if section_2.admission_outcome is AdmissionOutcome.ALLOWED:
        if evidence is None:
            raise CanonicalResolutionError("allowed resolution requires event-time evidence")
        section_3 = create_red_bar_v2_signal_bundle(
            instrument_key=evidence.instrument_key,
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
