from __future__ import annotations

from red_bar_lab.intelligence.historical_evidence import HistoricalEvidenceService
from red_bar_lab.services.historical_decision_replay import HistoricalDecisionReplayService


class EvidenceAwareHistoricalDecisionReplayService(HistoricalDecisionReplayService):
    """Historical replay plus additive Sprint-4 evidence persistence.

    The parent replay freezes and evaluates the historical decision first. Only
    after that result exists do we write a canonical research record. Evidence
    persistence therefore has no path back into entry, committee, portfolio, or
    exit authority.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        option_chain_sync = kwargs.get("option_chain_sync")
        self.evidence_database = getattr(option_chain_sync, "database", None)
        self.last_evidence_report = None

    def run_day(self, instrument_key, trading_date):
        result = super().run_day(instrument_key, trading_date)
        if self.evidence_database is not None:
            self.last_evidence_report = HistoricalEvidenceService(
                self.evidence_database
            ).ingest_replay_result(
                instrument_key=instrument_key,
                result=result,
            )
        return result
