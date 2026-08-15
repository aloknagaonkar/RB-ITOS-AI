from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from red_bar_lab.services.historical_dri_relevant_coverage_compat import (
    analyze_historical_dri_relevant_coverage,
)


@dataclass(frozen=True)
class ResearchQualifiedCoverage:
    base: object
    contracts: tuple[object, ...]
    replay_ready: bool
    fidelity: str
    reason: str
    qualification: str
    data_source: str

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def as_dict(self) -> dict[str, object]:
        payload = (
            dict(self.base.as_dict())
            if hasattr(self.base, "as_dict")
            else dict(getattr(self.base, "__dict__", {}))
        )
        payload.update(
            {
                "replay_ready": self.replay_ready,
                "fidelity": self.fidelity,
                "reason": self.reason,
                "qualification": self.qualification,
                "data_source": self.data_source,
                "contracts": [
                    dict(getattr(item, "__dict__", {})) for item in self.contracts
                ],
            }
        )
        return payload


class HistoricalDRIResearchReadinessService:
    """Research-only readiness adapter for historical DRI replay.

    The existing global readiness gate remains authoritative. When it fails, a date
    may qualify only when every contract in the DRI-relevant strike window passes
    the separately audited candle and OI thresholds. This adapter is intended only
    for historical Research Lab replay and must never be injected into live or paper
    execution paths.
    """

    def __init__(self, option_sync: object, historical: object) -> None:
        self.option_sync = option_sync
        self.historical = historical

    def __getattr__(self, name: str) -> Any:
        return getattr(self.option_sync, name)

    def validate_day(self, instrument_key, trading_date):
        global_coverage = self.option_sync.validate_day(
            instrument_key, trading_date
        )
        if bool(getattr(global_coverage, "replay_ready", False)):
            return ResearchQualifiedCoverage(
                base=global_coverage,
                contracts=tuple(getattr(global_coverage, "contracts", ()) or ()),
                replay_ready=True,
                fidelity=str(getattr(global_coverage, "fidelity", "UNKNOWN")),
                reason=str(getattr(global_coverage, "reason", "")),
                qualification="GLOBAL_REPLAY_READY",
                data_source=str(
                    getattr(global_coverage, "data_source", "UNKNOWN") or "UNKNOWN"
                ),
            )

        expired_detail = self.option_sync._validate_expired_day(
            instrument_key, trading_date
        )
        underlying = self.historical.read_day(
            instrument_key, trading_date, interval_minutes=1
        )
        audit = analyze_historical_dri_relevant_coverage(
            expired_detail, underlying
        )
        if audit.status != "STRATEGY_RELEVANT_COVERAGE_HIGH":
            return global_coverage

        return ResearchQualifiedCoverage(
            base=global_coverage,
            contracts=tuple(getattr(expired_detail, "contracts", ()) or ()),
            replay_ready=True,
            fidelity="STRATEGY_RELEVANT_OPTION_REPLAY",
            reason=(
                "Research-only qualification: all DRI-relevant CE/PE contracts "
                "meet candle and OI thresholds although the broad option universe "
                "does not pass the global replay gate."
            ),
            qualification="STRATEGY_RELEVANT_COVERAGE_HIGH",
            data_source="EXPIRED_OPTION_CANDLES_RELEVANT_WINDOW",
        )
