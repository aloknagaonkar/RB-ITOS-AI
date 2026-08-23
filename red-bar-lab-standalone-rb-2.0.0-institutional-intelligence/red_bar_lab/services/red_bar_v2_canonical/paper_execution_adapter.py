from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Protocol

from red_bar_lab.execution.paper_engine import PaperContract, RedBarPaperExecutionEngine

from .paper_execution_models import (
    CanonicalPaperContract,
    CanonicalPaperExecutionCommand,
)


@dataclass(frozen=True, slots=True)
class PaperAdapterResult:
    accepted: bool
    uncertain: bool
    reason_code: str
    paper_order_id: str | None


class CanonicalPaperAdapter(Protocol):
    def lookup(self, *, execution_id: str) -> PaperAdapterResult | None: ...
    def submit(self, *, command: CanonicalPaperExecutionCommand) -> PaperAdapterResult: ...


class CanonicalContractSelector(Protocol):
    def select(
        self,
        *,
        option_side: str,
        spot_price: float,
        selected_at: datetime,
    ) -> CanonicalPaperContract | None: ...


class ExistingPaperContractSelector:
    """Narrow adapter over the existing NIFTY option selection/quote path."""

    def __init__(
        self,
        *,
        engine: RedBarPaperExecutionEngine,
        zerodha,
        underlying_name: str = "NIFTY 50",
        maximum_spread_pct: float = 10.0,
    ) -> None:
        self.engine = engine
        self.zerodha = zerodha
        self.underlying_name = underlying_name
        self.maximum_spread_pct = float(maximum_spread_pct)

    def select(
        self,
        *,
        option_side: str,
        spot_price: float,
        selected_at: datetime,
    ) -> CanonicalPaperContract | None:
        direction = "BULLISH" if option_side == "CE" else "BEARISH"
        contracts = self.engine.candidate_contracts(
            zerodha=self.zerodha,
            underlying_name=self.underlying_name,
            direction=direction,
            spot_price=spot_price,
            strike_count_each_side=2,
        )
        quotes = {
            str(row.get("symbol")): row
            for row in self.engine.contract_quotes(
                zerodha=self.zerodha,
                contracts=contracts,
            )
        }
        for contract in contracts:
            if contract.option_type != option_side or contract.expiry < selected_at.date():
                continue
            quote = quotes.get(contract.tradingsymbol) or {}
            try:
                ltp = float(quote.get("ltp") or 0.0)
                bid = float(quote["best_bid"]) if quote.get("best_bid") else None
                ask = float(quote["best_ask"]) if quote.get("best_ask") else None
            except (TypeError, ValueError):
                continue
            if ltp <= 0 or contract.lot_size <= 0:
                continue
            if bid and ask:
                spread_pct = ((ask - bid) / max((ask + bid) / 2.0, 0.01)) * 100.0
                if spread_pct < 0 or spread_pct > self.maximum_spread_pct:
                    continue
            from red_bar_lab.domain.red_bar_v2 import OptionSide

            return CanonicalPaperContract(
                instrument_token=contract.instrument_token,
                instrument_key=f"{contract.exchange}|{contract.instrument_token}",
                tradingsymbol=contract.tradingsymbol,
                exchange=contract.exchange,
                option_side=OptionSide(option_side),
                strike=contract.strike,
                expiry=contract.expiry,
                lot_size=contract.lot_size,
                selected_at=selected_at,
                quote_timestamp=selected_at,
                last_price=ltp,
                best_bid=bid,
                best_ask=ask,
            )
        return None


class ExistingRedBarPaperAdapter:
    """Idempotent correlation wrapper; never invokes a live broker order API."""

    def __init__(
        self,
        *,
        engine: RedBarPaperExecutionEngine,
        zerodha,
        database_path: Path,
        underlying_name: str = "NIFTY 50",
    ) -> None:
        self.engine = engine
        self.zerodha = zerodha
        self.database_path = Path(database_path)
        self.underlying_name = underlying_name

    def lookup(self, *, execution_id: str) -> PaperAdapterResult | None:
        try:
            with sqlite3.connect(self.database_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT order_id,status FROM paper_execution_orders "
                    "WHERE signal_id=? AND account_id=? ORDER BY entry_timestamp LIMIT 1",
                    (execution_id, self.engine.account_id),
                ).fetchone()
        except sqlite3.Error:
            return PaperAdapterResult(False, True, "PAPER_LOOKUP_UNAVAILABLE", None)
        if row is None:
            return None
        status = str(row["status"] or "").upper()
        return PaperAdapterResult(
            accepted=status in {"OPEN", "CLOSED"},
            uncertain=False,
            reason_code=f"EXISTING_PAPER_{status or 'UNKNOWN'}",
            paper_order_id=str(row["order_id"]),
        )

    def submit(self, *, command: CanonicalPaperExecutionCommand) -> PaperAdapterResult:
        existing = self.lookup(execution_id=command.execution_id)
        if existing is not None:
            return existing
        contract = PaperContract(
            instrument_token=command.contract.instrument_token,
            tradingsymbol=command.contract.tradingsymbol,
            exchange=command.contract.exchange,
            option_type=command.contract.option_side.value,
            strike=command.contract.strike,
            expiry=command.contract.expiry,
            lot_size=command.contract.lot_size,
        )
        try:
            row = self.engine.open_long_option(
                zerodha=self.zerodha,
                contract=contract,
                quantity=command.quantity,
                signal_id=command.execution_id,
                underlying_name=self.underlying_name,
                underlying_price=None,
                reason="CANONICAL_RED_BAR_V2_PAPER_CANARY",
                policy_metadata={
                    "execution_strategy_source": "CANONICAL_RED_BAR_V2",
                    "signal_sources": [command.signal_id],
                },
            )
        except sqlite3.IntegrityError:
            replay = self.lookup(execution_id=command.execution_id)
            return replay or PaperAdapterResult(False, True, "DUPLICATE_RECONCILIATION_REQUIRED", None)
        except (ValueError, TypeError) as exc:
            return PaperAdapterResult(False, False, type(exc).__name__.upper(), None)
        except (sqlite3.Error, OSError):
            return PaperAdapterResult(False, True, "PAPER_SUBMISSION_UNCERTAIN", None)
        return PaperAdapterResult(
            accepted=True,
            uncertain=False,
            reason_code="PAPER_ACCEPTED",
            paper_order_id=str(row.get("order_id")),
        )
