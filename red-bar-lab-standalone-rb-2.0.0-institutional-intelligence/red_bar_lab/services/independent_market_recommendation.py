from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class IndependentMarketRecommendation:
    direction: str
    suggested_option: str
    grade: str
    action: str
    summary: str
    futures_state: str
    futures_strength: str
    option_delta: float | None
    delta_source: str
    pcr_oi: float | None
    positive_evidence: tuple[str, ...]
    caution_evidence: tuple[str, ...]
    blocking_evidence: tuple[str, ...]
    authority: str = "OBSERVATIONAL_ONLY"


_BULLISH_STATES = {"LONG_BUILDUP", "SHORT_COVERING"}
_BEARISH_STATES = {"SHORT_BUILDUP", "LONG_UNWINDING"}


def _text(value: object, default: str = "UNAVAILABLE") -> str:
    return str(value or default).strip().upper()


def _number(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def build_independent_market_recommendation(
    *,
    readiness: Mapping[str, object] | None,
    futures_snapshot: Mapping[str, object] | None,
    option_context: Mapping[str, object] | None = None,
) -> IndependentMarketRecommendation:
    """Create a read-only CE/PE market view without using Red Bar V2 direction."""

    ready = dict(readiness or {})
    futures = dict(futures_snapshot or {})
    options = dict(option_context or {})

    state = _text(futures.get("positioning_state"), "NEUTRAL")
    strength = _text(futures.get("strength") or ready.get("futures_strength"), "UNAVAILABLE")
    blocking = tuple(str(item) for item in (ready.get("blocking_reasons") or ()))
    advisory = tuple(str(item) for item in (ready.get("advisory_reasons") or ()))
    execution = tuple(str(item) for item in (ready.get("execution_reasons") or ()))
    market_hours = _text(ready.get("market_hours_status"), "UNAVAILABLE")
    overall = _text(ready.get("overall_status"), "UNAVAILABLE")

    if state in _BULLISH_STATES:
        direction, option = "BULLISH", "CE"
        delta = _number(options.get("candidate_delta") or options.get("atm_call_delta"))
    elif state in _BEARISH_STATES:
        direction, option = "BEARISH", "PE"
        delta = _number(options.get("candidate_delta") or options.get("atm_put_delta"))
    else:
        direction, option, delta = "NEUTRAL", "—", None

    delta_source = "EXACT_CANDIDATE" if options.get("candidate_delta") not in (None, "") else "LATEST_ATM_SIDE" if delta is not None else "UNAVAILABLE"
    pcr = _number(options.get("pcr_oi"))
    positives: list[str] = []
    cautions: list[str] = list(advisory) + list(execution)

    if direction != "NEUTRAL":
        positives.append(f"FUTURES_{state}")
    if strength == "STRONG":
        positives.append("FUTURES_STRENGTH_STRONG")
    elif strength in {"WEAK", "INSUFFICIENT", "UNAVAILABLE"}:
        cautions.append(f"FUTURES_STRENGTH_{strength}")
    if _text(ready.get("option_chain_status")) == "READY":
        positives.append("OPTION_CHAIN_READY")
    if _text(ready.get("option_quote_status")) == "READY":
        positives.append("OPTION_QUOTE_READY")
    if pcr is not None:
        positives.append("PCR_AVAILABLE")
    if delta is None and option != "—":
        cautions.append("OPTION_DELTA_UNAVAILABLE")

    if blocking:
        grade, action = "BLOCKED", "DO NOT TRADE"
        summary = "Critical market evidence is unavailable or unusable."
    elif direction == "NEUTRAL":
        grade, action = "NO_TRADE", "WAIT FOR DIRECTION"
        summary = "Futures positioning does not provide a directional CE/PE view."
    elif market_hours not in {"OPEN", "ENTRY_OPEN", "READY"}:
        grade, action = "CAUTIOUS", "WAIT FOR ENTRY HOURS"
        summary = f"Independent market view is {direction}, but entry hours are closed."
    elif overall == "READY" and strength == "STRONG" and _text(ready.get("option_quote_status")) == "READY":
        grade, action = "STRONG", f"BUY {option} — PAPER OBSERVATION"
        summary = f"Strong {direction.lower()} futures positioning supports {option}."
    elif overall in {"READY", "DEGRADED"} and strength in {"STRONG", "MODERATE"}:
        grade, action = "MODERATE", f"CONSIDER {option} WITH CAUTION"
        summary = f"The independent market view favours {option}, with advisory conditions."
    else:
        grade, action = "CAUTIOUS", "WAIT FOR CONFIRMATION"
        summary = f"The market leans {direction.lower()}, but confirmation is weak."

    return IndependentMarketRecommendation(
        direction=direction,
        suggested_option=option,
        grade=grade,
        action=action,
        summary=summary,
        futures_state=state,
        futures_strength=strength,
        option_delta=delta,
        delta_source=delta_source,
        pcr_oi=pcr,
        positive_evidence=tuple(dict.fromkeys(positives)),
        caution_evidence=tuple(dict.fromkeys(cautions)),
        blocking_evidence=blocking,
    )
