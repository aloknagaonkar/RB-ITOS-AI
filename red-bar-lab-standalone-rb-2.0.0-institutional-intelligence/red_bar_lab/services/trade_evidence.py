from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TradeEvidenceRecommendation:
    direction: str
    suggested_option: str
    suggested_contract: str
    candidate_score: float | None
    grade: str
    action: str
    summary: str
    positive_evidence: tuple[str, ...]
    caution_evidence: tuple[str, ...]
    blocking_evidence: tuple[str, ...]
    authority: str = "OBSERVATIONAL_ONLY"


_SUPPORTIVE_FUTURES = {
    "BULLISH": {"LONG_BUILDUP", "SHORT_COVERING"},
    "BEARISH": {"SHORT_BUILDUP", "LONG_UNWINDING"},
}
_CONTRARY_FUTURES = {
    "BULLISH": {"SHORT_BUILDUP", "LONG_UNWINDING"},
    "BEARISH": {"LONG_BUILDUP", "SHORT_COVERING"},
}


def _text(value: object, default: str = "UNAVAILABLE") -> str:
    return str(value or default).strip().upper()


def build_trade_evidence_recommendation(
    *,
    readiness: Mapping[str, object] | None,
    signal_diagnostic: Mapping[str, object] | None,
    futures_snapshot: Mapping[str, object] | None,
    one_minute_observation: Mapping[str, object] | None = None,
) -> TradeEvidenceRecommendation:
    """Grade a proposed Red Bar V2 trade without affecting execution."""

    ready = dict(readiness or {})
    signal = dict(signal_diagnostic or {})
    futures = dict(futures_snapshot or {})

    direction = _text(signal.get("direction"), "NO_SIGNAL")
    option = "CE" if direction == "BULLISH" else "PE" if direction == "BEARISH" else "—"
    contract = str(signal.get("best_candidate") or "Awaiting candidate")
    score_value = signal.get("best_score")
    score = float(score_value) if score_value not in (None, "") else None

    blocking = tuple(str(item) for item in (ready.get("blocking_reasons") or ()))
    advisory = tuple(str(item) for item in (ready.get("advisory_reasons") or ()))
    execution = tuple(str(item) for item in (ready.get("execution_reasons") or ()))
    overall = _text(ready.get("overall_status"), "UNAVAILABLE")
    market_hours = _text(ready.get("market_hours_status"), "UNAVAILABLE")
    option_quote = _text(ready.get("option_quote_status"), "UNAVAILABLE")
    v2_alignment = _text(ready.get("v2_alignment_status"), "UNAVAILABLE")
    futures_state = _text(futures.get("positioning_state"), "NEUTRAL")
    futures_strength = _text(futures.get("strength") or ready.get("futures_strength"), "UNAVAILABLE")

    positives: list[str] = []
    cautions: list[str] = list(advisory) + list(execution)

    if direction in {"BULLISH", "BEARISH"}:
        positives.append(f"RED_BAR_V2_{direction}")
    if option_quote == "READY":
        positives.append("OPTION_QUOTE_READY")
    if v2_alignment in {"ALIGNED", "READY"}:
        positives.append("V2_ALIGNMENT_ALIGNED")
    if futures_state in _SUPPORTIVE_FUTURES.get(direction, set()):
        positives.append(f"FUTURES_{futures_state}_SUPPORTIVE")
    elif futures_state in _CONTRARY_FUTURES.get(direction, set()):
        cautions.append(f"FUTURES_{futures_state}_CONTRADICTS_{direction}")

    if isinstance(one_minute_observation, Mapping):
        one_minute_direction = _text(
            one_minute_observation.get("research_direction")
            or one_minute_observation.get("overall_direction"),
            "UNAVAILABLE",
        )
        if direction in {"BULLISH", "BEARISH"} and one_minute_direction == direction:
            positives.append(f"ONE_MIN_PCR_{one_minute_direction}_SUPPORTIVE")
        elif direction in {"BULLISH", "BEARISH"} and one_minute_direction in {
            "BULLISH",
            "BEARISH",
        } and one_minute_direction != direction:
            cautions.append(f"ONE_MIN_PCR_{one_minute_direction}_CONTRADICTS_{direction}")

    if direction == "NO_SIGNAL":
        grade = "NO_SIGNAL"
        action = "WAIT FOR RED BAR V2 SIGNAL"
        summary = "No current bullish or bearish Red Bar V2 signal is available."
    elif blocking:
        grade = "BLOCKED"
        action = "DO NOT TRADE"
        summary = "Critical market evidence is unavailable or unusable."
    elif futures_state in _CONTRARY_FUTURES.get(direction, set()) and futures_strength == "STRONG":
        grade = "CONFLICTED"
        action = "WAIT — FUTURES CONTRADICT SIGNAL"
        summary = "Red Bar V2 direction conflicts with strong futures positioning."
    elif market_hours not in {"OPEN", "ENTRY_OPEN", "READY"}:
        grade = "CAUTIOUS"
        action = "WAIT FOR ENTRY HOURS"
        summary = "The setup is observationally visible, but entry hours are closed."
    elif overall == "READY" and futures_strength == "STRONG" and option_quote == "READY":
        grade = "STRONG"
        action = "PAPER TRADE ELIGIBLE"
        summary = "Red Bar V2 and supporting market evidence are strongly aligned."
    elif overall in {"READY", "DEGRADED"} and futures_strength in {"STRONG", "MODERATE"}:
        grade = "MODERATE"
        action = "TRADE WITH CAUTION"
        summary = "Most evidence is aligned, with limited advisory conditions."
    else:
        grade = "CAUTIOUS"
        action = "WAIT FOR CONFIRMATION"
        summary = "The signal exists, but supporting evidence is weak or incomplete."

    return TradeEvidenceRecommendation(
        direction=direction,
        suggested_option=option,
        suggested_contract=contract,
        candidate_score=score,
        grade=grade,
        action=action,
        summary=summary,
        positive_evidence=tuple(dict.fromkeys(positives)),
        caution_evidence=tuple(dict.fromkeys(cautions)),
        blocking_evidence=blocking,
    )
