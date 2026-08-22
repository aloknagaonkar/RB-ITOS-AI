from __future__ import annotations

"""Truthful public terminology for execution committee outputs.

The historical schema used ``execution_probability_pct`` for an uncalibrated
rule/selection score and ``expected_value_pct`` for a value that currently has
no execution authority.  Those names remain readable as compatibility aliases,
but new services and UI code must consume the explicit fields produced here.
"""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ExecutionScoreContract:
    selection_heuristic_score: float
    research_expectancy_pct: float | None
    research_expectancy_source: str | None
    evidence_sample_size: int
    evidence_ready: bool
    calibrated_probability_pct: float | None = None
    calibration_status: str = "NOT_CALIBRATED"

    def as_dict(self) -> dict[str, object]:
        return {
            "selection_heuristic_score": self.selection_heuristic_score,
            "research_expectancy_pct": self.research_expectancy_pct,
            "research_expectancy_source": self.research_expectancy_source,
            "evidence_sample_size": self.evidence_sample_size,
            "evidence_ready": self.evidence_ready,
            "calibrated_probability_pct": self.calibrated_probability_pct,
            "calibration_status": self.calibration_status,
        }


def _number(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def truthful_execution_scores(
    row: Mapping[str, object],
) -> ExecutionScoreContract:
    """Translate legacy committee fields into a truthful public contract.

    No probability is emitted until an explicitly calibrated field exists.
    ``execution_probability_pct`` is interpreted only as the current selection
    heuristic score.  ``expectancy_pct`` remains research evidence and is not
    renamed to expected value.
    """

    calibrated = row.get("calibrated_probability_pct")
    calibrated_probability = (
        _number(calibrated) if calibrated not in (None, "") else None
    )
    calibration_status = (
        "CALIBRATED"
        if calibrated_probability is not None
        else "NOT_CALIBRATED"
    )
    expectancy = row.get("expectancy_pct")
    return ExecutionScoreContract(
        selection_heuristic_score=round(
            _number(
                row.get("selection_heuristic_score"),
                _number(row.get("execution_probability_pct"), 0.0),
            ),
            2,
        ),
        research_expectancy_pct=(
            round(_number(expectancy), 3)
            if expectancy not in (None, "")
            else None
        ),
        research_expectancy_source=(
            str(row.get("expectancy_source"))
            if row.get("expectancy_source") not in (None, "")
            else None
        ),
        evidence_sample_size=int(row.get("evidence_sample_size") or 0),
        evidence_ready=bool(row.get("evidence_ready")),
        calibrated_probability_pct=calibrated_probability,
        calibration_status=calibration_status,
    )


def with_truthful_execution_scores(
    row: Mapping[str, object],
) -> dict[str, object]:
    result = dict(row)
    result.update(truthful_execution_scores(row).as_dict())
    return result


__all__ = [
    "ExecutionScoreContract",
    "truthful_execution_scores",
    "with_truthful_execution_scores",
]
