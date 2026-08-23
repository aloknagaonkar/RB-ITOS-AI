from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.brokers.zerodha_client import ZerodhaAPIError, ZerodhaKiteClient
from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data import (
    PaperMarketDataAuthenticationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataUnavailableError,
    PaperMarketQuote,
    PaperOptionInstrument,
    PaperUnderlyingQuote,
    finite_positive_number,
    verify_quote_freshness,
    verify_timestamp_freshness,
)

IST = ZoneInfo("Asia/Kolkata")
_ZERODHA_UNDERLYINGS = {"NIFTY 50": "NSE:NIFTY 50", "BANK NIFTY": "NSE:NIFTY BANK"}


class ZerodhaPaperCanaryMarketData:
    provider_name = "ZERODHA"

    def __init__(self, client: ZerodhaKiteClient, *, maximum_quote_age_seconds: float) -> None:
        self._client = client
        self._maximum_quote_age_seconds = finite_positive_number("maximum_quote_age_seconds", maximum_quote_age_seconds)
        self._symbol_to_key: dict[str, str] = {}

    @staticmethod
    def _timestamp(value: object) -> datetime:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed): raise PaperMarketDataCorruptionError("Zerodha quote timestamp missing")
        result = parsed.to_pydatetime()
        return result.replace(tzinfo=IST) if result.tzinfo is None or result.utcoffset() is None else result

    def _quote_payload(self, keys: list[str]) -> dict[str, object]:
        try:
            return self._client.quote(keys)
        except ZerodhaAPIError as exc:
            text = str(exc).lower()
            if "token" in text or "auth" in text or "permission" in text:
                raise PaperMarketDataAuthenticationError("Zerodha authentication failed") from exc
            raise PaperMarketDataUnavailableError("Zerodha market data unavailable") from exc

    def underlying_quote(self, *, underlying: str, evaluated_at: datetime) -> PaperUnderlyingQuote:
        key = _ZERODHA_UNDERLYINGS.get(underlying)
        if key is None: raise PaperMarketDataCorruptionError("unsupported Zerodha underlying")
        row = self._quote_payload([key]).get(key)
        if not isinstance(row, dict) or not row: raise PaperMarketDataUnavailableError("Zerodha underlying quote unavailable")
        timestamp = self._timestamp(row.get("timestamp") or row.get("last_trade_time"))
        try:
            quote = PaperUnderlyingQuote(key, underlying, row.get("last_price"), timestamp, self.provider_name)
        except (TypeError, ValueError) as exc:
            raise PaperMarketDataCorruptionError("malformed Zerodha underlying quote") from exc
        verify_timestamp_freshness(timestamp=quote.quote_timestamp, evaluated_at=evaluated_at, maximum_age_seconds=self._maximum_quote_age_seconds)
        return quote

    def option_instruments(self, *, underlying: str, evaluated_at: datetime) -> tuple[PaperOptionInstrument, ...]:
        try:
            frame = self._client.nfo_options(underlying_name=underlying, as_of=evaluated_at.date())
        except ZerodhaAPIError as exc:
            raise PaperMarketDataUnavailableError("Zerodha instruments unavailable") from exc
        if frame.empty: return ()
        output: list[PaperOptionInstrument] = []; seen: set[str] = set()
        for _, row in frame.iterrows():
            try:
                side = OptionSide(str(row["instrument_type"])); token = int(row["instrument_token"])
                symbol = str(row["tradingsymbol"]).strip(); exchange = str(row.get("exchange") or "NFO").strip(); key = f"{exchange}|{token}"
                if not symbol or key in seen: raise PaperMarketDataCorruptionError("Zerodha contract identity missing or duplicated")
                seen.add(key)
                output.append(PaperOptionInstrument(key, token, symbol, underlying, row["expiry"], finite_positive_number("strike", row["strike"]), side, int(row.get("lot_size") or 1), self.provider_name))
                self._symbol_to_key[f"{exchange}:{symbol}"] = key
            except PaperMarketDataCorruptionError: raise
            except (KeyError, TypeError, ValueError) as exc: raise PaperMarketDataCorruptionError("malformed Zerodha option contract") from exc
        return tuple(output)

    def quotes(self, *, instrument_keys: tuple[str, ...], evaluated_at: datetime) -> tuple[PaperMarketQuote, ...]:
        if not instrument_keys: return ()
        reverse = {value: key for key, value in self._symbol_to_key.items()}
        request_keys = [reverse.get(key, key.replace("|", ":", 1)) for key in instrument_keys]
        payload = self._quote_payload(request_keys)
        quotes: list[PaperMarketQuote] = []
        for requested, raw_key in zip(instrument_keys, request_keys):
            row: dict[str, Any] = dict(payload.get(raw_key) or {})
            if not row: continue
            depth = row.get("depth") or {}; buy = depth.get("buy") or []; sell = depth.get("sell") or []
            timestamp = self._timestamp(row.get("timestamp") or row.get("last_trade_time"))
            try:
                quote = PaperMarketQuote(requested, row.get("instrument_token") or requested.rsplit("|", 1)[-1], row.get("last_price"), buy[0].get("price") if buy else None, sell[0].get("price") if sell else None, timestamp, self.provider_name)
            except (TypeError, ValueError) as exc: raise PaperMarketDataCorruptionError("malformed Zerodha quote values") from exc
            verify_quote_freshness(quote, evaluated_at=evaluated_at, maximum_age_seconds=self._maximum_quote_age_seconds)
            quotes.append(quote)
        return tuple(quotes)
