from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import unquote

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
    finite_positive_number,
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
        self._maximum_quote_age_seconds = finite_positive_number(
            "maximum_quote_age_seconds",
            maximum_quote_age_seconds,
        )
        self._expected_tokens: dict[str, int | str] = {}

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
    def _normalize_key(value: object) -> str | None:
        if type(value) is not str or not value.strip():
            return None
        text = unquote(value.strip())
        if "|" not in text and ":" in text:
            exchange, remainder = text.split(":", 1)
            text = f"{exchange}|{remainder}"
        return text

    @staticmethod
    def _normalize_token(value: object) -> int | str | None:
        if type(value) is int and value > 0:
            return value
        if type(value) is str and value.strip():
            text = value.strip()
            return int(text) if text.isdigit() and int(text) > 0 else text
        return None

    @classmethod
    def _token(cls, row: dict[str, Any], instrument_key: str) -> int | str:
        normalized = cls._normalize_token(
            row.get("instrument_token") or row.get("exchange_token")
        )
        if normalized is not None:
            return normalized
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
        if not rows:
            return ()
        output: list[PaperOptionInstrument] = []
        seen_keys: set[str] = set()
        token_owners: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise PaperMarketDataCorruptionError("malformed Upstox option contract")
            try:
                key = self._normalize_key(row.get("instrument_key"))
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
                if not key or not symbol or key in seen_keys:
                    raise PaperMarketDataCorruptionError("Upstox contract identity missing or duplicated")
                token = self._token(row, key)
                token_identity = str(token)
                previous_owner = token_owners.get(token_identity)
                if previous_owner is not None and previous_owner != key:
                    raise PaperMarketDataCorruptionError("Upstox contract token is ambiguous")
                seen_keys.add(key)
                token_owners[token_identity] = key
                instrument = PaperOptionInstrument(
                    instrument_key=key,
                    instrument_token=token,
                    trading_symbol=symbol,
                    underlying=underlying,
                    expiry=expiry,
                    strike=finite_positive_number(
                        "strike",
                        row.get("strike_price") or row.get("strike"),
                    ),
                    option_side=side,
                    lot_size=int(row.get("lot_size")),
                    provider=self.provider_name,
                )
                output.append(instrument)
                self._expected_tokens[key] = token
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

    def _correlate_quote_rows(
        self,
        *,
        payload: dict[str, Any],
        requested_keys: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        if not payload:
            return {}
        requested = set(requested_keys)
        if len(requested) != len(requested_keys):
            raise PaperMarketDataCorruptionError("duplicate requested Upstox quote identity")
        matched: dict[str, dict[str, Any]] = {}
        for response_key, raw_row in payload.items():
            if not isinstance(raw_row, dict):
                raise PaperMarketDataCorruptionError("malformed Upstox quote row")
            response_identity = self._normalize_key(response_key)
            row_identity = self._normalize_key(
                raw_row.get("instrument_key") or raw_row.get("instrumentKey")
            )
            row_token = self._normalize_token(
                raw_row.get("instrument_token") or raw_row.get("exchange_token")
            )

            identity_matches = {
                value
                for value in (response_identity, row_identity)
                if value in requested
            }
            token_matches = {
                key
                for key in requested
                if row_token is not None
                and str(self._expected_tokens.get(key)) == str(row_token)
            }
            candidates = identity_matches | token_matches
            if not candidates:
                raise PaperMarketDataCorruptionError(
                    "Upstox returned a quote for an unrequested contract"
                )
            if len(candidates) != 1:
                raise PaperMarketDataCorruptionError(
                    "Upstox quote identity is ambiguous"
                )
            requested_key = next(iter(candidates))

            for actual_identity in (response_identity, row_identity):
                if actual_identity is not None and actual_identity != requested_key:
                    raise PaperMarketDataCorruptionError(
                        "Upstox quote instrument key conflicts with request"
                    )
            expected_token = self._expected_tokens.get(requested_key)
            if row_token is not None and expected_token is not None:
                if str(row_token) != str(expected_token):
                    raise PaperMarketDataCorruptionError(
                        "Upstox quote instrument token conflicts with contract"
                    )
            if requested_key in matched:
                raise PaperMarketDataCorruptionError(
                    "duplicate Upstox quote response identity"
                )
            matched[requested_key] = raw_row
        return matched

    def quotes(self, *, instrument_keys: tuple[str, ...], evaluated_at: datetime) -> tuple[PaperMarketQuote, ...]:
        if not instrument_keys:
            return ()
        requested_keys = tuple(
            self._normalize_key(key) or ""
            for key in instrument_keys
        )
        if any(not key for key in requested_keys):
            raise PaperMarketDataCorruptionError("invalid requested Upstox instrument key")
        payload = self._full_quotes(requested_keys)
        rows = self._correlate_quote_rows(
            payload=payload,
            requested_keys=requested_keys,
        )
        output: list[PaperMarketQuote] = []
        for key in requested_keys:
            row = rows.get(key)
            if row is None:
                continue
            depth = row.get("market_depth") or row.get("depth") or {}
            if depth is not None and not isinstance(depth, dict):
                raise PaperMarketDataCorruptionError("malformed Upstox market depth")
            buy = depth.get("buy") or depth.get("bids") or []
            sell = depth.get("sell") or depth.get("asks") or []
            if not isinstance(buy, list) or not isinstance(sell, list):
                raise PaperMarketDataCorruptionError("malformed Upstox market depth")
            timestamp = self._timestamp(
                row.get("timestamp")
                or row.get("last_trade_time")
                or row.get("exchange_timestamp")
            )
            row_token = self._normalize_token(
                row.get("instrument_token") or row.get("exchange_token")
            )
            expected_token = self._expected_tokens.get(key)
            token = row_token if row_token is not None else expected_token
            if token is None:
                raise PaperMarketDataCorruptionError(
                    "Upstox quote token identity is missing"
                )
            try:
                quote = PaperMarketQuote(
                    instrument_key=key,
                    instrument_token=token,
                    last_price=row.get("last_price") or row.get("ltp"),
                    bid_price=(buy[0].get("price") if buy else row.get("bid_price")),
                    ask_price=(sell[0].get("price") if sell else row.get("ask_price")),
                    quote_timestamp=timestamp,
                    provider=self.provider_name,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise PaperMarketDataCorruptionError("malformed Upstox quote values") from exc
            verify_quote_freshness(
                quote,
                evaluated_at=evaluated_at,
                maximum_age_seconds=self._maximum_quote_age_seconds,
            )
            output.append(quote)
        return tuple(output)
