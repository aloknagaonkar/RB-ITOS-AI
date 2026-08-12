from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_COMPONENTS = (
    ("Spread", "Spread Score", 15.0),
    ("Liquidity", "Liquidity", 20.0),
    ("Volume", "Volume Score", 15.0),
    ("Open Interest", "OI Score", 10.0),
    ("VWAP", "VWAP Score", 10.0),
    ("EMA9 / EMA21", "EMA Score", 10.0),
    ("Momentum", "Momentum", 10.0),
)


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class CandidateInspection:
    rank: int
    symbol: str
    score: float
    health_score: float
    health_band: str
    execution_candidate: bool
    reasons: tuple[str, ...]
    weaknesses: tuple[str, ...]
    comparison_to_best: tuple[str, ...]
    score_breakdown: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "score": self.score,
            "health_score": self.health_score,
            "health_band": self.health_band,
            "execution_candidate": self.execution_candidate,
            "reasons": list(self.reasons),
            "weaknesses": list(self.weaknesses),
            "comparison_to_best": list(self.comparison_to_best),
            "score_breakdown": list(self.score_breakdown),
        }


def inspect_candidate(
    selected: dict[str, object],
    best: dict[str, object],
) -> CandidateInspection:
    rank = int(selected.get("Rank") or 0)
    symbol = str(selected.get("Option") or "")
    score = _num(selected.get("Score"))

    breakdown = []
    normalized_points = []
    reasons = []
    weaknesses = []

    for label, key, maximum in _COMPONENTS:
        value = _num(selected.get(key))
        ratio = value / maximum if maximum else 0.0
        normalized_points.append(max(0.0, min(1.0, ratio)))
        breakdown.append(
            {
                "Evidence": label,
                "Score": round(value, 2),
                "Maximum": maximum,
                "Percent": round(max(0.0, min(100.0, ratio * 100.0)), 1),
            }
        )
        if ratio >= 0.80:
            reasons.append(f"{label} is strong ({value:.1f}/{maximum:.0f}).")
        elif ratio < 0.50:
            weaknesses.append(
                f"{label} is weak ({value:.1f}/{maximum:.0f})."
            )

    # Greeks stay observational: they can contribute to health, not ranking.
    delta = abs(_num(selected.get("Delta")))
    gamma = _num(selected.get("Gamma"))
    iv = _num(selected.get("IV"))
    greek_quality = 0.0
    greek_checks = 0
    if delta > 0:
        greek_checks += 1
        greek_quality += 1.0 if 0.30 <= delta <= 0.70 else 0.5
    if gamma:
        greek_checks += 1
        greek_quality += 1.0 if gamma > 0 else 0.0
    if iv:
        greek_checks += 1
        greek_quality += 1.0 if 5.0 <= iv <= 60.0 else 0.5

    rule_quality = (
        sum(normalized_points) / len(normalized_points)
        if normalized_points else 0.0
    )
    if greek_checks:
        greek_quality /= greek_checks
        health = rule_quality * 85.0 + greek_quality * 15.0
    else:
        health = rule_quality * 100.0

    health = max(0.0, min(100.0, health))
    if health >= 85:
        band = "EXCELLENT"
    elif health >= 75:
        band = "GOOD"
    elif health >= 60:
        band = "WATCH"
    else:
        band = "WEAK"

    comparison = []
    if rank == 1:
        comparison.append("Highest-ranked candidate in the current ranking.")
        comparison.append(
            "This remains the only automatic paper execution candidate."
        )
    else:
        best_score = _num(best.get("Score"))
        gap = best_score - score
        comparison.append(
            f"Rank #{rank} trails Rank #1 by {gap:.2f} score points."
        )
        for label, key, maximum in _COMPONENTS:
            selected_value = _num(selected.get(key))
            best_value = _num(best.get(key))
            diff = selected_value - best_value
            if diff > 0.01:
                comparison.append(
                    f"Better {label}: {selected_value:.1f} vs "
                    f"{best_value:.1f}."
                )
            elif diff < -0.01:
                comparison.append(
                    f"Lower {label}: {selected_value:.1f} vs "
                    f"{best_value:.1f}."
                )
        comparison.append(
            "Inspection only: selecting this row does not alter execution."
        )

    return CandidateInspection(
        rank=rank,
        symbol=symbol,
        score=round(score, 2),
        health_score=round(health, 1),
        health_band=band,
        execution_candidate=(rank == 1),
        reasons=tuple(reasons),
        weaknesses=tuple(weaknesses),
        comparison_to_best=tuple(comparison),
        score_breakdown=tuple(breakdown),
    )
