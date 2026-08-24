from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence


_DIRECTIONS = {"BULLISH", "BEARISH"}
_BULLISH_FUTURES = {"LONG_BUILDUP", "SHORT_COVERING"}
_BEARISH_FUTURES = {"SHORT_BUILDUP", "LONG_UNWINDING"}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _text(value: object, default: str = "UNAVAILABLE") -> str:
    text = str(value or "").strip().upper()
    return text or default


@dataclass(frozen=True, slots=True)
class DirectionComponent:
    """One immutable, explainable vote in market-direction research."""

    name: str
    maximum_score: float
    bullish_score: float
    bearish_score: float
    conclusion: str
    quality: str
    details: tuple[dict[str, object], ...]

    @property
    def winning_score(self) -> float:
        return max(self.bullish_score, self.bearish_score)


@dataclass(frozen=True, slots=True)
class MarketDirectionValidation:
    """Read-only composite direction result with no execution authority."""

    conclusion: str
    bullish_score: float
    bearish_score: float
    score_gap: float
    quality: str
    reason: str
    components: tuple[DirectionComponent, ...]
    authority: str = "OBSERVATIONAL_ONLY"


def _structure_component(bundle: Mapping[str, object]) -> DirectionComponent:
    direction = _text(bundle.get("underlying_direction") or bundle.get("observed_direction"))
    state = _text(bundle.get("acceptance_state") or bundle.get("structural_state"))
    early_direction = _text(bundle.get("early_1m_direction"))
    early_state = _text(bundle.get("early_1m_state"))
    readiness = _text(bundle.get("evidence_readiness"))
    bullish = bearish = 0.0
    if early_direction in _DIRECTIONS:
        if early_direction == "BULLISH":
            bullish += 15.0
        else:
            bearish += 15.0
    if direction in _DIRECTIONS:
        points = 25.0 if state == "HOLD_CONFIRMED" else 15.0
        if direction == "BULLISH":
            bullish += points
        else:
            bearish += points
    conclusion = (
        direction
        if direction in _DIRECTIONS and state == "HOLD_CONFIRMED"
        else f"{direction}_EARLY"
        if direction in _DIRECTIONS
        else "SIDEWAYS"
        if direction == "NEUTRAL"
        else "UNAVAILABLE"
    )
    quality = "READY" if readiness == "READY" and direction in _DIRECTIONS else "PARTIAL" if bundle else "UNAVAILABLE"
    return DirectionComponent(
        "Completed NIFTY 1m/5m structure", 40.0, min(bullish, 40.0), min(bearish, 40.0), conclusion, quality,
        (
            {"Check": "Completed 1m early state", "Observed": early_state, "Direction": early_direction, "Rule": "Completed 1m break; early evidence only"},
            {"Check": "Completed 5m structure", "Observed": state, "Direction": direction, "Rule": "Completed breakout plus hold owns confirmation"},
            {"Check": "Evidence readiness", "Observed": readiness, "Direction": "NEUTRAL", "Rule": "Persisted evidence must be ready"},
            {"Check": "Underlying evidence time", "Observed": bundle.get("underlying_timestamp"), "Direction": "NEUTRAL", "Rule": "Completed-candle exchange time"},
        ),
    )


def _buildup_direction(side: str, premium_change: float | None, oi_change: float | None) -> tuple[str, str]:
    if premium_change is None or oi_change is None or premium_change == 0 or oi_change == 0:
        return "UNAVAILABLE", "Insufficient non-zero premium/OI movement"
    if premium_change > 0 and oi_change > 0:
        state = "LONG_BUILDUP"
    elif premium_change < 0 and oi_change > 0:
        state = "SHORT_BUILDUP"
    elif premium_change > 0:
        state = "SHORT_COVERING"
    else:
        state = "LONG_UNWINDING"
    bullish = (side == "CE" and state in {"LONG_BUILDUP", "SHORT_COVERING"}) or (side == "PE" and state in {"SHORT_BUILDUP", "LONG_UNWINDING"})
    return ("BULLISH" if bullish else "BEARISH"), state


def _option_component(bundle: Mapping[str, object], rows: Sequence[Mapping[str, object]]) -> DirectionComponent:
    bullish = bearish = 0.0
    pressure = _text(bundle.get("option_direction"))
    if pressure == "BULLISH":
        bullish += 10.0
    elif pressure == "BEARISH":
        bearish += 10.0
    detail_rows: list[dict[str, object]] = []
    buildup_votes = {"BULLISH": 0.0, "BEARISH": 0.0}
    vwap_votes = {"BULLISH": 0.0, "BEARISH": 0.0}
    usable = 0
    for row in rows:
        side = _text(row.get("option_type"))
        premium_change = _number(
            row.get("premium_change_from_previous_refresh_pct")
        )
        oi_change = _number(row.get("oi_change_from_previous_refresh"))
        price_vs_vwap = _number(row.get("price_vs_vwap_pct"))
        direction, buildup = _buildup_direction(side, premium_change, oi_change)
        if direction in _DIRECTIONS:
            buildup_votes[direction] += 1.0
            usable += 1
        if price_vs_vwap is not None:
            vwap_direction = "BULLISH" if (side == "CE" and price_vs_vwap > 0) or (side == "PE" and price_vs_vwap < 0) else "BEARISH"
            vwap_votes[vwap_direction] += 1.0
        else:
            vwap_direction = "UNAVAILABLE"
        detail_rows.append({
            "Strike": row.get("strike"), "Side": side, "LTP": row.get("current_price"), "VWAP": row.get("vwap"),
            "LTP vs VWAP %": price_vs_vwap, "Premium change %": premium_change, "OI change": oi_change,
            "Volume change %": row.get("volume_change_from_previous_refresh_pct"),
            "Buildup": buildup, "Directional vote": direction,
            "Current snapshot": row.get("observed_at"),
            "Previous snapshot": row.get("previous_observed_at"),
        })
    vote_total = buildup_votes["BULLISH"] + buildup_votes["BEARISH"]
    if vote_total:
        bullish += 10.0 * buildup_votes["BULLISH"] / vote_total
        bearish += 10.0 * buildup_votes["BEARISH"] / vote_total
    vwap_total = vwap_votes["BULLISH"] + vwap_votes["BEARISH"]
    if vwap_total:
        bullish += 5.0 * vwap_votes["BULLISH"] / vwap_total
        bearish += 5.0 * vwap_votes["BEARISH"] / vwap_total
    conclusion = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "CONFLICT" if rows else "UNAVAILABLE"
    quality = "READY" if rows and usable else "PARTIAL" if rows else "UNAVAILABLE"
    return DirectionComponent("Option buildup and VWAP", 25.0, bullish, bearish, conclusion, quality, tuple(detail_rows))


def _futures_component(futures: Mapping[str, object], bundle: Mapping[str, object]) -> DirectionComponent:
    bullish = bearish = 0.0
    state = _text(futures.get("positioning_state"))
    if state in _BULLISH_FUTURES:
        bullish += 8.0
        state_direction = "BULLISH"
    elif state in _BEARISH_FUTURES:
        bearish += 8.0
        state_direction = "BEARISH"
    else:
        state_direction = "NEUTRAL"
    vwap_direction = _text(bundle.get("futures_vwap_direction"))
    if vwap_direction not in _DIRECTIONS:
        acceptance = _text(futures.get("futures_vwap_acceptance"))
        vwap_direction = "BULLISH" if "ABOVE" in acceptance else "BEARISH" if "BELOW" in acceptance else "UNAVAILABLE"
    if vwap_direction == "BULLISH":
        bullish += 7.0
    elif vwap_direction == "BEARISH":
        bearish += 7.0
    relative_volume = _number(futures.get("relative_volume"))
    if relative_volume is not None and relative_volume >= 1.2 and state_direction in _DIRECTIONS:
        if state_direction == "BULLISH":
            bullish += 3.0
        else:
            bearish += 3.0
    spot_direction = _text(bundle.get("underlying_direction") or bundle.get("observed_direction"))
    if spot_direction in _DIRECTIONS and spot_direction == state_direction:
        if spot_direction == "BULLISH":
            bullish += 2.0
        else:
            bearish += 2.0
    conclusion = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "CONFLICT" if futures else "UNAVAILABLE"
    quality = "READY" if _text(futures.get("readiness_status")) == "READY" else "PARTIAL" if futures else "UNAVAILABLE"
    return DirectionComponent(
        "Futures VWAP, volume and OI", 20.0, bullish, bearish, conclusion, quality,
        (
            {"Check": "Price/OI positioning", "Observed": state, "Direction": state_direction, "Rule": "Price and OI buildup classification"},
            {"Check": "Futures vs VWAP", "Observed": futures.get("futures_vwap_acceptance"), "Direction": vwap_direction, "Rule": "Completed futures price relative to VWAP"},
            {"Check": "Relative volume", "Observed": relative_volume, "Direction": state_direction if relative_volume is not None and relative_volume >= 1.2 else "WEAK", "Rule": "At least 1.20 for participation points"},
            {"Check": "Futures OI change %", "Observed": futures.get("oi_change_pct"), "Direction": state_direction, "Rule": "Used by persisted positioning classification"},
            {"Check": "Futures candle time", "Observed": futures.get("bar_close_timestamp") or futures.get("latest_timestamp"), "Direction": "NEUTRAL", "Rule": "Completed futures candle time"},
        ),
    )


def _pcr_component(projection: Mapping[str, object]) -> DirectionComponent:
    panel = projection.get("current_panel")
    aggregate = panel.get("aggregate") if isinstance(panel, Mapping) else None
    aggregate = aggregate if isinstance(aggregate, Mapping) else {}
    evidence = aggregate.get("direction_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    direction = _text(evidence.get("direction"))
    change = _number(aggregate.get("absolute_change"))
    slope = _number(aggregate.get("slope_per_minute"))
    persistence = _text(aggregate.get("persistence_state"))
    consecutive = int(_number(aggregate.get("consecutive_count")) or 0)
    bullish = bearish = 0.0
    if direction == "BULLISH":
        bullish += 6.0
    elif direction == "BEARISH":
        bearish += 6.0
    if change is not None:
        if change > 0:
            bullish += 4.0
        elif change < 0:
            bearish += 4.0
    if slope is not None:
        if slope > 0:
            bullish += 2.0
        elif slope < 0:
            bearish += 2.0
    if consecutive >= 3 and direction in _DIRECTIONS:
        if direction == "BULLISH":
            bullish += 3.0
        else:
            bearish += 3.0
    conclusion = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "NEUTRAL" if aggregate else "UNAVAILABLE"
    quality_state = _text((projection.get("quality") or {}).get("state") if isinstance(projection.get("quality"), Mapping) else None)
    quality = "READY" if quality_state == "READY" else "PARTIAL" if aggregate else "UNAVAILABLE"
    return DirectionComponent(
        "PCR level, movement and persistence", 15.0, bullish, bearish, conclusion, quality,
        (
            {"Check": "Current PCR", "Observed": aggregate.get("pcr"), "Direction": direction, "Rule": "Configured PCR regime"},
            {"Check": "Change from previous observation", "Observed": change, "Direction": "BULLISH" if change and change > 0 else "BEARISH" if change and change < 0 else "NEUTRAL", "Rule": "PCR movement"},
            {"Check": "Slope per minute", "Observed": slope, "Direction": "BULLISH" if slope and slope > 0 else "BEARISH" if slope and slope < 0 else "NEUTRAL", "Rule": "Short-term PCR slope"},
            {"Check": "Persistence", "Observed": f"{persistence}; {consecutive} observations", "Direction": direction, "Rule": "At least three aligned observations for persistence points"},
            {"Check": "PCR source time", "Observed": projection.get("source_timestamp"), "Direction": "NEUTRAL", "Rule": "Persisted Market Trend Research source time"},
        ),
    )


def build_market_direction_validation(
    *,
    authoritative_bundle: Mapping[str, object] | None,
    option_rows: Sequence[Mapping[str, object]],
    futures_snapshot: Mapping[str, object] | None,
    pcr_projection: Mapping[str, object] | None,
) -> MarketDirectionValidation:
    """Combine persisted research evidence without performing provider I/O."""

    bundle = authoritative_bundle or {}
    components = (
        _structure_component(bundle),
        _option_component(bundle, option_rows),
        _futures_component(futures_snapshot or {}, bundle),
        _pcr_component(pcr_projection or {}),
    )
    bullish = sum(item.bullish_score for item in components)
    bearish = sum(item.bearish_score for item in components)
    gap = abs(bullish - bearish)
    winner = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "CONFLICT"
    structure = components[0]
    derivatives_agree = any(item.conclusion == winner for item in components[1:3])
    missing = [item.name for item in components if item.quality == "UNAVAILABLE"]
    degraded = [item.name for item in components if item.quality != "READY"]
    if missing:
        conclusion, quality = "UNAVAILABLE", "INCOMPLETE"
        reason = "Mandatory evidence unavailable: " + ", ".join(missing)
    elif degraded:
        conclusion, quality = "UNAVAILABLE", "DEGRADED"
        reason = "Mandatory evidence is not ready: " + ", ".join(degraded)
    elif structure.conclusion == "SIDEWAYS":
        conclusion, quality, reason = "SIDEWAYS", "READY", "No completed directional NIFTY structure is confirmed."
    elif not structure.conclusion.startswith(winner):
        conclusion, quality, reason = "CONFLICT", "READY", "NIFTY structure disagrees with the winning composite evidence."
    elif max(bullish, bearish) < 65.0 or gap < 15.0 or not derivatives_agree:
        conclusion, quality, reason = "CONFLICT", "READY", "Score, separation, or derivatives-alignment threshold is not met."
    else:
        conclusion, quality = winner, "READY"
        reason = f"{winner} structure is supported by derivatives evidence."
    return MarketDirectionValidation(conclusion, bullish, bearish, gap, quality, reason, components)


__all__ = ["DirectionComponent", "MarketDirectionValidation", "build_market_direction_validation"]
