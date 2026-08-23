from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from red_bar_lab.brokers.zerodha_client import ZerodhaAPIError, ZerodhaKiteClient
from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data import (
    PaperMarketDataAuthenticationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataUnavailableError,
    PaperMarketQuote,
    PaperOptionInstrument,
    verify_quote_freshness,
)


class ZerodhaPaperCanaryMarketData:
    provider_name = "ZERODHA"

    def __init__(self, client: ZerodhaKiteClient, *, maximum_quote_age_seconds: float) -> None:
        self._client = client
        self._maximum_quote_age_seconds = float(maximum_quote_age_seconds)
        self._symbol_to_key: dict[str, str] = {}

    @staticmethod
    def _timestamp(value: object) -> datetime:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise PaperMarketDataCorruptionError("Zerodha quote timestamp missing")
        result = parsed.to_pydatetime()
        if result.tzinfo is None or result.utcoffset() is None:
            raise PaperMarketDataCorruptionError("Zerodha quote timestamp is naive")
        return result

    def option_instruments(self, *, underlying: str, evaluated_at: datetime) -> tuple[PaperOptionInstrument, ...]:
        try:
            frame = self._client.nfo_options(underlying_name=underlying, as_of=evaluated_at.date())
        except ZerodhaAPIError as exc:
            raise PaperMarketDataUnavailableError("Zerodha instruments unavailable") from exc
        output: list[PaperOptionInstrument] = []
        for _, row in frame.iterrows():
            try:
                side = OptionSide(str(row["instrument_type"]))
                token = int(row["instrument_token"])
                symbol = str(row["tradingsymbol"])
                exchange = str(row.get("exchange") or "NFO")
                key = f"{exchange}|{token}"
                output.append(PaperOptionInstrument(
                    instrument_key=key,
                    instrument_token=token,
                    trading_symbol=symbol,
                    underlying=underlying,
                    expiry=row["expiry"],
                    strike=float(row["strike"]),
                    option_side=side,
                    lot_size=int(row.get("lot_size") or 1),
                    provider=self.provider_name,
                ))
                self._symbol_to_key[f"{exchange}:{symbol}"] = key
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(output)

    def quotes(self, *, instrument_keys: tuple[str, ...], evaluated_at: datetime) -> tuple[PaperMarketQuote, ...]:
        if not instrument_keys:
            return ()
        reverse = {value: key for key, value in self._symbol_to_key.items()}
        request_keys = [reverse.get(key, key.replace("|", ":", 1)) for key in instrument_keys]
        try:
            payload = self._client.quote(request_keys)
        except ZerodhaAPIError as exc:
            message = str(exc).lower()
            if "token" in message or "auth" in message or "permission" in message:
                raise PaperMarketDataAuthenticationError("Zerodha authentication failed") from exc
            raise PaperMarketDataUnavailableError("Zerodha quotes unavailable") from exc
        quotes: list[PaperMarketQuote] = []
        for requested, raw_key in zip(instrument_keys, request_keys):
            row: dict[str, Any] = dict(payload.get(raw_key) or {})
            if not row:
                continue
            depth = row.get("depth") or {}
            buy = depth.get("buy") or []
            sell = depth.get("sell") or []
            timestamp = self._timestamp(row.get("timestamp") or row.get("last_trade_time"))
            quote = PaperMarketQuote(
                instrument_key=requested,
                instrument_token=row.get("instrument_token") or requested.rsplit("|", 1)[-1],
                last_price=row.get("last_price"),
                bid_price=(buy[0].get("price") if buy else None),
                ask_price=(sell[0].get("price") if sell else None),
                quote_timestamp=timestamp,
                provider=self.provider_name,
            )
            verify_quote_freshness(
                quote,
                evaluated_at=evaluated_at,
                maximum_age_seconds=self._maximum_quote_age_seconds,
            )
            quotes.append(quote)
        return tuple(quotes)
