from __future__ import annotations

from typing import Mapping


OBSERVATIONAL_AUTHORITY = "OBSERVATIONAL ONLY"
MODEL_VERSION = "RBV2-OUTLOOK-V1"


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _option_side(order: Mapping[str, object]) -> str:
    side = str(order.get("option_type") or order.get("side") or "").upper()
    if side in {"CALL", "CE"}:
        return "CE"
    if side in {"PUT", "PE"}:
        return "PE"
    return "UNKNOWN"


def build_trade_outlook(
    order: Mapping[str, object],
    card: Mapping[str, object],
) -> dict[str, object]:
    """Classify an active trade from persisted evidence only.

    This helper is intentionally observational. It never calls a provider and its
    output must not be used to open, close, resize, or modify protection on a trade.
    """
    side = _option_side(order)
    status = str(order.get("status") or "OPEN").upper()
    freshness = str((card.get("freshness") or {}).get("status") or "UNAVAILABLE").upper()
    pnl = _number(card.get("unrealized_pnl"))
    entry_price = _number(card.get("entry_price"))
    current_price = _number(card.get("current_price"))
    delta_change = _number(card.get("delta_change"))
    pcr_change = _number(card.get("pcr_change"))
    spread_pct = _number(card.get("spread_pct"))

    supportive: list[str] = []
    conflicting: list[str] = []
    observations: list[str] = []
    score = 0
    available = 0

    if status == "CLOSED":
        return {
            "recommendation": "CLOSED",
            "outlook": "TRADE COMPLETE",
            "trade_health": "CLOSED",
            "underlying_bias": "NOT APPLICABLE",
            "confidence_pct": 100,
            "supportive_evidence": (),
            "conflicting_evidence": (),
            "observations": (),
            "score": 0,
            "data_quality": freshness,
            "authority": OBSERVATIONAL_AUTHORITY,
            "model_version": MODEL_VERSION,
        }

    if freshness == "UNAVAILABLE":
        return {
            "recommendation": "MONITOR",
            "outlook": "DATA UNAVAILABLE",
            "trade_health": "UNKNOWN",
            "underlying_bias": "UNKNOWN",
            "confidence_pct": 0,
            "supportive_evidence": (),
            "conflicting_evidence": ("No persisted telemetry snapshot is available.",),
            "observations": (),
            "score": 0,
            "data_quality": freshness,
            "authority": OBSERVATIONAL_AUTHORITY,
            "model_version": MODEL_VERSION,
        }

    if pnl is not None:
        available += 1
        if pnl > 0:
            score += 2
            supportive.append("Option premium is above the paper entry value.")
        elif pnl < 0:
            score -= 2
            conflicting.append("Option premium is below the paper entry value.")
        else:
            observations.append("Option premium is near the paper entry value.")
    elif entry_price not in (None, 0.0) and current_price is not None:
        available += 1
        if current_price > entry_price:
            score += 2
            supportive.append("Option premium increased from entry.")
        elif current_price < entry_price:
            score -= 2
            conflicting.append("Option premium decreased from entry.")

    if delta_change is not None and side in {"CE", "PE"}:
        available += 1
        strengthening = delta_change >= 0.03 if side == "CE" else delta_change <= -0.03
        weakening = delta_change <= -0.03 if side == "CE" else delta_change >= 0.03
        if strengthening:
            score += 2
            supportive.append(f"{side} Delta sensitivity strengthened from entry.")
        elif weakening:
            score -= 2
            conflicting.append(f"{side} Delta sensitivity weakened from entry.")
        else:
            observations.append(f"{side} Delta is broadly stable from entry.")

    if spread_pct is not None:
        available += 1
        if spread_pct <= 1.0:
            score += 1
            supportive.append("Bid/ask spread remains controlled.")
        elif spread_pct > 2.0:
            score -= 1
            conflicting.append("Bid/ask spread is wide.")
        else:
            observations.append("Bid/ask spread is moderate.")

    if pcr_change is not None:
        available += 1
        if pcr_change > 0.05:
            observations.append("Put OI relative to Call OI increased at the selected strike.")
        elif pcr_change < -0.05:
            observations.append("Call OI relative to Put OI increased at the selected strike.")
        else:
            observations.append("Selected-strike PCR is broadly stable.")

    if freshness == "STALE":
        score -= 2
        conflicting.append("Latest persisted telemetry is stale.")

    if available == 0:
        recommendation = "MONITOR"
        outlook = "INSUFFICIENT EVIDENCE"
        health = "UNKNOWN"
        confidence = 0
    elif score >= 4:
        recommendation = f"HOLD {side}" if side in {"CE", "PE"} else "MONITOR"
        outlook = f"{side} MOMENTUM STRENGTHENING" if side in {"CE", "PE"} else "FAVORABLE"
        health = "FAVORABLE"
        confidence = min(90, 55 + 7 * score)
    elif score >= 2:
        recommendation = f"HOLD {side}" if side in {"CE", "PE"} else "MONITOR"
        outlook = f"{side} MOMENTUM SUPPORTIVE" if side in {"CE", "PE"} else "SUPPORTIVE"
        health = "FAVORABLE"
        confidence = min(80, 50 + 6 * score)
    elif score >= 0:
        recommendation = "MONITOR"
        outlook = "MIXED / NEUTRAL"
        health = "NEUTRAL"
        confidence = min(65, 40 + 5 * available)
    else:
        recommendation = "MOMENTUM WEAKENING"
        outlook = f"{side} MOMENTUM WEAKENING" if side in {"CE", "PE"} else "WEAKENING"
        health = "WEAKENING"
        confidence = min(80, 50 + 6 * abs(score))

    bias = "BULLISH CONTINUATION" if side == "CE" else "BEARISH CONTINUATION" if side == "PE" else "UNKNOWN"
    return {
        "recommendation": recommendation,
        "outlook": outlook,
        "trade_health": health,
        "underlying_bias": bias,
        "confidence_pct": int(confidence),
        "supportive_evidence": tuple(supportive),
        "conflicting_evidence": tuple(conflicting),
        "observations": tuple(observations),
        "score": score,
        "data_quality": freshness,
        "authority": OBSERVATIONAL_AUTHORITY,
        "model_version": MODEL_VERSION,
    }


__all__ = ["build_trade_outlook"]
