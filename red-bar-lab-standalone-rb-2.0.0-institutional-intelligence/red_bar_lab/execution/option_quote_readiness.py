from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

QUOTE_READY = "READY"
QUOTE_MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
QUOTE_INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
QUOTE_STALE = "STALE"
QUOTE_ZERO_LTP = "ZERO_LTP"
QUOTE_MISSING_BID_ASK = "MISSING_BID_ASK"
QUOTE_CROSSED_MARKET = "CROSSED_MARKET"
QUOTE_WIDE_SPREAD = "WIDE_SPREAD"

_TIMESTAMP_FIELDS = (
    "last_trade_time",
    "last_trade_timestamp",
    "exchange_timestamp",
    "quote_timestamp",
    "timestamp",
)


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_level(depth: object, side: str) -> Mapping[str, object]:
    if not isinstance(depth, Mapping):
        return {}
    levels = depth.get(side) or []
    if not isinstance(levels, list) or not levels:
        return {}
    level = levels[0]
    return level if isinstance(level, Mapping) else {}


def _parse_timestamp(value: object, reference: datetime) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        try:
            parsed = datetime.fromtimestamp(numeric, tz=reference.tzinfo)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=reference.tzinfo)
    return parsed.astimezone(reference.tzinfo)


def _timestamp_value(quote: Mapping[str, object]) -> object | None:
    for field in _TIMESTAMP_FIELDS:
        value = quote.get(field)
        if value not in (None, ""):
            return value
    return None


@dataclass(frozen=True)
class OptionQuoteReadiness:
    status: str
    reason: str
    quote_timestamp: datetime | None
    quote_age_seconds: float | None
    last_price: float | None
    best_bid: float | None
    best_ask: float | None
    spread_pct: float | None

    @property
    def ready(self) -> bool:
        return self.status == QUOTE_READY


def assess_option_quote_readiness(
    quote: Mapping[str, object],
    *,
    observed_at: datetime,
    stale_after_seconds: float = 60.0,
    max_spread_pct: float = 2.0,
) -> OptionQuoteReadiness:
    """Assess option quote freshness and executable market quality.

    The result is observational only. It does not grant or remove execution
    authority and is intended for telemetry and readiness diagnostics.
    """

    last_price = _number(quote.get("last_price"))
    depth = quote.get("depth") or {}
    best_bid = _number(_first_level(depth, "buy").get("price"))
    best_ask = _number(_first_level(depth, "sell").get("price"))

    spread_pct: float | None = None
    if best_bid is not None and best_ask is not None:
        midpoint = (best_bid + best_ask) / 2.0
        if midpoint > 0:
            spread_pct = (best_ask - best_bid) / midpoint * 100.0

    raw_timestamp = _timestamp_value(quote)
    if raw_timestamp is None:
        return OptionQuoteReadiness(
            QUOTE_MISSING_TIMESTAMP,
            "Quote timestamp is missing.",
            None,
            None,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    quote_timestamp = _parse_timestamp(raw_timestamp, observed_at)
    if quote_timestamp is None:
        return OptionQuoteReadiness(
            QUOTE_INVALID_TIMESTAMP,
            "Quote timestamp is invalid.",
            None,
            None,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    quote_age_seconds = (observed_at - quote_timestamp).total_seconds()
    if quote_age_seconds < -5.0:
        return OptionQuoteReadiness(
            QUOTE_INVALID_TIMESTAMP,
            "Quote timestamp is unexpectedly ahead of observation time.",
            quote_timestamp,
            quote_age_seconds,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    quote_age_seconds = max(0.0, quote_age_seconds)
    if quote_age_seconds > max(0.0, float(stale_after_seconds)):
        return OptionQuoteReadiness(
            QUOTE_STALE,
            (
                f"Quote age {quote_age_seconds:.1f}s exceeds the "
                f"{float(stale_after_seconds):.1f}s limit."
            ),
            quote_timestamp,
            quote_age_seconds,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    if last_price is None or last_price <= 0.0:
        return OptionQuoteReadiness(
            QUOTE_ZERO_LTP,
            "Last traded price is missing, zero, or negative.",
            quote_timestamp,
            quote_age_seconds,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return OptionQuoteReadiness(
            QUOTE_MISSING_BID_ASK,
            "Best bid or best ask is missing or non-positive.",
            quote_timestamp,
            quote_age_seconds,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    if best_bid > best_ask:
        return OptionQuoteReadiness(
            QUOTE_CROSSED_MARKET,
            "Best bid exceeds best ask.",
            quote_timestamp,
            quote_age_seconds,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    if spread_pct is not None and spread_pct > float(max_spread_pct):
        return OptionQuoteReadiness(
            QUOTE_WIDE_SPREAD,
            (
                f"Bid-ask spread {spread_pct:.3f}% exceeds the "
                f"{float(max_spread_pct):.3f}% limit."
            ),
            quote_timestamp,
            quote_age_seconds,
            last_price,
            best_bid,
            best_ask,
            spread_pct,
        )

    return OptionQuoteReadiness(
        QUOTE_READY,
        "Quote timestamp, price, bid, ask, and spread are usable.",
        quote_timestamp,
        quote_age_seconds,
        last_price,
        best_bid,
        best_ask,
        spread_pct,
    )
