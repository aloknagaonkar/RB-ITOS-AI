from __future__ import annotations

from datetime import date
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import RedBarV2SignalBundle

from .persistence_models import (
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceResult,
    PersistedRedBarV2Resolution,
)


class RedBarV2CanonicalRepository(Protocol):
    def persist_resolution(
        self,
        envelope: PersistedRedBarV2Resolution,
    ) -> CanonicalPersistenceResult: ...

    def get_resolution(
        self,
        resolution_id: str,
    ) -> PersistedRedBarV2Resolution | None: ...

    def get_bundle(
        self,
        bundle_id: str,
    ) -> RedBarV2SignalBundle | None: ...

    def get_bundle_by_signal_id(
        self,
        signal_id: str,
    ) -> RedBarV2SignalBundle | None: ...

    def list_session_resolutions(
        self,
        *,
        instrument_key: str,
        trading_date: date,
    ) -> tuple[PersistedRedBarV2Resolution, ...]: ...

    def list_bundle_events(
        self,
        bundle_id: str,
    ) -> tuple[CanonicalBundleLifecycleEvent, ...]: ...
