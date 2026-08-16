from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class PaperContract:
    instrument_token: int
    tradingsymbol: str
    exchange: str
    option_type: str
    strike: float
    expiry: date
    lot_size: int


@dataclass(frozen=True)
class PaperPortfolioSummary:
    initial_capital: float
    realized_pnl: float
    unrealized_pnl: float
    net_pnl: float
    deployed_capital: float
    available_capital: float
    open_positions: int
    closed_positions: int


def _now_ist() -> datetime:
    return datetime.now(IST)


def _quote_key(contract: PaperContract) -> str:
    return f"{contract.exchange}:{contract.tradingsymbol}"


def _best_price(
    quote: dict[str, object],
    *,
    side: str,
    fallback_bps: float,
) -> float:
    ltp = float(quote.get("last_price") or 0.0)
    depth = quote.get("depth") or {}
    book_side = "sell" if side == "BUY" else "buy"
    levels = depth.get(book_side) or []
    if levels:
        try:
            price = float(levels[0].get("price") or 0.0)
            if price > 0:
                return price
        except (TypeError, ValueError, AttributeError):
            pass
    if ltp <= 0:
        raise ValueError("No usable LTP/depth price for paper fill.")
    adjustment = fallback_bps / 10000.0
    return (
        ltp * (1.0 + adjustment)
        if side == "BUY"
        else ltp * (1.0 - adjustment)
    )


class RedBarPaperExecutionEngine:
    """Virtual option execution using a read-only market-data provider.

    No live broker order is ever transmitted by this class.
    """

    def __init__(
        self,
        database,
        settings,
        *,
        account_id: str = "PAPER-STD",
        initial_capital: float = 100000.0,
        slippage_bps: float = 5.0,
    ):
        self.database = database
        self.settings = settings
        self.account_id = account_id
        self.initial_capital = float(initial_capital)
        self.slippage_bps = float(slippage_bps)
        self.database.ensure_paper_execution_account(
            account_id=self.account_id,
            account_name="Standard Paper Account",
            initial_capital=self.initial_capital,
        )

    def candidate_contracts(
        self,
        *,
        zerodha,
        underlying_name: str,
        direction: str,
        spot_price: float,
        expiry: date | None = None,
        strike_count_each_side: int = 2,
    ) -> list[PaperContract]:
        option_type = (
            "CE" if str(direction).upper() == "BULLISH" else "PE"
        )
        frame = zerodha.nfo_options(
            underlying_name=underlying_name,
            as_of=date.today(),
        )
        if frame.empty:
            return []

        if expiry is None:
            expiry_values = sorted(
                item for item in frame["expiry"].dropna().unique()
            )
            if not expiry_values:
                return []
            expiry = expiry_values[0]

        frame = frame[
            (frame["expiry"] == expiry)
            & (frame["instrument_type"] == option_type)
        ].copy()
        if frame.empty:
            return []

        frame["distance"] = (
            pd.to_numeric(frame["strike"], errors="coerce")
            - float(spot_price)
        ).abs()
        frame = frame.sort_values(
            ["distance", "strike"]
        ).head(1 + 2 * int(strike_count_each_side))

        contracts = []
        for _, row in frame.iterrows():
            try:
                contracts.append(
                    PaperContract(
                        instrument_token=int(row["instrument_token"]),
                        tradingsymbol=str(row["tradingsymbol"]),
                        exchange=str(row.get("exchange") or "NFO"),
                        option_type=str(row["instrument_type"]),
                        strike=float(row["strike"]),
                        expiry=row["expiry"],
                        lot_size=int(row.get("lot_size") or 1),
                    )
                )
            except (TypeError, ValueError, KeyError):
                continue
        return sorted(
            contracts,
            key=lambda item: abs(item.strike - float(spot_price)),
        )

    def contract_quotes(
        self,
        *,
        zerodha,
        contracts: list[PaperContract],
    ) -> list[dict[str, object]]:
        if not contracts:
            return []
        keys = [_quote_key(contract) for contract in contracts]
        quotes = zerodha.quote(keys)
        rows = []
        for contract in contracts:
            key = _quote_key(contract)
            q = quotes.get(key) or {}
            depth = q.get("depth") or {}
            buy = depth.get("buy") or []
            sell = depth.get("sell") or []
            rows.append(
                {
                    "symbol": contract.tradingsymbol,
                    "token": contract.instrument_token,
                    "type": contract.option_type,
                    "strike": contract.strike,
                    "expiry": str(contract.expiry),
                    "lot_size": contract.lot_size,
                    "ltp": q.get("last_price"),
                    "volume": q.get("volume"),
                    "oi": q.get("oi"),
                    "buy_quantity": q.get("buy_quantity"),
                    "sell_quantity": q.get("sell_quantity"),
                    "best_bid": (
                        buy[0].get("price") if buy else None
                    ),
                    "best_ask": (
                        sell[0].get("price") if sell else None
                    ),
                    "iv": q.get("iv"),
                    "delta": q.get("delta"),
                    "gamma": q.get("gamma"),
                    "theta": q.get("theta"),
                    "vega": q.get("vega"),
                }
            )
        return rows

    def open_long_option(
        self,
        *,
        zerodha,
        contract: PaperContract,
        quantity: int,
        signal_id: str | None,
        underlying_name: str,
        underlying_price: float | None,
        stop_price: float | None = None,
        target1_price: float | None = None,
        target2_price: float | None = None,
        reason: str = "MANUAL_PAPER_ENTRY",
        policy_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if quantity <= 0:
            raise ValueError("Paper quantity must be positive.")
        if quantity % contract.lot_size != 0:
            raise ValueError(
                f"Quantity must be a multiple of lot size "
                f"{contract.lot_size}."
            )

        key = _quote_key(contract)
        quote = zerodha.quote([key]).get(key)
        if not quote:
            raise ValueError(
                f"No Zerodha quote available for {key}."
            )

        entry_price = _best_price(
            quote,
            side="BUY",
            fallback_bps=self.slippage_bps,
        )
        required = entry_price * int(quantity)
        summary = self.portfolio_summary()
        if required > summary.available_capital:
            raise ValueError(
                f"Insufficient paper capital. Required ₹{required:.2f}, "
                f"available ₹{summary.available_capital:.2f}."
            )

        now = _now_ist()
        order_id = f"PAPER-{uuid4().hex[:12].upper()}"
        policy_metadata = dict(policy_metadata or {})
        row = {
            "order_id": order_id,
            "account_id": self.account_id,
            "signal_id": signal_id,
            "market_data_provider": getattr(zerodha, "provider_name", "MARKET_DATA"),
            "execution_provider": "RED_BAR_PAPER",
            "execution_mode": "PAPER",
            "underlying_name": underlying_name,
            "underlying_price_entry": underlying_price,
            "instrument_token": contract.instrument_token,
            "exchange": contract.exchange,
            "tradingsymbol": contract.tradingsymbol,
            "option_type": contract.option_type,
            "strike": contract.strike,
            "expiry": str(contract.expiry),
            "lot_size": contract.lot_size,
            "side": "BUY",
            "quantity": int(quantity),
            "entry_timestamp": now.isoformat(),
            "entry_price": entry_price,
            "current_price": entry_price,
            "stop_price": stop_price,
            "target1_price": target1_price,
            "target2_price": target2_price,
            "status": "OPEN",
            "entry_reason": reason,
            "mfe_points": 0.0,
            "mae_points": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": None,
            "execution_strategy_source": policy_metadata.get("execution_strategy_source"),
            "strategy_stop_loss_pct": policy_metadata.get("strategy_stop_loss_pct"),
            "strategy_target_pct": policy_metadata.get("strategy_target_pct"),
            "exit_mode": policy_metadata.get("exit_mode"),
            "evaluation_horizon_minutes": policy_metadata.get("evaluation_horizon_minutes"),
            "signal_sources": policy_metadata.get("signal_sources") or [],
            "merge_status": policy_metadata.get("merge_status"),
            "rsi_signal_id": policy_metadata.get("rsi_signal_id"),
            "rsi_confirmation_timestamp": policy_metadata.get("rsi_confirmation_timestamp"),
        }
        self.database.insert_paper_execution_order(row)
        self.database.insert_paper_execution_mark(
            {
                "order_id": order_id,
                "timestamp": now.isoformat(),
                "price": entry_price,
                "underlying_price": underlying_price,
                "unrealized_pnl": 0.0,
                "mfe_points": 0.0,
                "mae_points": 0.0,
                "event_type": "ENTRY",
            }
        )
        return self.database.read_paper_execution_order(order_id)

    def refresh_open_positions(
        self,
        *,
        zerodha,
        underlying_prices: dict[str, float] | None = None,
    ) -> list[dict[str, object]]:
        open_rows = self.database.read_open_paper_execution_orders(
            self.account_id
        )
        if not open_rows:
            return []

        keys = [
            f"{row['exchange']}:{row['tradingsymbol']}"
            for row in open_rows
        ]
        quotes = zerodha.quote(keys)
        updated = []

        for row in open_rows:
            key = f"{row['exchange']}:{row['tradingsymbol']}"
            quote = quotes.get(key) or {}
            ltp = quote.get("last_price")
            if ltp is None:
                continue
            price = float(ltp)
            entry = float(row["entry_price"])
            quantity = int(row["quantity"])
            points = price - entry
            pnl = points * quantity
            mfe = max(
                float(row.get("mfe_points") or 0.0),
                points,
            )
            mae = min(
                float(row.get("mae_points") or 0.0),
                points,
            )
            now = _now_ist()
            underlying_price = None
            if underlying_prices:
                underlying_price = underlying_prices.get(
                    str(row.get("underlying_name") or "")
                )

            self.database.update_paper_execution_mark_to_order(
                order_id=str(row["order_id"]),
                current_price=price,
                unrealized_pnl=pnl,
                mfe_points=mfe,
                mae_points=mae,
                updated_at=now.isoformat(),
            )
            self.database.insert_paper_execution_mark(
                {
                    "order_id": row["order_id"],
                    "timestamp": now.isoformat(),
                    "price": price,
                    "underlying_price": underlying_price,
                    "unrealized_pnl": pnl,
                    "mfe_points": mfe,
                    "mae_points": mae,
                    "event_type": "MARK",
                }
            )

            refreshed = self.database.read_paper_execution_order(
                str(row["order_id"])
            )
            updated.append(refreshed)

        return updated

    def close_position(
        self,
        *,
        zerodha,
        order_id: str,
        exit_reason: str = "MANUAL_PAPER_EXIT",
    ) -> dict[str, object]:
        row = self.database.read_paper_execution_order(order_id)
        if not row:
            raise ValueError(f"Unknown paper order {order_id}.")
        if row.get("status") != "OPEN":
            return row

        key = f"{row['exchange']}:{row['tradingsymbol']}"
        quote = zerodha.quote([key]).get(key)
        if not quote:
            raise ValueError(
                f"No Zerodha quote available for {key}."
            )
        exit_price = _best_price(
            quote,
            side="SELL",
            fallback_bps=self.slippage_bps,
        )
        entry_price = float(row["entry_price"])
        quantity = int(row["quantity"])
        points = exit_price - entry_price
        pnl = points * quantity
        mfe = max(
            float(row.get("mfe_points") or 0.0),
            points,
        )
        mae = min(
            float(row.get("mae_points") or 0.0),
            points,
        )
        now = _now_ist()

        self.database.close_paper_execution_order(
            order_id=order_id,
            exit_timestamp=now.isoformat(),
            exit_price=exit_price,
            exit_reason=exit_reason,
            realized_pnl=pnl,
            mfe_points=mfe,
            mae_points=mae,
        )
        self.database.insert_paper_execution_mark(
            {
                "order_id": order_id,
                "timestamp": now.isoformat(),
                "price": exit_price,
                "underlying_price": None,
                "unrealized_pnl": 0.0,
                "mfe_points": mfe,
                "mae_points": mae,
                "event_type": "EXIT",
            }
        )
        return self.database.read_paper_execution_order(order_id)

    def option_candles(
        self,
        *,
        zerodha,
        instrument_token: int,
        date_from,
        date_to,
        interval: str = "minute",
    ) -> pd.DataFrame:
        frame = zerodha.historical_candles(
            instrument_token=int(instrument_token),
            interval=interval,
            date_from=date_from,
            date_to=date_to,
            include_oi=True,
        )
        if frame.empty:
            return frame

        frame = frame.copy()
        frame["close"] = pd.to_numeric(
            frame["close"], errors="coerce"
        )
        frame["volume"] = pd.to_numeric(
            frame["volume"], errors="coerce"
        )
        frame["ema9"] = frame["close"].ewm(
            span=9, adjust=False
        ).mean()
        frame["ema21"] = frame["close"].ewm(
            span=21, adjust=False
        ).mean()

        typical = (
            pd.to_numeric(frame["high"], errors="coerce")
            + pd.to_numeric(frame["low"], errors="coerce")
            + frame["close"]
        ) / 3.0
        volume = frame["volume"].fillna(0.0)
        cumulative_volume = volume.cumsum()
        frame["vwap"] = (
            (typical * volume).cumsum()
            / cumulative_volume.where(cumulative_volume != 0)
        )
        return frame

    def portfolio_summary(self) -> PaperPortfolioSummary:
        rows = self.database.read_paper_execution_orders(
            self.account_id
        )
        open_rows = [row for row in rows if row.get("status") == "OPEN"]
        closed_rows = [
            row for row in rows if row.get("status") == "CLOSED"
        ]

        realized = sum(
            float(row.get("realized_pnl") or 0.0)
            for row in closed_rows
        )
        unrealized = sum(
            float(row.get("unrealized_pnl") or 0.0)
            for row in open_rows
        )
        deployed = sum(
            float(row.get("entry_price") or 0.0)
            * int(row.get("quantity") or 0)
            for row in open_rows
        )
        available = (
            self.initial_capital
            + realized
            - deployed
        )

        return PaperPortfolioSummary(
            initial_capital=self.initial_capital,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            net_pnl=realized + unrealized,
            deployed_capital=deployed,
            available_capital=available,
            open_positions=len(open_rows),
            closed_positions=len(closed_rows),
        )
