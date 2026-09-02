from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping
import hashlib


SETUP_TYPES = (
    "BULLISH_STRUCTURE_BREAK",
    "BEARISH_STRUCTURE_BREAK",
    "BULLISH_EMA_RECLAIM",
    "BEARISH_EMA_LOSS",
    "BULLISH_RANGE_BREAKOUT",
    "BEARISH_RANGE_BREAKDOWN",
    "BULLISH_PULLBACK_CONTINUATION",
    "BEARISH_PULLBACK_CONTINUATION",
    "BULLISH_RED_BAR_CONFIRMATION",
    "BEARISH_RED_BAR_CONFIRMATION",
    "COUNTER_TREND_RED_BAR",
)


@dataclass(frozen=True)
class FreshSetupSignal:
    signal_id: str
    regime_snapshot_id: str
    transition_id: str
    setup_type: str
    direction: str
    detected_at: str
    trigger_level: float | None
    invalidation_level: float | None
    fresh_until: str
    primary_trigger: str
    supporting_evidence: tuple[str, ...]
    red_bar_alignment: str
    status: str
    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "supporting_evidence": list(self.supporting_evidence),
            "execution_allowed": False,
        }


def _signal_id(
    regime_snapshot_id: str,
    transition_id: str,
    setup_type: str,
    detected_at: str,
) -> str:
    raw = "|".join(
        [regime_snapshot_id, transition_id, setup_type, detected_at]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    stamp = detected_at.replace(":", "").replace("-", "").replace("+", "")
    return f"SIG-{setup_type[:8]}-{stamp}-{digest}"


def _fresh_until(detected_at: str, minutes: int) -> str:
    value = datetime.fromisoformat(detected_at)
    return (value + timedelta(minutes=minutes)).isoformat()


def _emit(
    *,
    regime_snapshot_id: str,
    transition_id: str,
    setup_type: str,
    direction: str,
    detected_at: str,
    trigger_level: float | None,
    invalidation_level: float | None,
    primary_trigger: str,
    supporting_evidence: Iterable[str],
    red_bar_alignment: str,
    freshness_minutes: int,
) -> FreshSetupSignal:
    return FreshSetupSignal(
        signal_id=_signal_id(
            regime_snapshot_id,
            transition_id,
            setup_type,
            detected_at,
        ),
        regime_snapshot_id=regime_snapshot_id,
        transition_id=transition_id,
        setup_type=setup_type,
        direction=direction,
        detected_at=detected_at,
        trigger_level=trigger_level,
        invalidation_level=invalidation_level,
        fresh_until=_fresh_until(detected_at, freshness_minutes),
        primary_trigger=primary_trigger,
        supporting_evidence=tuple(supporting_evidence),
        red_bar_alignment=red_bar_alignment,
        status="FRESH",
        execution_allowed=False,
    )


class FreshSetupSignalEngine:
    def detect(
        self,
        regime_snapshot: Mapping[str, object],
        transition: Mapping[str, object],
        attribution: Mapping[str, object],
        *,
        freshness_minutes: int = 15,
    ) -> list[FreshSetupSignal]:
        evidence = set(regime_snapshot.get("evidence") or [])
        direction = str(transition.get("direction") or "")
        detected_at = str(
            transition.get("updated_at")
            or regime_snapshot.get("timestamp")
            or datetime.now().astimezone().isoformat()
        )
        transition_id = str(transition.get("transition_id") or "")
        regime_snapshot_id = str(attribution.get("regime_snapshot_id") or "")
        trigger_level = regime_snapshot.get("break_level")
        invalidation_level = regime_snapshot.get("invalidation_level")
        red_bar_alignment = str(
            regime_snapshot.get("red_bar_support") or "NOT_AVAILABLE"
        )

        signals: list[FreshSetupSignal] = []

        def add(setup_type: str, trigger: str, supporting: Iterable[str]) -> None:
            signals.append(
                _emit(
                    regime_snapshot_id=regime_snapshot_id,
                    transition_id=transition_id,
                    setup_type=setup_type,
                    direction=direction,
                    detected_at=detected_at,
                    trigger_level=trigger_level,
                    invalidation_level=invalidation_level,
                    primary_trigger=trigger,
                    supporting_evidence=supporting,
                    red_bar_alignment=red_bar_alignment,
                    freshness_minutes=freshness_minutes,
                )
            )

        if direction == "BULLISH":
            if "1M_STRUCTURE_BREAKOUT" in evidence:
                add(
                    "BULLISH_STRUCTURE_BREAK",
                    "1M_STRUCTURE_BREAKOUT",
                    evidence,
                )

            if (
                "5M_CLOSE_ABOVE_EMA10" in evidence
                and "5M_EMA10_RISING" in evidence
            ):
                add(
                    "BULLISH_EMA_RECLAIM",
                    "5M_CLOSE_ABOVE_EMA10",
                    evidence,
                )

            if (
                "1M_STRUCTURE_BREAKOUT" in evidence
                and "1M_POSITIVE_MOMENTUM" in evidence
            ):
                add(
                    "BULLISH_RANGE_BREAKOUT",
                    "1M_STRUCTURE_BREAKOUT",
                    evidence,
                )

            if (
                "1M_HIGHER_LOW" in evidence
                and "1M_EMA10_ABOVE_EMA30" in evidence
                and "1M_POSITIVE_MOMENTUM" in evidence
            ):
                add(
                    "BULLISH_PULLBACK_CONTINUATION",
                    "1M_HIGHER_LOW",
                    evidence,
                )

            if red_bar_alignment == "ALIGNED":
                add(
                    "BULLISH_RED_BAR_CONFIRMATION",
                    "RED_BAR_ALIGNED",
                    evidence,
                )
            elif red_bar_alignment == "COUNTER_TREND":
                add(
                    "COUNTER_TREND_RED_BAR",
                    "RED_BAR_COUNTER_TREND",
                    evidence,
                )

        elif direction == "BEARISH":
            if "1M_STRUCTURE_BREAKDOWN" in evidence:
                add(
                    "BEARISH_STRUCTURE_BREAK",
                    "1M_STRUCTURE_BREAKDOWN",
                    evidence,
                )

            if (
                "5M_CLOSE_BELOW_EMA10" in evidence
                and "5M_EMA10_FALLING" in evidence
            ):
                add(
                    "BEARISH_EMA_LOSS",
                    "5M_CLOSE_BELOW_EMA10",
                    evidence,
                )

            if (
                "1M_STRUCTURE_BREAKDOWN" in evidence
                and "1M_NEGATIVE_MOMENTUM" in evidence
            ):
                add(
                    "BEARISH_RANGE_BREAKDOWN",
                    "1M_STRUCTURE_BREAKDOWN",
                    evidence,
                )

            if (
                "1M_LOWER_HIGH" in evidence
                and "1M_EMA10_BELOW_EMA30" in evidence
                and "1M_NEGATIVE_MOMENTUM" in evidence
            ):
                add(
                    "BEARISH_PULLBACK_CONTINUATION",
                    "1M_LOWER_HIGH",
                    evidence,
                )

            if red_bar_alignment == "ALIGNED":
                add(
                    "BEARISH_RED_BAR_CONFIRMATION",
                    "RED_BAR_ALIGNED",
                    evidence,
                )
            elif red_bar_alignment == "COUNTER_TREND":
                add(
                    "COUNTER_TREND_RED_BAR",
                    "RED_BAR_COUNTER_TREND",
                    evidence,
                )

        return signals
