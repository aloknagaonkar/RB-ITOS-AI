from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.live_signal_admission import (
    AdmissionMode,
    LiveSignalAdmissionDecision,
    evaluate_live_signal_admission,
)


IST = ZoneInfo("Asia/Kolkata")


class _AdmissionDatabaseProxy:
    """Delegate database access while filtering terminally blocked live signals."""

    def __init__(
        self,
        database,
        *,
        now: datetime,
        max_signal_age_seconds: int,
        allow_outside_market_hours: bool,
        allow_stale_signals: bool,
        enable_opportunity_extension: bool,
    ) -> None:
        self._database = database
        self._now = now
        self._max_signal_age_seconds = int(max_signal_age_seconds)
        self._allow_outside_market_hours = bool(allow_outside_market_hours)
        self._allow_stale_signals = bool(allow_stale_signals)
        self._enable_opportunity_extension = bool(enable_opportunity_extension)
        self.decisions: dict[str, LiveSignalAdmissionDecision] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._database, name)

    def read_signal_attempts(self, instrument_key: str, trading_date: str):
        rows = self._database.read_signal_attempts(instrument_key, trading_date)
        allowed = []
        for row in rows:
            signal_id = str(row.get("signal_id") or "")
            decision = evaluate_live_signal_admission(
                confirmation_timestamp=row.get("confirmation_timestamp"),
                now=self._now,
                mode=AdmissionMode.LIVE,
                max_signal_age_seconds=self._max_signal_age_seconds,
                allow_outside_market_hours=self._allow_outside_market_hours,
                allow_stale_signals=self._allow_stale_signals,
                enable_opportunity_extension=self._enable_opportunity_extension,
            )
            if signal_id:
                self.decisions[signal_id] = decision
            if decision.allowed:
                allowed.append(row)
                continue
            self._persist_terminal_block(row, decision)
        return allowed

    def _persist_terminal_block(
        self,
        signal: dict[str, Any],
        decision: LiveSignalAdmissionDecision,
    ) -> None:
        signal_id = str(signal.get("signal_id") or "")
        insert_diagnostic = getattr(
            self._database,
            "insert_paper_signal_diagnostic",
            None,
        )
        if callable(insert_diagnostic):
            insert_diagnostic(
                {
                    "scan_id": "LIVE-ADMISSION",
                    "signal_id": signal_id or None,
                    "signal_state": signal.get("state"),
                    "direction": signal.get("direction"),
                    "confirmation_timestamp": signal.get(
                        "confirmation_timestamp"
                    ),
                    "signal_age_seconds": decision.signal_age_seconds,
                    "market_hours_ok": decision.market_hours_ok,
                    "freshness_ok": decision.freshness_ok,
                    "duplicate_free": True,
                    "candidate_available": False,
                    "best_candidate": None,
                    "best_score": None,
                    "minimum_score": None,
                    "score_ok": False,
                    "final_decision": decision.decision,
                    "reason": decision.reason,
                    "timestamp": self._now.isoformat(),
                }
            )

        insert_state = getattr(
            self._database,
            "insert_execution_state_event",
            None,
        )
        if callable(insert_state) and signal_id:
            insert_state(
                {
                    "event_id": f"LIVE-ADMISSION-{signal_id}",
                    "signal_id": signal_id,
                    "order_id": None,
                    "state": "LIVE_ADMISSION_BLOCKED",
                    "detail": (
                        f"decision={decision.decision}; "
                        f"reason={decision.reason}; "
                        "historical_override=PROHIBITED"
                    ),
                    "candidate_score": None,
                    "timestamp": self._now.isoformat(),
                }
            )


class LiveAdmissionRedBarPaperAutomationService(
    RedBarPaperAutomationService
):
    """Additive live guard around the stable paper automation service.

    Terminal current-session blocks are applied before candidate scoring,
    historical evidence, committee evaluation, queue creation, or order opening.
    Allowed signals continue through the unchanged legacy-compatible engine.
    """

    def process_new_signals(
        self,
        *,
        trading_date: str,
        lots: int = 1,
        queue_only: bool = False,
    ):
        original_database = self.database
        proxy = _AdmissionDatabaseProxy(
            original_database,
            now=datetime.now(IST),
            max_signal_age_seconds=self.max_signal_age_seconds,
            allow_outside_market_hours=self.allow_outside_market_hours,
            allow_stale_signals=self.allow_stale_signals,
            enable_opportunity_extension=self.enable_opportunity_extension,
        )
        self.database = proxy
        self.engine.database = proxy
        try:
            return super().process_new_signals(
                trading_date=trading_date,
                lots=lots,
                queue_only=queue_only,
            )
        finally:
            self.database = original_database
            self.engine.database = original_database


__all__ = ["LiveAdmissionRedBarPaperAutomationService"]
