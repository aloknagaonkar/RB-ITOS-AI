from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from red_bar_lab.services.historical_dri_relevant_coverage import (
    HistoricalDRIRelevantCoverageAudit,
    analyze_historical_dri_relevant_coverage,
)


@dataclass(frozen=True)
class HistoricalStrategyReadinessAudit:
    """Shared, diagnostic-only readiness evidence for historical strategies."""

    trading_date: date
    global_replay_ready: bool
    global_fidelity: str
    global_reason: str
    coverage_basis: str
    relevant_status: str
    relevant_reason: str
    relevant_contracts: int
    relevant_ce_contracts: int
    relevant_pe_contracts: int
    relevant_complete_contracts: int
    relevant_candle_coverage_pct: float
    relevant_oi_coverage_pct: float
    missing_relevant_contracts: int

    @property
    def effective_ready(self) -> bool:
        """Only the authoritative global replay gate can admit a date."""
        return self.global_replay_ready


class HistoricalStrategyReadinessService:
    """Build shared replay diagnostics without changing replay admission."""

    def __init__(self, option_chain_sync, replay_reader) -> None:
        self.option_chain_sync = option_chain_sync
        self.replay_reader = replay_reader

    def inspect_day(
        self,
        instrument_key: str,
        trading_date: date,
    ) -> HistoricalStrategyReadinessAudit:
        coverage = self.option_chain_sync.validate_day(
            instrument_key,
            trading_date,
        )
        underlying = self.replay_reader.read_day(
            instrument_key,
            trading_date,
            interval_minutes=1,
        )
        relevant = analyze_historical_dri_relevant_coverage(
            coverage,
            underlying,
        )
        return self._build(trading_date, coverage, relevant)

    @staticmethod
    def _build(
        trading_date: date,
        coverage,
        relevant: HistoricalDRIRelevantCoverageAudit,
    ) -> HistoricalStrategyReadinessAudit:
        global_ready = bool(getattr(coverage, "replay_ready", False))
        return HistoricalStrategyReadinessAudit(
            trading_date=trading_date,
            global_replay_ready=global_ready,
            global_fidelity=str(
                getattr(coverage, "fidelity", "UNKNOWN")
            ),
            global_reason=str(
                getattr(coverage, "reason", "")
                or (
                    "AUTHORITATIVE_GLOBAL_GATE_PASS"
                    if global_ready
                    else "AUTHORITATIVE_GLOBAL_GATE_BLOCKED"
                )
            ),
            coverage_basis="FULL_CHAIN" if global_ready else "BLOCKED",
            relevant_status=relevant.status,
            relevant_reason=relevant.reason,
            relevant_contracts=relevant.relevant_contracts,
            relevant_ce_contracts=relevant.relevant_ce_contracts,
            relevant_pe_contracts=relevant.relevant_pe_contracts,
            relevant_complete_contracts=(
                relevant.relevant_complete_contracts
            ),
            relevant_candle_coverage_pct=(
                relevant.relevant_candle_coverage_pct
            ),
            relevant_oi_coverage_pct=(
                relevant.relevant_oi_coverage_pct
            ),
            missing_relevant_contracts=(
                relevant.missing_relevant_contracts
            ),
        )
