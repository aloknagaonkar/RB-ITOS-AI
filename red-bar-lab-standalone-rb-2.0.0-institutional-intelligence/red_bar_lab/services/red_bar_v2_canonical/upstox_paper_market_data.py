from __future__ import annotations

from collections.abc import Mapping
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
    PaperMarketDataDiagnosticError,
    PaperMarketDataRateLimitError,
    PaperMarketDataUnavailableError,
    PaperMarketQuote,
    PaperOptionInstrument,
    PaperUnderlyingQuote,
    finite_positive_number,
    verify_quote_freshness,
    verify_timestamp_freshness,
)
from .paper_market_data_readiness_models import MarketDataReadinessStage


class UpstoxPaperCanaryMarketData:
    provider_name = "UPSTOX"

    def __init__(self, client: UpstoxClient, *, underlying_keys: dict[str, str], maximum_quote_age_seconds: float) -> None:
        self._client = client
        self._underlying_keys = dict(underlying_keys)
        self._maximum_quote_age_seconds = finite_positive_number("maximum_quote_age_seconds", maximum_quote_age_seconds)
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
        normalized = cls._normalize_token(row.get("instrument_token") or row.get("exchange_token"))
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

    def underlying_quote(self, *, underlying: str, evaluated_at: datetime) -> PaperUnderlyingQuote:
        key = self._underlying_keys.get(underlying)
        if not key:
            raise PaperMarketDataCorruptionError("unsupported Upstox underlying")
        payload = self._full_quotes((key,))
        rows = self._correlate_quote_rows(payload=payload, requested_keys=(key,), require_known_token=False)
        row = rows.get(key)
        if row is None:
            raise PaperMarketDataUnavailableError("Upstox underlying quote unavailable")
        timestamp = self._timestamp(row.get("timestamp") or row.get("last_trade_time") or row.get("exchange_timestamp"))
        try:
            quote = PaperUnderlyingQuote(key, underlying, row.get("last_price") or row.get("ltp"), timestamp, self.provider_name)
        except (TypeError, ValueError) as exc:
            raise PaperMarketDataCorruptionError("malformed Upstox underlying quote") from exc
        verify_timestamp_freshness(
            timestamp=quote.quote_timestamp,
            evaluated_at=evaluated_at,
            maximum_age_seconds=self._maximum_quote_age_seconds,
        )
        return quote

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
                side = OptionSide(str(row.get("instrument_type") or row.get("option_type") or row.get("option_side") or "").upper())
                expiry = self._expiry(row.get("expiry"))
                if expiry < evaluated_at.date():
                    continue
                symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or "").strip()
                if not key or not symbol or key in seen_keys:
                    raise PaperMarketDataCorruptionError("Upstox contract identity missing or duplicated")
                token = self._token(row, key)
                owner = token_owners.get(str(token))
                if owner is not None and owner != key:
                    raise PaperMarketDataCorruptionError("Upstox contract token is ambiguous")
                seen_keys.add(key)
                token_owners[str(token)] = key
                instrument = PaperOptionInstrument(
                    key,
                    token,
                    symbol,
                    underlying,
                    expiry,
                    finite_positive_number("strike", row.get("strike_price") or row.get("strike")),
                    side,
                    int(row.get("lot_size")),
                    self.provider_name,
                )
                output.append(instrument)
                self._expected_tokens[key] = token
            except PaperMarketDataCorruptionError:
                raise
            except (TypeError, ValueError) as exc:
                raise PaperMarketDataCorruptionError("malformed Upstox option contract") from exc
        return tuple(sorted(output, key=lambda item: (item.expiry, item.strike, item.option_side.value)))

    @staticmethod
    def _add_index(index: dict[str, set[str]], identity: str | None, requested_key: str) -> None:
        if identity is not None:
            index.setdefault(identity, set()).add(requested_key)

    def _requested_indexes(
        self,
        requested_keys: tuple[str, ...],
        *,
        require_known_token: bool,
    ) -> tuple[dict[str, str], dict[str, set[str]], dict[str, set[str]]]:
        exact: dict[str, str] = {}
        normalized: dict[str, set[str]] = {}
        tokens: dict[str, set[str]] = {}
        for requested_key in requested_keys:
            if requested_key in exact:
                raise PaperMarketDataDiagnosticError(
                    stage=MarketDataReadinessStage.OPTION_QUOTE_CORRELATION,
                    reason_code="OPTION_QUOTE_IDENTITY_AMBIGUOUS",
                    source_component="upstox_quote_correlation",
                    rejected_field="quote_identity",
                    received_count=len(requested_keys),
                    normalized_count=0,
                    rejected_count=1,
                )
            exact[requested_key] = requested_key
            self._add_index(normalized, self._normalize_key(requested_key), requested_key)
            expected_token = self._expected_tokens.get(requested_key)
            if require_known_token and expected_token is None:
                raise PaperMarketDataDiagnosticError(
                    stage=MarketDataReadinessStage.OPTION_QUOTE_CORRELATION,
                    reason_code="OPTION_QUOTE_IDENTITY_MISSING",
                    source_component="upstox_quote_correlation",
                    rejected_field="instrument_token",
                    received_count=len(requested_keys),
                    normalized_count=0,
                    rejected_count=1,
                )
            if expected_token is not None:
                tokens.setdefault(str(expected_token), set()).add(requested_key)
                self._add_index(normalized, self._normalize_key(expected_token), requested_key)
        return exact, normalized, tokens

    def _identity_matches(
        self,
        value: object,
        *,
        exact: dict[str, str],
        normalized: dict[str, set[str]],
        tokens: dict[str, set[str]],
        permit_token_lookup: bool,
    ) -> set[str]:
        matches: set[str] = set()
        if type(value) is str:
            stripped = value.strip()
            if stripped in exact:
                matches.add(exact[stripped])
            normalized_key = self._normalize_key(value)
            if normalized_key is not None:
                matches.update(normalized.get(normalized_key, ()))
        if permit_token_lookup:
            token = self._normalize_token(value)
            if token is not None:
                matches.update(tokens.get(str(token), ()))
        return matches

    def _quote_diagnostic(
        self,
        *,
        reason_code: str,
        payload_count: int,
        correlated_count: int,
        rejected_count: int,
        rejected_field: str,
        rejected_type: str | None = None,
    ) -> PaperMarketDataDiagnosticError:
        return PaperMarketDataDiagnosticError(
            stage=MarketDataReadinessStage.OPTION_QUOTE_CORRELATION,
            reason_code=reason_code,
            source_component="upstox_quote_correlation",
            received_count=payload_count,
            normalized_count=correlated_count,
            rejected_count=rejected_count,
            rejected_field=rejected_field,
            rejected_type=rejected_type,
        )

    def _correlate_quote_rows(
        self,
        *,
        payload: dict[str, Any],
        requested_keys: tuple[str, ...],
        require_known_token: bool = True,
    ) -> dict[str, dict[str, Any]]:
        exact, normalized, tokens = self._requested_indexes(
            requested_keys,
            require_known_token=require_known_token,
        )
        payload_count = len(payload)
        matched: dict[str, dict[str, Any]] = {}

        for response_key, raw_row in payload.items():
            if not isinstance(raw_row, Mapping):
                raise self._quote_diagnostic(
                    reason_code="OPTION_QUOTE_ROW_NOT_MAPPING",
                    payload_count=payload_count,
                    correlated_count=len(matched),
                    rejected_count=1,
                    rejected_field="response_shape",
                    rejected_type=type(raw_row).__name__,
                )

            embedded_fields = (
                ("instrument_token", raw_row.get("instrument_token"), True),
                ("instrument_key", raw_row.get("instrument_key"), False),
                ("instrument_key", raw_row.get("instrumentKey"), False),
            )
            requested_key: str | None = None
            primary_field: str | None = None
            for field_name, value, permit_token_lookup in embedded_fields:
                if value is None or (type(value) is str and not value.strip()):
                    continue
                candidates = self._identity_matches(
                    value,
                    exact=exact,
                    normalized=normalized,
                    tokens=tokens,
                    permit_token_lookup=permit_token_lookup,
                )
                if len(candidates) > 1:
                    raise self._quote_diagnostic(
                        reason_code="OPTION_QUOTE_IDENTITY_AMBIGUOUS",
                        payload_count=payload_count,
                        correlated_count=len(matched),
                        rejected_count=1,
                        rejected_field=field_name,
                    )
                if not candidates:
                    raise self._quote_diagnostic(
                        reason_code="OPTION_QUOTE_IDENTITY_UNREQUESTED",
                        payload_count=payload_count,
                        correlated_count=len(matched),
                        rejected_count=1,
                        rejected_field=field_name,
                    )
                requested_key = next(iter(candidates))
                primary_field = field_name
                break

            outer_candidates = self._identity_matches(
                response_key,
                exact=exact,
                normalized=normalized,
                tokens=tokens,
                permit_token_lookup=False,
            )
            if len(outer_candidates) > 1:
                raise self._quote_diagnostic(
                    reason_code="OPTION_QUOTE_IDENTITY_AMBIGUOUS",
                    payload_count=payload_count,
                    correlated_count=len(matched),
                    rejected_count=1,
                    rejected_field="quote_identity",
                )
            if requested_key is None:
                if len(outer_candidates) == 1:
                    requested_key = next(iter(outer_candidates))
                    primary_field = "quote_identity"
                elif type(response_key) is not str or not response_key.strip():
                    raise self._quote_diagnostic(
                        reason_code="OPTION_QUOTE_IDENTITY_MISSING",
                        payload_count=payload_count,
                        correlated_count=len(matched),
                        rejected_count=1,
                        rejected_field="quote_identity",
                    )
                else:
                    raise self._quote_diagnostic(
                        reason_code="OPTION_QUOTE_IDENTITY_UNREQUESTED",
                        payload_count=payload_count,
                        correlated_count=len(matched),
                        rejected_count=1,
                        rejected_field="quote_identity",
                    )

            for field_name, value, permit_token_lookup in embedded_fields:
                if field_name == primary_field or value is None or (type(value) is str and not value.strip()):
                    continue
                candidates = self._identity_matches(
                    value,
                    exact=exact,
                    normalized=normalized,
                    tokens=tokens,
                    permit_token_lookup=permit_token_lookup,
                )
                if len(candidates) > 1:
                    raise self._quote_diagnostic(
                        reason_code="OPTION_QUOTE_IDENTITY_AMBIGUOUS",
                        payload_count=payload_count,
                        correlated_count=len(matched),
                        rejected_count=1,
                        rejected_field=field_name,
                    )
                if candidates and requested_key not in candidates:
                    raise self._quote_diagnostic(
                        reason_code="OPTION_QUOTE_IDENTITY_CONFLICT",
                        payload_count=payload_count,
                        correlated_count=len(matched),
                        rejected_count=1,
                        rejected_field=field_name,
                    )
            if outer_candidates and requested_key not in outer_candidates:
                raise self._quote_diagnostic(
                    reason_code="OPTION_QUOTE_IDENTITY_CONFLICT",
                    payload_count=payload_count,
                    correlated_count=len(matched),
                    rejected_count=1,
                    rejected_field="quote_identity",
                )
            if requested_key in matched:
                raise self._quote_diagnostic(
                    reason_code="OPTION_QUOTE_DUPLICATE",
                    payload_count=payload_count,
                    correlated_count=len(matched),
                    rejected_count=1,
                    rejected_field="duplicate_identity",
                )
            if raw_row.get("last_price") is None and raw_row.get("ltp") is None:
                raise self._quote_diagnostic(
                    reason_code="OPTION_QUOTE_REQUIRED_FIELD_MISSING",
                    payload_count=payload_count,
                    correlated_count=len(matched),
                    rejected_count=1,
                    rejected_field="quote_price",
                )
            if raw_row.get("timestamp") is None and raw_row.get("last_trade_time") is None and raw_row.get("exchange_timestamp") is None:
                raise self._quote_diagnostic(
                    reason_code="OPTION_QUOTE_REQUIRED_FIELD_MISSING",
                    payload_count=payload_count,
                    correlated_count=len(matched),
                    rejected_count=1,
                    rejected_field="quote_timestamp",
                )
            matched[requested_key] = dict(raw_row)

        missing_count = len(requested_keys) - len(matched)
        if missing_count:
            raise self._quote_diagnostic(
                reason_code="OPTION_QUOTE_COUNT_INCOMPLETE",
                payload_count=payload_count,
                correlated_count=len(matched),
                rejected_count=missing_count,
                rejected_field="quote_identity",
            )
        return matched

    def quotes(self, *, instrument_keys: tuple[str, ...], evaluated_at: datetime) -> tuple[PaperMarketQuote, ...]:
        if not instrument_keys:
            return ()
        requested_keys = tuple(self._normalize_key(key) or "" for key in instrument_keys)
        if any(not key for key in requested_keys):
            raise PaperMarketDataCorruptionError("invalid requested Upstox instrument key")
        rows = self._correlate_quote_rows(
            payload=self._full_quotes(requested_keys),
            requested_keys=requested_keys,
        )
        output: list[PaperMarketQuote] = []
        for key in requested_keys:
            row = rows[key]
            depth = row.get("market_depth") or row.get("depth") or {}
            if not isinstance(depth, dict):
                raise PaperMarketDataCorruptionError("malformed Upstox market depth")
            buy = depth.get("buy") or depth.get("bids") or []
            sell = depth.get("sell") or depth.get("asks") or []
            if not isinstance(buy, list) or not isinstance(sell, list):
                raise PaperMarketDataCorruptionError("malformed Upstox market depth")
            timestamp = self._timestamp(row.get("timestamp") or row.get("last_trade_time") or row.get("exchange_timestamp"))
            token = self._normalize_token(row.get("instrument_token") or row.get("exchange_token")) or self._expected_tokens.get(key)
            if token is None:
                raise PaperMarketDataCorruptionError("Upstox quote token identity is missing")
            try:
                quote = PaperMarketQuote(
                    key,
                    token,
                    row.get("last_price") or row.get("ltp"),
                    buy[0].get("price") if buy else row.get("bid_price"),
                    sell[0].get("price") if sell else row.get("ask_price"),
                    timestamp,
                    self.provider_name,
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
