from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paper_canary_models import PaperCanaryRuntimeState
from .paper_canary_state_store import (
    AtomicJsonPaperCanaryStateStore,
    PaperCanaryStateCorruptionError,
    PaperCanaryStateStorageError,
)


@dataclass(frozen=True, slots=True)
class PaperCanaryRuntimeObservation:
    status: str
    state: PaperCanaryRuntimeState | None


class PaperCanaryRuntimeObservabilityService:
    """Read-only state-file projection. It never builds or starts a runtime."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = Path(state_path)

    def load(self, *, worker_enabled: bool, mode: str) -> PaperCanaryRuntimeObservation:
        if not worker_enabled:
            return PaperCanaryRuntimeObservation("WORKER_DISABLED", None)
        if mode == "OBSERVE_ONLY":
            return PaperCanaryRuntimeObservation("OBSERVE_ONLY", None)
        if mode != "PAPER_CANARY":
            return PaperCanaryRuntimeObservation("CONFIGURATION_INVALID", None)
        try:
            state = AtomicJsonPaperCanaryStateStore(self.state_path).load()
        except PaperCanaryStateCorruptionError:
            return PaperCanaryRuntimeObservation("RUNTIME_STATE_CORRUPT", None)
        except PaperCanaryStateStorageError:
            return PaperCanaryRuntimeObservation("RUNTIME_STATE_UNAVAILABLE", None)
        if state is None:
            return PaperCanaryRuntimeObservation("RUNTIME_STATE_UNAVAILABLE", None)
        status = {
            "DISABLED": "WORKER_DISABLED",
            "OBSERVE_ONLY": "OBSERVE_ONLY",
            "HEALTHY_IDLE": "HEALTHY_IDLE",
            "PAPER_ACTION_COMPLETED": "PAPER_ACTION_COMPLETED",
            "ENTRY_SUSPENDED": "ENTRY_SUSPENDED",
            "RECOVERY_ONLY": "RECOVERY_ONLY",
            "CIRCUIT_OPEN": "CIRCUIT_OPEN",
            "RECOVERY_PROBE": "RECOVERY_PROBE",
            "STORAGE_UNAVAILABLE": "STORAGE_UNAVAILABLE",
            "CONFIGURATION_INVALID": "CONFIGURATION_INVALID",
        }.get(state.worker_status.value, "RUNTIME_STATE_CORRUPT")
        return PaperCanaryRuntimeObservation(status, state)
