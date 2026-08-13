from __future__ import annotations

from functools import wraps
from typing import Callable

import streamlit as st

from red_bar_lab.execution.trend_automation import (
    EMA10TrendSnapshot,
    TrendAwarePaperAutomationService,
)


ACTIVE_QUEUE_STATUSES = {
    "QUALIFIED",
    "APPROVED",
    "PENDING",
    "EXECUTING",
    "ACTIVE",
}


def load_completed_ema10_snapshot(paper_market) -> EMA10TrendSnapshot:
    """Use the exact live automation EMA10 loader for the UI preview.

    The UI must never maintain a second interpretation of completed 5-minute
    candles. Constructing the service without running its initializer is safe
    here because ``_load_ema10_snapshot`` only requires the market adapter on
    ``self.zerodha``.
    """
    if paper_market is None:
        return EMA10TrendSnapshot(
            False,
            None,
            None,
            None,
            "UNDERLYING_CANDLE_PROVIDER_UNAVAILABLE",
        )

    try:
        loader = object.__new__(TrendAwarePaperAutomationService)
        loader.zerodha = paper_market
        return TrendAwarePaperAutomationService._load_ema10_snapshot(loader)
    except Exception as exc:
        return EMA10TrendSnapshot(
            False,
            None,
            None,
            None,
            f"EMA10_UI_LOAD_FAILED:{type(exc).__name__}",
        )


class CandidateDetailDatabaseProxy:
    """Give Candidate Detail the same contract-scoped duplicate semantics.

    The legacy evidence panel asks a signal-level method whether a duplicate
    exists. This proxy narrows that one UI call to the candidate currently being
    inspected. Actual execution continues to use TrendAwareDatabaseProxy.
    """

    def __init__(
        self,
        database,
        ranked_contracts,
        *,
        selected_symbol_provider: Callable[[], str] | None = None,
    ) -> None:
        self._database = database
        self._selected_symbol_provider = (
            selected_symbol_provider
            or (
                lambda: str(
                    st.session_state.get(
                        "paper_inspected_candidate_symbol",
                        "",
                    )
                )
            )
        )
        self._token_by_symbol = {
            str(row.get("tradingsymbol") or ""): int(
                row.get("instrument_token") or 0
            )
            for row in (ranked_contracts or [])
            if str(row.get("tradingsymbol") or "")
        }

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    @staticmethod
    def _same_contract(
        row: dict[str, object],
        *,
        selected_symbol: str,
        selected_token: int,
    ) -> bool:
        row_token = int(row.get("instrument_token") or 0)
        if selected_token > 0 and row_token > 0:
            return row_token == selected_token
        row_symbol = str(
            row.get("tradingsymbol")
            or row.get("candidate_symbol")
            or ""
        )
        return bool(selected_symbol and row_symbol == selected_symbol)

    def paper_execution_exists_for_signal(
        self,
        *,
        signal_id: str,
        account_id: str,
    ) -> bool:
        """OPEN or other-signal pending same contract blocks the UI candidate."""
        selected_symbol = str(self._selected_symbol_provider() or "")
        if not selected_symbol:
            return self._database.paper_execution_exists_for_signal(
                signal_id=signal_id,
                account_id=account_id,
            )
        selected_token = int(self._token_by_symbol.get(selected_symbol, 0))

        open_rows = self._database.read_open_paper_execution_orders(account_id)
        if any(
            self._same_contract(
                row,
                selected_symbol=selected_symbol,
                selected_token=selected_token,
            )
            for row in (open_rows or [])
        ):
            return True

        try:
            queue_rows = self._database.read_execution_queue(limit=5000)
        except TypeError:
            queue_rows = self._database.read_execution_queue()

        for row in queue_rows or []:
            if not self._same_contract(
                row,
                selected_symbol=selected_symbol,
                selected_token=selected_token,
            ):
                continue
            # The current signal's own queue row is the evaluation being shown,
            # not a competing duplicate. An active order is already caught above.
            if str(row.get("signal_id") or "") == str(signal_id):
                continue
            if str(row.get("status") or "").upper() in ACTIVE_QUEUE_STATUSES:
                return True
        return False


class ExitSignalDatabaseProxy:
    """Enrich the selected trade's signal with completed NIFTY 5m EMA10."""

    def __init__(self, database, snapshot: EMA10TrendSnapshot) -> None:
        self._database = database
        self._snapshot = snapshot

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    def read_signal_attempt_by_id(self, *args, **kwargs):
        row = self._database.read_signal_attempt_by_id(*args, **kwargs)
        if not row:
            return row
        enriched = dict(row)
        enriched.update(
            {
                "_ema10_5m_ready": self._snapshot.ready,
                "_ema10_5m_close": self._snapshot.close,
                "_ema10_5m_value": self._snapshot.ema10,
                "_ema10_5m_timestamp": self._snapshot.timestamp,
                "_ema10_5m_reason": self._snapshot.reason,
            }
        )
        return enriched


def build_candidate_workbench_wrapper(original):
    """Wrap only Candidate Detail database reads; execution state is untouched."""

    @wraps(original)
    def wrapper(
        ranked_rows,
        ranked_contracts,
        paper_engine,
        paper_market,
        today_text,
        paper_data_ready,
        ranked_at,
        database,
        intelligence_snapshot,
        latest_signal,
        latest_direction,
        market_open,
        auto_min_score,
        open_orders,
    ):
        evidence_database = CandidateDetailDatabaseProxy(
            database,
            ranked_contracts,
        )
        return original(
            ranked_rows,
            ranked_contracts,
            paper_engine,
            paper_market,
            today_text,
            paper_data_ready,
            ranked_at,
            evidence_database,
            intelligence_snapshot,
            latest_signal,
            latest_direction,
            market_open,
            auto_min_score,
            open_orders,
        )

    return wrapper


def build_paper_exit_panel_wrapper(
    original,
    *,
    snapshot_loader=load_completed_ema10_snapshot,
):
    """Feed the Paper Exit preview the live monitor's completed EMA10 context."""

    @wraps(original)
    def wrapper(
        *,
        position,
        paper_engine,
        paper_market,
        database,
        intelligence_snapshot,
        instrument_key,
        today_text,
    ):
        snapshot = snapshot_loader(paper_market)
        evidence_database = ExitSignalDatabaseProxy(database, snapshot)
        return original(
            position=position,
            paper_engine=paper_engine,
            paper_market=paper_market,
            database=evidence_database,
            intelligence_snapshot=intelligence_snapshot,
            instrument_key=instrument_key,
            today_text=today_text,
        )

    return wrapper
