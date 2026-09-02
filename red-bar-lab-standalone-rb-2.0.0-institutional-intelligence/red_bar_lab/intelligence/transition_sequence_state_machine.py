from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from uuid import uuid4


BULLISH_STAGES = (
    "BEARISH_STRUCTURE_PRESENT",
    "LOWER_LOW_FAILURE",
    "HIGHER_LOW_FORMED",
    "EMA10_RECLAIMED",
    "EMA10_SLOPE_POSITIVE",
    "LAST_LOWER_HIGH_BROKEN",
    "EMA10_ABOVE_EMA30",
    "BULLISH_CONFIRMED",
)

BEARISH_STAGES = (
    "BULLISH_STRUCTURE_PRESENT",
    "HIGHER_HIGH_FAILURE",
    "LOWER_HIGH_FORMED",
    "EMA10_LOST",
    "EMA10_SLOPE_NEGATIVE",
    "LAST_HIGHER_LOW_BROKEN",
    "EMA10_BELOW_EMA30",
    "BEARISH_CONFIRMED",
)

TERMINAL_STATES = {
    "BULLISH_CONFIRMED",
    "BEARISH_CONFIRMED",
    "INVALIDATED",
    "EXPIRED",
}


@dataclass(frozen=True)
class TransitionSequenceState:
    transition_id: str
    direction: str
    status: str
    stage: str
    stage_index: int
    progress_pct: float
    started_at: str
    updated_at: str
    confirmed_at: str | None
    invalidated_at: str | None
    previous_regime: str
    current_regime: str
    break_level: float | None
    invalidation_level: float | None
    bullish_score: int
    bearish_score: int
    evidence: tuple[str, ...]
    red_bar_support: str
    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "evidence": list(self.evidence),
            "execution_allowed": False,
        }


def _new_id(direction: str, timestamp: str) -> str:
    token = uuid4().hex[:10]
    return f"TR-{direction[:4]}-{timestamp.replace(':','').replace('-','')}-{token}"


def _now_text(snapshot: Mapping[str, object]) -> str:
    return str(snapshot.get("timestamp") or datetime.now().astimezone().isoformat())


def _bullish_stage(snapshot: Mapping[str, object]) -> tuple[str, int]:
    evidence = set(snapshot.get("evidence") or [])
    regime = str(snapshot.get("current_regime") or "")
    previous = str(snapshot.get("previous_regime") or "")

    checks = [
        ("BEARISH_STRUCTURE_PRESENT", previous in {"BEARISH", "TRANSITION_BEARISH"}),
        ("LOWER_LOW_FAILURE", "1M_LOWER_LOW" not in evidence),
        ("HIGHER_LOW_FORMED", "1M_HIGHER_LOW" in evidence),
        ("EMA10_RECLAIMED", "5M_CLOSE_ABOVE_EMA10" in evidence),
        ("EMA10_SLOPE_POSITIVE", "5M_EMA10_RISING" in evidence),
        ("LAST_LOWER_HIGH_BROKEN", "1M_STRUCTURE_BREAKOUT" in evidence),
        ("EMA10_ABOVE_EMA30", "1M_EMA10_ABOVE_EMA30" in evidence),
        ("BULLISH_CONFIRMED", regime == "BULLISH"),
    ]
    completed = [item for item in checks if item[1]]
    if not completed:
        return "TRANSITION_WATCH", 0
    return completed[-1][0], completed[-1][0] == "BULLISH_CONFIRMED" and 7 or checks.index(completed[-1])


def _bearish_stage(snapshot: Mapping[str, object]) -> tuple[str, int]:
    evidence = set(snapshot.get("evidence") or [])
    regime = str(snapshot.get("current_regime") or "")
    previous = str(snapshot.get("previous_regime") or "")

    checks = [
        ("BULLISH_STRUCTURE_PRESENT", previous in {"BULLISH", "TRANSITION_BULLISH"}),
        ("HIGHER_HIGH_FAILURE", "1M_HIGHER_HIGH" not in evidence),
        ("LOWER_HIGH_FORMED", "1M_LOWER_HIGH" in evidence),
        ("EMA10_LOST", "5M_CLOSE_BELOW_EMA10" in evidence),
        ("EMA10_SLOPE_NEGATIVE", "5M_EMA10_FALLING" in evidence),
        ("LAST_HIGHER_LOW_BROKEN", "1M_STRUCTURE_BREAKDOWN" in evidence),
        ("EMA10_BELOW_EMA30", "1M_EMA10_BELOW_EMA30" in evidence),
        ("BEARISH_CONFIRMED", regime == "BEARISH"),
    ]
    completed = [item for item in checks if item[1]]
    if not completed:
        return "TRANSITION_WATCH", 0
    return completed[-1][0], completed[-1][0] == "BEARISH_CONFIRMED" and 7 or checks.index(completed[-1])


def _direction(snapshot: Mapping[str, object]) -> str | None:
    regime = str(snapshot.get("current_regime") or "")
    if regime in {"BULLISH", "TRANSITION_BULLISH"}:
        return "BULLISH"
    if regime in {"BEARISH", "TRANSITION_BEARISH"}:
        return "BEARISH"

    bull = int(snapshot.get("bullish_score") or 0)
    bear = int(snapshot.get("bearish_score") or 0)
    if bull >= 55 and bull > bear:
        return "BULLISH"
    if bear >= 55 and bear > bull:
        return "BEARISH"
    return None


def _is_invalidated(
    direction: str,
    snapshot: Mapping[str, object],
) -> bool:
    close = snapshot.get("close")
    invalidation = snapshot.get("invalidation_level")
    evidence = set(snapshot.get("evidence") or [])
    if direction == "BULLISH":
        if "1M_STRUCTURE_BREAKDOWN" in evidence:
            return True
        if close is not None and invalidation is not None:
            return float(close) < float(invalidation)
    else:
        if "1M_STRUCTURE_BREAKOUT" in evidence:
            return True
        if close is not None and invalidation is not None:
            return float(close) > float(invalidation)
    return False


class TransitionSequenceStateMachine:
    def advance(
        self,
        snapshot: Mapping[str, object],
        previous: Mapping[str, object] | None = None,
    ) -> TransitionSequenceState | None:
        direction = _direction(snapshot)
        if direction is None:
            return None

        timestamp = _now_text(snapshot)
        previous_record = dict(previous or {})
        previous_direction = str(previous_record.get("direction") or "")
        previous_status = str(previous_record.get("status") or "")

        start_new = (
            not previous_record
            or previous_status in TERMINAL_STATES
            or previous_direction != direction
        )

        transition_id = (
            _new_id(direction, timestamp)
            if start_new
            else str(previous_record.get("transition_id"))
        )
        started_at = (
            timestamp
            if start_new
            else str(previous_record.get("started_at") or timestamp)
        )

        if _is_invalidated(direction, snapshot):
            return TransitionSequenceState(
                transition_id=transition_id,
                direction=direction,
                status="INVALIDATED",
                stage="INVALIDATED",
                stage_index=int(previous_record.get("stage_index") or 0),
                progress_pct=float(previous_record.get("progress_pct") or 0.0),
                started_at=started_at,
                updated_at=timestamp,
                confirmed_at=previous_record.get("confirmed_at"),
                invalidated_at=timestamp,
                previous_regime=str(snapshot.get("previous_regime") or "UNKNOWN"),
                current_regime=str(snapshot.get("current_regime") or "UNKNOWN"),
                break_level=snapshot.get("break_level"),
                invalidation_level=snapshot.get("invalidation_level"),
                bullish_score=int(snapshot.get("bullish_score") or 0),
                bearish_score=int(snapshot.get("bearish_score") or 0),
                evidence=tuple(snapshot.get("evidence") or []),
                red_bar_support=str(snapshot.get("red_bar_support") or "NOT_AVAILABLE"),
                execution_allowed=False,
            )

        if direction == "BULLISH":
            stage, index = _bullish_stage(snapshot)
        else:
            stage, index = _bearish_stage(snapshot)

        previous_index = int(previous_record.get("stage_index") or 0)
        # Never move backward inside the same active transition.
        if not start_new and index < previous_index:
            index = previous_index
            stage = str(previous_record.get("stage") or stage)

        confirmed = stage in {"BULLISH_CONFIRMED", "BEARISH_CONFIRMED"}
        status = "CONFIRMED" if confirmed else "ACTIVE"
        confirmed_at = (
            timestamp
            if confirmed and not previous_record.get("confirmed_at")
            else previous_record.get("confirmed_at")
        )

        return TransitionSequenceState(
            transition_id=transition_id,
            direction=direction,
            status=status,
            stage=stage,
            stage_index=index,
            progress_pct=round(index / 7 * 100.0, 2),
            started_at=started_at,
            updated_at=timestamp,
            confirmed_at=confirmed_at,
            invalidated_at=None,
            previous_regime=str(snapshot.get("previous_regime") or "UNKNOWN"),
            current_regime=str(snapshot.get("current_regime") or "UNKNOWN"),
            break_level=snapshot.get("break_level"),
            invalidation_level=snapshot.get("invalidation_level"),
            bullish_score=int(snapshot.get("bullish_score") or 0),
            bearish_score=int(snapshot.get("bearish_score") or 0),
            evidence=tuple(snapshot.get("evidence") or []),
            red_bar_support=str(snapshot.get("red_bar_support") or "NOT_AVAILABLE"),
            execution_allowed=False,
        )
