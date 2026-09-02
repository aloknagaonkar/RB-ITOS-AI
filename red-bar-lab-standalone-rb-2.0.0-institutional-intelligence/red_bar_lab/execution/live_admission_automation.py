from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.live_signal_admission import (
    AdmissionMode,
    LiveSignalAdmissionDecision,
    evaluate_live_signal_admission,
)


IST = ZoneInfo("Asia/Kolkata")


def _persist_admission_block(
    database,
    *,
    signal: dict[str, Any],
    decision: LiveSignalAdmissionDecision,
    now: datetime,
    scan_id: str,
    state: str,
) -> None:
    """Persist one terminal live-admission decision without changing authority."""
    signal_id = str(signal.get("signal_id") or "")
    insert_diagnostic = getattr(
        database,
        "insert_paper_signal_diagnostic",
        None,
    )
    if callable(insert_diagnostic):
        insert_diagnostic(
            {
                "scan_id": scan_id,
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
                "timestamp": now.isoformat(),
            }
        )

    insert_state = getattr(
        database,
        "insert_execution_state_event",
        None,
    )
    if callable(insert_state) and signal_id:
        insert_state(
            {
                "event_id": f"EVT-{uuid4().hex[:14].upper()}",
                "signal_id": signal_id,
                "order_id": None,
                "state": state,
                "detail": (
                    f"decision={decision.decision}; "
                    f"reason={decision.reason}; "
                    "historical_override=PROHIBITED"
                ),
                "candidate_score": None,
                "timestamp": now.isoformat(),
            }
        )


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
        account_id: str | None = None,
    ) -> None:
        self._database = database
        self._now = now
        self._max_signal_age_seconds = int(max_signal_age_seconds)
        self._allow_outside_market_hours = bool(allow_outside_market_hours)
        self._allow_stale_signals = bool(allow_stale_signals)
        self._enable_opportunity_extension = bool(enable_opportunity_extension)
        self._account_id = str(account_id or "")
        self.decisions: dict[str, LiveSignalAdmissionDecision] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._database, name)

    def _executed_signal_ids(self) -> frozenset[str]:
        """Signals that already opened a paper order must not be re-blocked,
        re-expired, or re-admitted by the per-cycle freshness guard."""
        if not self._account_id:
            return frozenset()
        try:
            orders = self._database.read_paper_execution_orders(self._account_id)
        except Exception:
            return frozenset()
        return frozenset(
            str(row.get("signal_id") or "")
            for row in orders
            if row.get("signal_id")
        )

    def read_signal_attempts(self, instrument_key: str, trading_date: str):
        rows = self._database.read_signal_attempts(instrument_key, trading_date)
        executed_signal_ids = self._executed_signal_ids()
        allowed = []
        for row in rows:
            signal_id = str(row.get("signal_id") or "")
            already_executed = bool(signal_id) and signal_id in executed_signal_ids
            decision = evaluate_live_signal_admission(
                confirmation_timestamp=row.get("confirmation_timestamp"),
                now=self._now,
                mode=AdmissionMode.LIVE,
                max_signal_age_seconds=self._max_signal_age_seconds,
                allow_outside_market_hours=self._allow_outside_market_hours,
                allow_stale_signals=self._allow_stale_signals,
                enable_opportunity_extension=self._enable_opportunity_extension,
                already_executed=already_executed,
            )
            if signal_id:
                self.decisions[signal_id] = decision
            if already_executed:
                # The signal already produced its order: do not re-admit it
                # into the execution pipeline and do not keep BLOCKing/expiring
                # it with MAX_SIGNAL_AGE_EXCEEDED on every cycle.
                continue
            if decision.allowed:
                allowed.append(row)
                continue
            _persist_admission_block(
                self._database,
                signal=row,
                decision=decision,
                now=self._now,
                scan_id="LIVE-ADMISSION",
                state="LIVE_ADMISSION_BLOCKED",
            )
        return allowed


class LiveAdmissionRedBarPaperAutomationService(
    RedBarPaperAutomationService
):
    """Additive live guard around the stable paper automation service.

    Terminal current-session blocks are applied before candidate scoring,
    historical evidence, committee evaluation, queue creation, or order opening.
    Allowed signals continue through the unchanged legacy-compatible engine.
    """

    def _current_time(self) -> datetime:
        return datetime.now(IST)

    def _instrument_key(self) -> str:
        if self.underlying_name == "NIFTY 50":
            return "NSE_INDEX|Nifty 50"
        if self.underlying_name == "BANK NIFTY":
            return "NSE_INDEX|Nifty Bank"
        raise ValueError(
            f"Unsupported live-admission underlying {self.underlying_name}"
        )

    def _signal_has_order(self, signal_id: str) -> bool:
        if not signal_id:
            return False
        try:
            orders = self.database.read_paper_execution_orders(
                self.engine.account_id
            )
        except Exception:
            return False
        return any(
            str(row.get("signal_id") or "") == signal_id
            for row in orders
        )

    def _admission_decision(
        self,
        signal: dict[str, Any],
        *,
        now: datetime,
    ) -> LiveSignalAdmissionDecision:
        return evaluate_live_signal_admission(
            confirmation_timestamp=signal.get("confirmation_timestamp"),
            now=now,
            mode=AdmissionMode.LIVE,
            max_signal_age_seconds=self.max_signal_age_seconds,
            allow_outside_market_hours=self.allow_outside_market_hours,
            allow_stale_signals=self.allow_stale_signals,
            enable_opportunity_extension=self.enable_opportunity_extension,
            already_executed=self._signal_has_order(
                str(signal.get("signal_id") or "")
            ),
        )

    def _enforce_queue_admission(
        self,
        *,
        trading_date: str,
        now: datetime,
    ) -> int:
        """Expire APPROVED queue rows that fail current live admission.

        Queue rows whose source signal cannot be resolved are left unchanged for
        backward compatibility with non-Red-Bar queue producers.
        """
        read_queue = getattr(self.database, "read_execution_queue", None)
        expire_queue = getattr(
            self.database,
            "expire_execution_queue_for_signal",
            None,
        )
        if not callable(read_queue) or not callable(expire_queue):
            return 0

        approved_rows = [
            row
            for row in read_queue()
            if str(row.get("status") or "").upper() == "APPROVED"
            and row.get("signal_id")
        ]
        if not approved_rows:
            return 0

        signals = self.database.read_signal_attempts(
            self._instrument_key(),
            trading_date,
        )
        signal_by_id = {
            str(row.get("signal_id")): row
            for row in signals
            if row.get("signal_id")
        }

        blocked_signal_ids: set[str] = set()
        for queue_row in approved_rows:
            signal_id = str(queue_row.get("signal_id") or "")
            if signal_id in blocked_signal_ids:
                continue
            signal = signal_by_id.get(signal_id)
            if signal is None:
                continue
            decision = self._admission_decision(signal, now=now)
            if decision.allowed:
                continue

            reason = f"LIVE_ADMISSION:{decision.reason}"
            expire_queue(signal_id=signal_id, reason=reason)
            _persist_admission_block(
                self.database,
                signal=signal,
                decision=decision,
                now=now,
                scan_id="LIVE-ADMISSION-QUEUE",
                state="LIVE_ADMISSION_QUEUE_BLOCKED",
            )
            blocked_signal_ids.add(signal_id)

        return len(blocked_signal_ids)

    def process_new_signals(
        self,
        *,
        trading_date: str,
        lots: int = 1,
        queue_only: bool = False,
        run_id: str | None = None,
    ):
        original_database = self.database
        proxy = _AdmissionDatabaseProxy(
            original_database,
            now=self._current_time(),
            max_signal_age_seconds=self.max_signal_age_seconds,
            allow_outside_market_hours=self.allow_outside_market_hours,
            allow_stale_signals=self.allow_stale_signals,
            enable_opportunity_extension=self.enable_opportunity_extension,
            account_id=getattr(self.engine, "account_id", None),
        )
        self.database = proxy
        self.engine.database = proxy
        try:
            return super().process_new_signals(
                trading_date=trading_date,
                lots=lots,
                queue_only=queue_only,
                run_id=run_id,
            )
        finally:
            self.database = original_database
            self.engine.database = original_database

    def execute_approved_queue(
        self,
        *,
        trading_date: str,
        lots: int = 1,
        run_id: str | None = None,
    ):
        self._enforce_queue_admission(
            trading_date=trading_date,
            now=self._current_time(),
        )
        return super().execute_approved_queue(
            trading_date=trading_date,
            lots=lots,
            run_id=run_id,
        )


__all__ = ["LiveAdmissionRedBarPaperAutomationService"]
