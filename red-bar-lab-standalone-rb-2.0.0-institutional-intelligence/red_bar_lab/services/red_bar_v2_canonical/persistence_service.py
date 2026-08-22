from __future__ import annotations

from datetime import datetime
from typing import Callable

from .models import RedBarV2CanonicalResolution, RedBarV2ParityResult
from .persistence_identity import build_canonical_resolution_id
from .persistence_models import (
    CanonicalPersistenceError,
    CanonicalPersistenceResult,
    PersistedRedBarV2Resolution,
)
from .repository_protocol import RedBarV2CanonicalRepository


class RedBarV2CanonicalPersistenceService:
    def __init__(
        self,
        repository: RedBarV2CanonicalRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or (lambda: datetime.now().astimezone())

    def persist(
        self,
        *,
        resolution: RedBarV2CanonicalResolution,
        parity: RedBarV2ParityResult | None,
        instrument_key: str,
    ) -> CanonicalPersistenceResult:
        if not isinstance(instrument_key, str) or not instrument_key.strip():
            raise CanonicalPersistenceError("instrument_key must be non-empty")
        if not resolution.source_replay_id.strip():
            raise CanonicalPersistenceError("source_replay_id must be non-empty")
        if resolution.resolved_at.tzinfo is None or resolution.resolved_at.utcoffset() is None:
            raise CanonicalPersistenceError("resolved_at must be timezone-aware")

        decision = resolution.section_2
        readiness = resolution.section_1
        bundle = resolution.section_3
        trading_date = readiness.trading_date
        if decision.reference is not None and decision.reference.trading_date != trading_date:
            raise CanonicalPersistenceError("decision reference trading date disagrees with readiness")
        if bundle is not None:
            if bundle.instrument_key != instrument_key:
                raise CanonicalPersistenceError("instrument_key must match bundle underlying instrument")
            if bundle.trading_date != trading_date:
                raise CanonicalPersistenceError("bundle trading date disagrees with readiness")
        if parity is not None:
            if parity.canonical_direction is not decision.direction:
                raise CanonicalPersistenceError("parity direction disagrees with canonical decision")
            if parity.canonical_option_side is not decision.option_side:
                raise CanonicalPersistenceError("parity option side disagrees with canonical decision")
            if parity.canonical_entry_type is not decision.entry_type:
                raise CanonicalPersistenceError("parity entry type disagrees with canonical decision")
            if parity.canonical_admission_code != decision.admission_code:
                raise CanonicalPersistenceError("parity admission code disagrees with canonical decision")

        resolution_id = build_canonical_resolution_id(
            strategy_id=decision.strategy_id,
            strategy_version=decision.strategy_version,
            instrument_key=instrument_key,
            trading_date=trading_date,
            source_replay_id=resolution.source_replay_id,
            evaluation_timestamp=decision.evaluation_timestamp,
            entry_type=decision.entry_type,
            direction=decision.direction,
            admission_outcome=decision.admission_outcome,
        )
        envelope = PersistedRedBarV2Resolution(
            schema_version="1.0",
            resolution_id=resolution_id,
            instrument_key=instrument_key,
            trading_date=trading_date,
            source_replay_id=resolution.source_replay_id,
            resolved_at=resolution.resolved_at,
            section_1=readiness,
            section_2=decision,
            section_3=bundle,
            parity=parity,
        )
        return self.repository.persist_resolution(envelope)
