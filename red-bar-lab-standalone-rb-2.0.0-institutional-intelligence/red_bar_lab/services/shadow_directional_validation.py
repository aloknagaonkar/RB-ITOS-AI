from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping

import pandas as pd

from red_bar_lab.services.shadow_directional_replay import (
    ShadowDirectionalReplayService,
)


CONFIDENCE_BANDS = (
    (0.0, 40.0, "LOW"),
    (40.0, 60.0, "MODERATE"),
    (60.0, 75.0, "STRONG"),
    (75.0, float("inf"), "VERY_STRONG"),
)


@dataclass(frozen=True)
class ShadowPromotionGateResult:
    eligible: bool
    evaluated_transitions: int
    trading_sessions: int
    accuracy_30m: float | None
    false_transition_rate_30m: float | None
    average_mfe: float | None
    average_mae: float | None
    bullish_accuracy_30m: float | None
    bearish_accuracy_30m: float | None
    warnings: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "evaluated_transitions": self.evaluated_transitions,
            "trading_sessions": self.trading_sessions,
            "accuracy_30m": self.accuracy_30m,
            "false_transition_rate_30m": self.false_transition_rate_30m,
            "average_mfe": self.average_mfe,
            "average_mae": self.average_mae,
            "bullish_accuracy_30m": self.bullish_accuracy_30m,
            "bearish_accuracy_30m": self.bearish_accuracy_30m,
            "warnings": list(self.warnings),
            "execution_allowed": False,
        }


def confidence_band(confidence: object) -> str:
    value = float(confidence or 0.0)
    for minimum, maximum, label in CONFIDENCE_BANDS:
        if minimum <= value < maximum:
            return label
    return "LOW"


def _accuracy(rows: list[Mapping[str, object]], field: str) -> float | None:
    values = [
        bool(row[field])
        for row in rows
        if row.get(field) is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values) * 100.0, 2)


def summarize_by_field(
    rows: Iterable[Mapping[str, object]],
    field: str,
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(field) or "UNKNOWN"), []).append(row)

    output: list[dict[str, object]] = []
    for key, group in sorted(grouped.items()):
        summary = ShadowDirectionalReplayService.summarize(group).as_record()
        output.append({field: key, **summary})
    return output


def summarize_by_confidence(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    decorated = []
    for row in rows:
        decorated.append({**dict(row), "confidence_band": confidence_band(row.get("confidence"))})
    return summarize_by_field(decorated, "confidence_band")


def evaluate_promotion_gates(
    rows: Iterable[Mapping[str, object]],
    *,
    minimum_transitions: int = 100,
    minimum_sessions: int = 20,
    minimum_accuracy_30m: float = 60.0,
    maximum_false_transition_rate_30m: float = 40.0,
) -> ShadowPromotionGateResult:
    items = list(rows)
    sessions = {
        str(row.get("trading_date") or "")
        for row in items
        if row.get("trading_date")
    }
    summary = ShadowDirectionalReplayService.summarize(items)

    bullish = [row for row in items if str(row.get("direction")) == "BULLISH"]
    bearish = [row for row in items if str(row.get("direction")) == "BEARISH"]
    bullish_accuracy = _accuracy(bullish, "direction_correct_30m")
    bearish_accuracy = _accuracy(bearish, "direction_correct_30m")

    warnings: list[str] = []

    if len(items) < minimum_transitions:
        warnings.append("INSUFFICIENT SAMPLE")
    if len(sessions) < minimum_sessions:
        warnings.append("INSUFFICIENT TRADING SESSIONS")
    if summary.accuracy_30m is None or summary.accuracy_30m < minimum_accuracy_30m:
        warnings.append("30M ACCURACY BELOW PROMOTION GATE")
    if (
        summary.false_transition_rate_30m is None
        or summary.false_transition_rate_30m > maximum_false_transition_rate_30m
    ):
        warnings.append("HIGH FALSE-TRANSITION RATE")
    if (
        summary.average_mfe is None
        or summary.average_mae is None
        or summary.average_mfe <= summary.average_mae
    ):
        warnings.append("MFE DOES NOT JUSTIFY MAE")
    if bullish_accuracy is None or bearish_accuracy is None:
        warnings.append("BOTH DIRECTIONS NOT SUFFICIENTLY REPRESENTED")
    elif bullish_accuracy <= 50.0 or bearish_accuracy <= 50.0:
        warnings.append("DIRECTION PERFORMANCE UNBALANCED")

    by_regime = summarize_by_field(items, "regime")
    resolved_regimes = [
        row for row in by_regime if int(row.get("resolved_30m") or 0) > 0
    ]
    if resolved_regimes:
        dominant = max(int(row.get("resolved_30m") or 0) for row in resolved_regimes)
        total = sum(int(row.get("resolved_30m") or 0) for row in resolved_regimes)
        if total > 0 and dominant / total >= 0.80:
            warnings.append("REGIME PERFORMANCE UNSTABLE")
    else:
        warnings.append("REGIME PERFORMANCE UNAVAILABLE")

    return ShadowPromotionGateResult(
        eligible=not warnings,
        evaluated_transitions=len(items),
        trading_sessions=len(sessions),
        accuracy_30m=summary.accuracy_30m,
        false_transition_rate_30m=summary.false_transition_rate_30m,
        average_mfe=summary.average_mfe,
        average_mae=summary.average_mae,
        bullish_accuracy_30m=bullish_accuracy,
        bearish_accuracy_30m=bearish_accuracy,
        warnings=tuple(warnings),
    )


class MultiDayShadowValidationService:
    def __init__(self, replay_service: ShadowDirectionalReplayService | None = None):
        self.replay_service = replay_service or ShadowDirectionalReplayService()

    @staticmethod
    def trading_dates(start_date: date, end_date: date) -> list[date]:
        if end_date < start_date:
            raise ValueError("End date must be on or after start date.")
        days = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days

    def replay_days(
        self,
        frames_by_date: Mapping[date, pd.DataFrame],
        *,
        minimum_decision: str = "TRANSITION_FORMING",
    ) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for trading_date in sorted(frames_by_date):
            frame = frames_by_date[trading_date]
            rows = self.replay_service.replay(
                frame,
                minimum_decision=minimum_decision,
            )
            for row in rows:
                output.append(
                    {
                        **row,
                        "trading_date": trading_date.isoformat(),
                        "confidence_band": confidence_band(row.get("confidence")),
                        "execution_allowed": False,
                    }
                )
        return output

    @staticmethod
    def dashboard(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
        items = list(rows)
        summary = ShadowDirectionalReplayService.summarize(items).as_record()
        gates = evaluate_promotion_gates(items).as_record()
        return {
            "summary": summary,
            "promotion_gates": gates,
            "by_regime": summarize_by_field(items, "regime"),
            "by_direction": summarize_by_field(items, "direction"),
            "by_confidence": summarize_by_confidence(items),
            "rows": items,
            "execution_allowed": False,
        }
