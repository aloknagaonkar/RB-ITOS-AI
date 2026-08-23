from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import requests

from red_bar_lab.brokers.upstox_client import UpstoxAPIError, UpstoxClient
from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data import (
    PaperMarketDataAuthenticationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataRateLimitError,
    PaperMarketDataUnavailableError,
    PaperMarketQuote,
    PaperOptionInstrument,
    verify_quote_freshness,
)


class UpstoxPaperCanaryMarketData:
    provider_name = "UPSTOX"

    def __init__(
        self,
        client: UpstoxClient,
        *,
        underlying_keys: dict[str, str],
        maximum_quote_age_seconds: float,
    ) -> None:
        self._client = client
        self._underlying_keys = dict(underlying_keys)
        self._maximum_quote_age_seconds = float(maximum_quote_age_seconds)

    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        status = getattr(exc, "status_code", None)
        text = str(exc).lower()
        if status in (401, 403) or "http 401" in text or "http 403" in text or "authentication" in text or "unauthorized" in text:
            return PaperMarketDataAuthenticationError("Upstox authentication failed")
        if status == 429 or "http 429" in text or "rate limit" in text:
            return PaperMarketDataRateLimitError("Upstox rate limit reached")
        return PaperMarketDataUnavailableError("Upstox market data unavailable")

    @staticmethod
    def _token(row: dict[str, Any], instrument_key: str) -> int | str:
        raw = row.get("instrument_token") or row.get("exchange_token")
        if type(raw) is int and raw > 0:
            return raw
        if type(raw) is str and raw.strip():
            return raw.strip()
        suffix = instrument_key.rsplit("|", 1)[-1]
        return int(suffix) if suffix.isdigit() and int(suffix) > 0 else instrument_key

    @staticmethod
    def _expiry(value: object) -> date:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise PaperMarketDataCorruptionError("Upstox option expiry missing")
        return parsed.date()

    @staticmethod
    def _timestamp(value: object) -> datetime:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise PaperMarketDataCorruptionError("Upstox quote timestamp missing")
        result = parsed.to_pydatetime()
        if result.tzinfo is None or result.utcoffset() is None:
            raise PaperMarketDataCorruptionError("Upstox quote timestamp is naive")
        return result

    def option_instruments(self, *, underlying: str, evaluated_at: datetime) -> tuple[PaperOptionInstrument, ...]:
        underlying_key = self._underlying_keys.get(underlying)
        if not underlying_key:
            raise PaperMarketDataCorruptionError("unsupported Upstox underlying")
        try:
            rows = self._client.get_option_contracts(underlying_key)
        except UpstoxAPIError as exc:
            raise self._map_error(exc) from exc
        output: list[PaperOptionInstrument] = []
        seen: set[str] = set()
        for row in rows:
            try:
                key = str(row.get("instrument_key") or "").strip()
                side_text = str(
                    row.get("instrument_type")
                    or row.get("option_type")
                    or row.get("option_side")
                    or ""
                ).upper()
                side = OptionSide(side_text)
                expiry = self._expiry(row.get("expiry"))
                if expiry < evaluated_at.date():
                    continue
                symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or "").strip()
                if not key or not symbol or key in seen:
                    raise PaperMarketDataCorruptionError("Upstox contract identity missing or duplicated")
                seen.add(key)
                output.append(PaperOptionInstrument(
                    instrument_key=key,
                    instrument_token=self._token(row, key),
                    trading_symbol=symbol,
                    underlying=underlying,
                    expiry=expiry,
                    strike=float(row.get("strike_price") or row.get("strike")),
                    option_side=side,
                    lot_size=int(row.get("lot_size")),
                    provider=self.provider_name,
                ))
            except PaperMarketDataCorruptionError:
                raise
            except (TypeError, ValueError) as exc:
                raise PaperMarketDataCorruptionError("malformed Upstox option contract") from exc
        return tuple(sorted(output, key=lambda item: (item.expiry, item.strike, item.option_side.value)))

    def _full_quotes(self, instrument_keys: tuple[str, ...]) -> dict[str, Any]:
        try:
            response = self._client.session.get(
                f"{self._client.BASE_URL_V2}/market-quote/quotes",
                params={"instrument_key": ",".join(instrument_keys)},
                headers=self._client._headers(),
                timeout=self._client.timeout,
            )
            self._client._raise_for_api_error(response)
            payload = response.json()
        except UpstoxAPIError as exc:
            raise self._map_error(exc) from exc
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise PaperMarketDataUnavailableError("Upstox quotes unavailable") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise PaperMarketDataCorruptionError("malformed Upstox quote response")
        return data

    def quotes(self, *, instrument_keys: tuple[str, ...], evaluated_at: datetime) -> tuple[PaperMarketQuote, ...]:
        if not instrument_keys:
            return ()
        payload = self._full_quotes(instrument_keys)
        output: list[PaperMarketQuote] = []
        for key in instrument_keys:
            row = payload.get(key)
            if row is None:
                row = next(
                    (value for value in payload.values() if isinstance(value, dict) and value.get("instrument_token") == key),
                    None,
                )
            if row is None:
                continue
            if not isinstance(row, dict):
                raise PaperMarketDataCorruptionError("malformed Upstox quote row")
            depth = row.get("market_depth") or row.get("depth") or {}
            buy = depth.get("buy") or depth.get("bids") or []
            sell = depth.get("sell") or depth.get("asks") or []
            timestamp = self._timestamp(
                row.get("timestamp")
                or row.get("last_trade_time")
                or row.get("exchange_timestamp")
            )
            try:
                quote = PaperMarketQuote(
                    instrument_key=key,
                    instrument_token=row.get("instrument_token") or key,
                    last_price=row.get("last_price") or row.get("ltp"),
                    bid_price=(buy[0].get("price") if buy else row.get("bid_price")),
                    ask_price=(sell[0].get("price") if sell else row.get("ask_price")),
                    quote_timestamp=timestamp,
                    provider=self.provider_name,
                )
            except (TypeError, ValueError) as exc:
                raise PaperMarketDataCorruptionError("malformed Upstox quote values") from exc
            verify_quote_freshness(
                quote,
                evaluated_at=evaluated_at,
                maximum_age_seconds=self._maximum_quote_age_seconds,
            )
            output.append(quote)
        return tuple(output)
