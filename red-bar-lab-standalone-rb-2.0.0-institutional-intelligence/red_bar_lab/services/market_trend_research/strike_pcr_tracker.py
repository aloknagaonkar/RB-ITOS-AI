from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Mapping, Sequence

from .policy import MarketTrendResearchPolicy


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if isfinite(result) else None


def _pcr(pe_oi: object, ce_oi: object) -> float | None:
    pe = _number(pe_oi)
    ce = _number(ce_oi)
    return None if pe is None or ce is None or ce <= 0 else pe / ce


def _signal(pcr: float | None) -> str:
    if pcr is None:
        return "UNAVAILABLE"
    return MarketTrendResearchPolicy().classify(pcr).value


def _recommendation(signal: str) -> str:
    if signal == "BEARISH":
        return "BUY_PE"
    if signal in {"BULLISH", "STRONGLY_BULLISH"}:
        return "BUY_CE"
    return "WAIT"


@dataclass(frozen=True, slots=True)
class StrikePcrRecommendationObservation:
    underlying: str
    expiry: str
    strike: float
    strike_pcr: float | None
    strike_signal: str
    overall_pcr: float | None
    overall_signal: str
    recommendation: str
    observed_at: datetime
    symbol: str | None
    entry_ask: float | None
    executable_bid: float | None
    last_price: float | None
    entry_delta: float | None = None
    entry_iv: float | None = None
    entry_contract_vwap: float | None = None
    authority: str = "OBSERVATIONAL_ONLY"


def build_strike_pcr_recommendations(
    *,
    projection: Mapping[str, object],
    option_rows: Sequence[Mapping[str, object]],
) -> tuple[StrikePcrRecommendationObservation, ...]:
    """Build independent per-strike PCR recommendations and quote evidence."""
    panel = projection.get("current_panel")
    if not isinstance(panel, Mapping):
        return ()
    aggregate = panel.get("aggregate")
    aggregate = aggregate if isinstance(aggregate, Mapping) else {}
    overall_pcr = _number(aggregate.get("pcr"))
    overall_signal = _signal(overall_pcr)
    expiry = str(panel.get("expiry") or "")
    underlying = str(projection.get("underlying") or "NIFTY 50")
    source = projection.get("source_timestamp")
    if not isinstance(source, str):
        return ()
    try:
        observed_at = datetime.fromisoformat(source.replace("Z", "+00:00"))
    except ValueError:
        return ()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return ()
    quotes = {
        (float(row["strike"]), str(row.get("option_type") or "").upper()): row
        for row in option_rows
        if isinstance(row.get("strike"), (int, float))
        and str(row.get("expiry") or "") == expiry
        and str(row.get("option_type") or "").upper() in {"CE", "PE"}
    }
    result: list[StrikePcrRecommendationObservation] = []
    rows = panel.get("rows")
    for row in rows if isinstance(rows, (list, tuple)) else ():
        if not isinstance(row, Mapping) or str(row.get("position") or "").upper() == "TOTAL":
            continue
        strike = _number(row.get("strike"))
        if strike is None:
            continue
        strike_pcr = _pcr(row.get("pe_current_oi"), row.get("ce_current_oi"))
        strike_signal = _signal(strike_pcr)
        recommendation = _recommendation(strike_signal)
        side = "CE" if recommendation == "BUY_CE" else "PE" if recommendation == "BUY_PE" else None
        quote = quotes.get((strike, side), {}) if side else {}
        result.append(StrikePcrRecommendationObservation(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            strike_pcr=strike_pcr,
            strike_signal=strike_signal,
            overall_pcr=overall_pcr,
            overall_signal=overall_signal,
            recommendation=recommendation,
            observed_at=observed_at,
            symbol=(str(quote.get("tradingsymbol")) if quote.get("tradingsymbol") else None),
            entry_ask=_number(quote.get("ask")),
            executable_bid=_number(quote.get("bid")),
            last_price=_number(quote.get("current_price")),
            entry_delta=_number(quote.get("delta")),
            entry_iv=_number(quote.get("iv")),
            entry_contract_vwap=_number(quote.get("vwap")),
        ))
    return tuple(result)


__all__ = [
    "StrikePcrRecommendationObservation",
    "build_strike_pcr_recommendations",
]
