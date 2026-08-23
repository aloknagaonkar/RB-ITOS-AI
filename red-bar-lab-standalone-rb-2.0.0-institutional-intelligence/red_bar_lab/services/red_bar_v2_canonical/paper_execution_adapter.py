from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.execution.paper_engine import PaperContract, RedBarPaperExecutionEngine

from .paper_execution_models import (
    CanonicalPaperContract,
    CanonicalPaperExecutionCommand,
)
from .paper_market_data import PaperCanaryMarketData


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


def _canonical_token(value: int | str, instrument_key: str) -> int | None:
    if type(value) is int and value > 0:
        return value
    if type(value) is str and value.isdigit() and int(value) > 0:
        return int(value)
    suffix = instrument_key.rsplit("|", 1)[-1]
    return int(suffix) if suffix.isdigit() and int(suffix) > 0 else None


class ExistingPaperContractSelector:
    """Existing nearest-expiry/strike/spread policy over normalized read-only data."""

    def __init__(
        self,
        *,
        engine: RedBarPaperExecutionEngine,
        market_data: PaperCanaryMarketData,
        underlying_name: str = "NIFTY 50",
        maximum_spread_pct: float = 10.0,
    ) -> None:
        self.engine = engine
        self.market_data = market_data
        self.underlying_name = underlying_name
        self.maximum_spread_pct = float(maximum_spread_pct)

    def select(
        self,
        *,
        option_side: str,
        spot_price: float,
        selected_at: datetime,
    ) -> CanonicalPaperContract | None:
        side = OptionSide(option_side)
        instruments = tuple(
            item
            for item in self.market_data.option_instruments(
                underlying=self.underlying_name,
                evaluated_at=selected_at,
            )
            if item.option_side is side and item.expiry >= selected_at.date()
        )
        if not instruments:
            return None
        nearest_expiry = min(item.expiry for item in instruments)
        ranked = sorted(
            (item for item in instruments if item.expiry == nearest_expiry),
            key=lambda item: (abs(float(item.strike) - float(spot_price)), item.strike),
        )[:5]
        quotes = {
            quote.instrument_key: quote
            for quote in self.market_data.quotes(
                instrument_keys=tuple(item.instrument_key for item in ranked),
                evaluated_at=selected_at,
            )
        }
        for instrument in ranked:
            quote = quotes.get(instrument.instrument_key)
            token = _canonical_token(
                instrument.instrument_token,
                instrument.instrument_key,
            )
            if quote is None or token is None:
                continue
            bid = quote.bid_price
            ask = quote.ask_price
            if bid is not None and ask is not None:
                spread_pct = (
                    (float(ask) - float(bid))
                    / max((float(ask) + float(bid)) / 2.0, 0.01)
                ) * 100.0
                if spread_pct < 0 or spread_pct > self.maximum_spread_pct:
                    continue
            exchange = instrument.instrument_key.split("|", 1)[0]
            return CanonicalPaperContract(
                instrument_token=token,
                instrument_key=instrument.instrument_key,
                tradingsymbol=instrument.trading_symbol,
                exchange=exchange,
                option_side=instrument.option_side,
                strike=instrument.strike,
                expiry=instrument.expiry,
                lot_size=instrument.lot_size,
                selected_at=selected_at,
                quote_timestamp=quote.quote_timestamp,
                last_price=quote.last_price,
                best_bid=bid,
                best_ask=ask,
            )
        return None


class _EngineQuoteFacade:
    """Expose only the engine's legacy read-only quote shape for one command."""

    def __init__(
        self,
        *,
        market_data: PaperCanaryMarketData,
        instrument_key: str,
        evaluated_at: datetime,
    ) -> None:
        self.market_data = market_data
        self.instrument_key = instrument_key
        self.evaluated_at = evaluated_at
        self.provider_name = market_data.provider_name

    def quote(self, keys: list[str]) -> dict[str, object]:
        quotes = self.market_data.quotes(
            instrument_keys=(self.instrument_key,),
            evaluated_at=self.evaluated_at,
        )
        if not quotes:
            return {}
        quote = quotes[0]
        depth = {
            "buy": ([{"price": quote.bid_price}] if quote.bid_price is not None else []),
            "sell": ([{"price": quote.ask_price}] if quote.ask_price is not None else []),
        }
        return {
            key: {
                "last_price": quote.last_price,
                "depth": depth,
                "timestamp": quote.quote_timestamp.isoformat(),
            }
            for key in keys
        }


class ExistingRedBarPaperAdapter:
    """Idempotent virtual-paper wrapper; no live broker method is reachable."""

    def __init__(
        self,
        *,
        engine: RedBarPaperExecutionEngine,
        market_data: PaperCanaryMarketData,
        database_path: Path,
        underlying_name: str = "NIFTY 50",
    ) -> None:
        self.engine = engine
        self.market_data = market_data
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
        quote_facade = _EngineQuoteFacade(
            market_data=self.market_data,
            instrument_key=command.contract.instrument_key,
            evaluated_at=command.created_at,
        )
        try:
            row = self.engine.open_long_option(
                zerodha=quote_facade,
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
