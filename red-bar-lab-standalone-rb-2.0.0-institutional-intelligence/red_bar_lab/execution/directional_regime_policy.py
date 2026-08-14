from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectionalRegimePaperPolicy:
    status: str
    action: str
    candidate_score_bonus: float
    block_execution: bool
    reason: str

    def adjusted_score(self, score: float) -> float:
        return round(
            min(100.0, max(0.0, float(score) + self.candidate_score_bonus)),
            2,
        )


def evaluate_directional_regime_policy(
    status: str | None,
    *,
    aligned_bonus: float = 5.0,
) -> DirectionalRegimePaperPolicy:
    normalized = str(status or "UNAVAILABLE").upper().strip()

    if normalized == "ALIGNED":
        return DirectionalRegimePaperPolicy(
            status=normalized,
            action="CONFIDENCE_BONUS",
            candidate_score_bonus=float(aligned_bonus),
            block_execution=False,
            reason="DIRECTIONAL_REGIME_ALIGNED",
        )

    if normalized == "CONFLICT":
        return DirectionalRegimePaperPolicy(
            status=normalized,
            action="HOLD",
            candidate_score_bonus=0.0,
            block_execution=True,
            reason="DIRECTIONAL_REGIME_CONFLICT_HOLD",
        )

    if normalized == "PARTIAL_ALIGNMENT":
        return DirectionalRegimePaperPolicy(
            status=normalized,
            action="CONTINUE",
            candidate_score_bonus=0.0,
            block_execution=False,
            reason="DIRECTIONAL_REGIME_PARTIAL_ALIGNMENT",
        )

    if normalized == "NEUTRAL":
        return DirectionalRegimePaperPolicy(
            status=normalized,
            action="CONTINUE",
            candidate_score_bonus=0.0,
            block_execution=False,
            reason="DIRECTIONAL_REGIME_NEUTRAL",
        )

    return DirectionalRegimePaperPolicy(
        status="UNAVAILABLE",
        action="CONTINUE",
        candidate_score_bonus=0.0,
        block_execution=False,
        reason="DIRECTIONAL_REGIME_UNAVAILABLE_FAIL_OPEN",
    )
