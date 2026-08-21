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
    participation: Mapping[str, object] | None = None,
) -> IndependentMarketRecommendation:
    """Create a read-only CE/PE market view without using Red Bar V2 direction.

    When the six-strike participation snapshot is available, it becomes the
    direct option-market directional view. Futures remains independent
    confirmation/contradiction evidence. Without that snapshot, the existing
    futures-led behavior is preserved for compatibility.
    """

    ready = dict(readiness or {})
    futures = dict(futures_snapshot or {})
    options = dict(option_context or {})
    participation_view = dict(participation or {})

    state = _text(futures.get("positioning_state"), "NEUTRAL")
    strength = _text(futures.get("strength") or ready.get("futures_strength"), "UNAVAILABLE")
    blocking = tuple(str(item) for item in (ready.get("blocking_reasons") or ()))
    advisory = tuple(str(item) for item in (ready.get("advisory_reasons") or ()))
    execution = tuple(str(item) for item in (ready.get("execution_reasons") or ()))
    market_hours = _text(ready.get("market_hours_status"), "UNAVAILABLE")
    overall = _text(ready.get("overall_status"), "UNAVAILABLE")

    participation_side = _text(participation_view.get("recommended_side"), "UNAVAILABLE")
    participation_grade = _text(participation_view.get("grade"), "UNAVAILABLE")
    ce_score = _number(participation_view.get("ce_score"))
    pe_score = _number(participation_view.get("pe_score"))
    has_participation = participation_side in {"CE", "PE", "WAIT"} and ce_score is not None and pe_score is not None

    if has_participation and participation_side == "CE":
        direction, option = "BULLISH", "CE"
    elif has_participation and participation_side == "PE":
        direction, option = "BEARISH", "PE"
    elif has_participation and participation_side == "WAIT":
        direction, option = "NEUTRAL", "—"
    elif state in _BULLISH_STATES:
        direction, option = "BULLISH", "CE"
    elif state in _BEARISH_STATES:
        direction, option = "BEARISH", "PE"
    else:
        direction, option = "NEUTRAL", "—"

    if option == "CE":
        delta = _number(options.get("candidate_delta") or options.get("atm_call_delta"))
    elif option == "PE":
        delta = _number(options.get("candidate_delta") or options.get("atm_put_delta"))
    else:
        delta = None

    delta_source = (
        "EXACT_CANDIDATE" if options.get("candidate_delta") not in (None, "")
        else "LATEST_ATM_SIDE" if delta is not None
        else "UNAVAILABLE"
    )
    pcr = _number(participation_view.get("pcr_oi"))
    if pcr is None:
        pcr = _number(options.get("pcr_oi"))

    positives: list[str] = []
    cautions: list[str] = list(advisory) + list(execution)

    if has_participation:
        positives.append(f"SIX_STRIKE_CE_SCORE_{ce_score:.1f}")
        positives.append(f"SIX_STRIKE_PE_SCORE_{pe_score:.1f}")
        if participation_side in {"CE", "PE"}:
            positives.append(f"SIX_STRIKE_{participation_side}_LEAD")
        else:
            cautions.append("SIX_STRIKE_CONFLICTED")

    futures_side = "CE" if state in _BULLISH_STATES else "PE" if state in _BEARISH_STATES else None
    if futures_side:
        if option in {"CE", "PE"} and futures_side == option:
            positives.append(f"FUTURES_{state}_ALIGNS")
        elif option in {"CE", "PE"} and futures_side != option:
            cautions.append(f"FUTURES_{state}_CONTRADICTS_{option}")
        else:
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
        if has_participation:
            summary = f"Six-strike evidence is not separated enough: CE {ce_score:.1f} vs PE {pe_score:.1f}."
        else:
            summary = "Futures positioning does not provide a directional CE/PE view."
    elif market_hours not in {"OPEN", "ENTRY_OPEN", "READY"}:
        grade, action = "CAUTIOUS", "WAIT FOR ENTRY HOURS"
        summary = f"Independent market view is {direction}, but entry hours are closed."
    elif has_participation:
        futures_conflict = futures_side in {"CE", "PE"} and futures_side != option
        if participation_grade == "STRONG" and not futures_conflict and overall == "READY":
            grade, action = "STRONG", f"BUY {option} — PAPER OBSERVATION"
        elif participation_grade in {"STRONG", "MODERATE"} and not futures_conflict:
            grade, action = "MODERATE", f"CONSIDER {option} WITH CAUTION"
        elif futures_conflict:
            grade, action = "CONFLICTED", "WAIT FOR FUTURES / OPTIONS ALIGNMENT"
        else:
            grade, action = "CAUTIOUS", "WAIT FOR CONFIRMATION"
        summary = (
            f"Six-strike option participation favours {option}: CE {ce_score:.1f} vs PE {pe_score:.1f}. "
            f"Futures state is {state}/{strength}."
        )
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
