from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ContractCandidate:
    rank: int
    side: str
    strike: float
    symbol: str
    expiry: str
    current_price: float
    delta: float
    vwap: float
    iv: float
    oi_change_pct: float | None
    premium_change_pct: float | None
    activity: str
    interpretation: str
    bid: float
    ask: float
    spread_pct: float
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class ContractSelection:
    preferred_side: str
    status: str
    reason: str
    candidates: tuple[ContractCandidate, ...]
    authority: str = "OBSERVATIONAL_ONLY"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if isfinite(result) else None


def research_direction(
    *,
    combined_direction: str,
    combined_ready: bool,
    current_direction: str,
    current_ready: bool,
    morning_direction: str,
) -> tuple[str, str]:
    """Resolve the Market Trend Research page without averaging conflict."""
    combined = combined_direction.upper()
    current = current_direction.upper()
    morning = morning_direction.upper()
    if not combined_ready or not current_ready:
        return "INCOMPLETE", "Combined and current PCR must both be fresh"
    if combined not in {"BULLISH", "BEARISH"} or current not in {"BULLISH", "BEARISH"}:
        return "WAIT", "Combined or current PCR is neutral"
    if combined != current:
        return "CONFLICT", "Combined and current PCR disagree"
    if morning in {"BULLISH", "BEARISH"} and morning != combined:
        return "CONFLICT", "Morning fixed-level PCR opposes the current direction"
    return combined, "Combined and current PCR agree; morning evidence does not oppose"


def two_page_preference(
    *,
    trend_direction: str,
    validation_direction: str,
    validation_ready: bool,
) -> tuple[str, str, str]:
    trend = trend_direction.upper()
    validation = validation_direction.upper()
    if trend == "INCOMPLETE" or not validation_ready or validation == "UNAVAILABLE":
        return "NONE", "INCOMPLETE", "Both research pages must be fresh and complete"
    if trend not in {"BULLISH", "BEARISH"} or validation not in {"BULLISH", "BEARISH"}:
        return "NONE", "WAIT", "A page is neutral, sideways or conflicting"
    if trend != validation:
        return "NONE", "CONFLICT", "Market Trend Research and Direction Validation disagree"
    side = "CE" if trend == "BULLISH" else "PE"
    return side, "PASSED", f"Both research pages agree {trend}"


def pcr_research_preference(trend_direction: str) -> tuple[str, str, str]:
    """Map PCR research direction to an observational contract preference."""

    trend = trend_direction.upper()
    if trend == "INCOMPLETE":
        return "NONE", "INCOMPLETE", "PCR research evidence is incomplete"
    if trend not in {"BULLISH", "BEARISH"}:
        return "NONE", "WAIT", f"PCR research direction is {trend}"
    side = "CE" if trend == "BULLISH" else "PE"
    return side, "PASSED", f"PCR research supports {trend}; validation is observational only"


def _activity(premium_change: float, oi_change: float) -> str:
    if premium_change > 0 and oi_change > 0:
        return "LONG_BUILDUP"
    if premium_change < 0 and oi_change > 0:
        return "SHORT_BUILDUP"
    if premium_change > 0 and oi_change < 0:
        return "SHORT_COVERING"
    if premium_change < 0 and oi_change < 0:
        return "LONG_UNWINDING"
    return "NO_MEANINGFUL_CHANGE"


def _activity_interpretation(side: str, activity: str) -> str:
    """Explain premium/OI behaviour for one CE or PE contract."""

    return {
        ("PE", "SHORT_BUILDUP"): "Put writing — bullish/support",
        ("PE", "LONG_BUILDUP"): "Put buying/hedging — bearish concern",
        ("PE", "SHORT_COVERING"): "Put writers exiting — bearish concern",
        ("PE", "LONG_UNWINDING"): "Put long unwinding — bearish",
        ("CE", "SHORT_COVERING"): "Call short covering — bullish",
        ("CE", "SHORT_BUILDUP"): "Call writing — bearish/resistance",
        ("CE", "LONG_BUILDUP"): "Call buying — bullish",
        ("CE", "LONG_UNWINDING"): "Call long unwinding — not bullish confirmation",
    }.get((side, activity), "No meaningful premium/OI interpretation")


def select_best_contracts(
    rows: Sequence[Mapping[str, object]],
    *,
    preferred_side: str,
    selected_expiry: str,
    selected_strikes: frozenset[float],
    limit: int = 4,
) -> tuple[ContractCandidate, ...]:
    """Rank eligible contracts on an already-approved CE or PE side."""
    if preferred_side not in {"CE", "PE"} or limit < 1:
        return ()
    prepared: list[tuple[Mapping[str, object], dict[str, float | str]]] = []
    for row in rows:
        side = str(row.get("option_type") or "").upper()
        strike = _number(row.get("strike"))
        expiry = str(row.get("expiry") or "")
        price = _number(row.get("current_price"))
        delta = _number(row.get("delta"))
        vwap = _number(row.get("vwap"))
        iv = _number(row.get("iv"))
        oi = _number(row.get("oi"))
        volume = _number(row.get("volume"))
        bid = _number(row.get("bid"))
        ask = _number(row.get("ask"))
        premium_change = _number(row.get("premium_change_from_previous_refresh_pct"))
        oi_refresh_change = _number(row.get("oi_change_from_previous_refresh"))
        previous_refresh_oi = _number(row.get("previous_refresh_oi"))
        if (
            side != preferred_side
            or strike is None or strike not in selected_strikes
            or expiry != selected_expiry
            or any(value is None for value in (price, delta, vwap, iv, oi, volume, bid, ask))
            or price <= 0 or vwap <= 0 or iv <= 0 or oi <= 0 or volume <= 0
            or bid <= 0 or ask <= 0 or ask < bid
            or premium_change is None or oi_refresh_change is None
            or previous_refresh_oi is None or previous_refresh_oi <= 0
            or abs(premium_change) < 1.0
            or abs(oi_refresh_change / previous_refresh_oi * 100.0) < 1.0
        ):
            continue
        spread_pct = (ask - bid) / ((ask + bid) / 2.0) * 100.0
        if spread_pct > 5.0 or not 0.20 <= abs(delta) <= 0.85:
            continue
        prepared.append((row, {
            "strike": strike, "price": price, "delta": delta, "vwap": vwap,
            "iv": iv, "oi": oi, "volume": volume, "bid": bid, "ask": ask,
            "premium_change": premium_change, "oi_refresh_change": oi_refresh_change,
            "previous_refresh_oi": previous_refresh_oi,
            "spread_pct": spread_pct,
        }))
    if not prepared:
        return ()
    maximum_oi = max(float(values["oi"]) for _, values in prepared)
    maximum_volume = max(float(values["volume"]) for _, values in prepared)
    ranked: list[tuple[float, Mapping[str, object], dict[str, float | str], str]] = []
    for row, values in prepared:
        activity = _activity(
            float(values["premium_change"]),
            float(values["oi_refresh_change"]),
        )
        activity_score = 30.0 if activity == "LONG_BUILDUP" else 20.0 if activity == "SHORT_COVERING" else 0.0
        vwap_score = 20.0 if float(values["price"]) > float(values["vwap"]) else 0.0
        absolute_delta = abs(float(values["delta"]))
        delta_score = 20.0 if 0.40 <= absolute_delta <= 0.65 else 12.0 if 0.30 <= absolute_delta <= 0.70 else 4.0
        liquidity_score = 7.5 * float(values["oi"]) / maximum_oi + 7.5 * float(values["volume"]) / maximum_volume
        spread = float(values["spread_pct"])
        spread_score = 10.0 if spread <= 1.0 else 7.0 if spread <= 2.0 else 3.0
        iv_score = 5.0 if 5.0 <= float(values["iv"]) <= 40.0 else 2.0
        score = activity_score + vwap_score + delta_score + liquidity_score + spread_score + iv_score
        if score < 50.0:
            continue
        reason = f"{activity}; {'above' if vwap_score else 'below'} VWAP; |Delta| {absolute_delta:.2f}; spread {spread:.2f}%"
        ranked.append((score, row, values, reason))
    ranked.sort(key=lambda item: (-item[0], abs(float(item[2]["delta"]) - (0.5 if preferred_side == "CE" else -0.5)), float(item[2]["spread_pct"])))
    return tuple(
        ContractCandidate(
            rank=index,
            side=preferred_side,
            strike=float(values["strike"]),
            symbol=str(row.get("tradingsymbol") or f"{values['strike']:.0f} {preferred_side}"),
            expiry=selected_expiry,
            current_price=float(values["price"]),
            delta=float(values["delta"]),
            vwap=float(values["vwap"]),
            iv=float(values["iv"]),
            oi_change_pct=_number(row.get("oi_change_pct")),
            premium_change_pct=float(values["premium_change"]),
            activity=_activity(float(values["premium_change"]), float(values["oi_refresh_change"])),
            interpretation=_activity_interpretation(
                preferred_side,
                _activity(
                    float(values["premium_change"]),
                    float(values["oi_refresh_change"]),
                ),
            ),
            bid=float(values["bid"]),
            ask=float(values["ask"]),
            spread_pct=float(values["spread_pct"]),
            score=round(score, 2),
            reason=reason,
        )
        for index, (score, row, values, reason) in enumerate(ranked[:limit], 1)
    )
