from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RedBarV2Stage:
    number: int
    stage_id: str
    label: str

    @property
    def display_name(self) -> str:
        return f"{self.number}. {self.label}"


RED_BAR_V2_STAGES = (
    RedBarV2Stage(1, "INPUT_READINESS", "Input Readiness"),
    RedBarV2Stage(2, "STRATEGY_DECISION", "Strategy Decision"),
    RedBarV2Stage(3, "SIGNAL_BUNDLE", "Signal Bundle"),
    RedBarV2Stage(4, "ARCHITECTURE_PARITY", "Architecture Parity"),
    RedBarV2Stage(5, "PERSISTENCE_INTEGRITY", "Persistence & Integrity"),
    RedBarV2Stage(6, "RECENT_OBSERVATIONS", "Recent Observations"),
    RedBarV2Stage(7, "PROCESS_EXPLANATION", "Process Explanation"),
    RedBarV2Stage(8, "OPPORTUNITY_QUEUE", "Opportunity Queue"),
    RedBarV2Stage(9, "RESERVATION_BOUNDARY", "Reservation Boundary"),
    RedBarV2Stage(10, "PAPER_EXECUTION", "Paper Execution"),
    RedBarV2Stage(11, "RUNTIME_HEALTH", "Runtime Health"),
    RedBarV2Stage(12, "PROVIDER_READINESS", "Provider Readiness"),
)

STAGE_BY_ID = {stage.stage_id: stage for stage in RED_BAR_V2_STAGES}


__all__ = ["RED_BAR_V2_STAGES", "STAGE_BY_ID", "RedBarV2Stage"]
