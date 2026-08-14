from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd

from red_bar_lab.intelligence.shadow_directional_service import ShadowDirectionalService
from red_bar_lab.services.shadow_directional_outcome import evaluate_shadow_outcome


@dataclass(frozen=True)
class ShadowReplaySummary:
    evaluated: int
    resolved_5m: int
    resolved_15m: int
    resolved_30m: int
    accuracy_5m: float | None
    accuracy_15m: float | None
    accuracy_30m: float | None
    average_mfe: float | None
    average_mae: float | None
    false_transition_rate_30m: float | None

    def as_record(self) -> dict[str, object]:
        return dict(self.__dict__)


def _accuracy(values: list[bool]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values) * 100.0, 2)


class ShadowDirectionalReplayService:
    """Historical walk-forward replay with no execution side effects."""

    def __init__(self, engine: ShadowDirectionalService | None = None):
        self.engine = engine or ShadowDirectionalService()

    def replay(
        self,
        completed_five_minute_candles: pd.DataFrame,
        *,
        minimum_history: int = 35,
        minimum_decision: str = "TRANSITION_FORMING",
    ) -> list[dict[str, object]]:
        frame = completed_five_minute_candles.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = (
            frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .reset_index(drop=True)
        )
        if len(frame) < minimum_history:
            return []

        decision_rank = {
            "NO_TRANSITION": 0,
            "WATCH": 1,
            "TRANSITION_FORMING": 2,
            "SHADOW_SIGNAL": 3,
            "STRONG_SHADOW_SIGNAL": 4,
        }
        threshold = decision_rank.get(minimum_decision, 2)
        results: list[dict[str, object]] = []

        for end in range(minimum_history, len(frame)):
            visible = frame.iloc[: end + 1].copy()
            transition = self.engine.evaluate(visible)
            record = transition.as_record()
            if record["direction"] not in {"BULLISH", "BEARISH"}:
                continue
            if decision_rank.get(str(record["decision"]), 0) < threshold:
                continue

            record.update(
                {
                    "candle_timestamp": str(visible.iloc[-1]["timestamp"]),
                    "source": "SHADOW_DIRECTIONAL_HISTORICAL_REPLAY",
                    "execution_allowed": False,
                }
            )
            outcome = evaluate_shadow_outcome(frame, record).as_record()
            record.update(outcome)
            results.append(record)

        return results

    @staticmethod
    def summarize(rows: Iterable[Mapping[str, object]]) -> ShadowReplaySummary:
        items = list(rows)
        correct_5 = [bool(r["direction_correct_5m"]) for r in items if r.get("direction_correct_5m") is not None]
        correct_15 = [bool(r["direction_correct_15m"]) for r in items if r.get("direction_correct_15m") is not None]
        correct_30 = [bool(r["direction_correct_30m"]) for r in items if r.get("direction_correct_30m") is not None]
        mfe = [float(r["maximum_favorable_excursion"]) for r in items if r.get("maximum_favorable_excursion") is not None]
        mae = [float(r["maximum_adverse_excursion"]) for r in items if r.get("maximum_adverse_excursion") is not None]
        return ShadowReplaySummary(
            evaluated=len(items),
            resolved_5m=len(correct_5),
            resolved_15m=len(correct_15),
            resolved_30m=len(correct_30),
            accuracy_5m=_accuracy(correct_5),
            accuracy_15m=_accuracy(correct_15),
            accuracy_30m=_accuracy(correct_30),
            average_mfe=round(sum(mfe) / len(mfe), 2) if mfe else None,
            average_mae=round(sum(mae) / len(mae), 2) if mae else None,
            false_transition_rate_30m=(
                round((1.0 - sum(correct_30) / len(correct_30)) * 100.0, 2)
                if correct_30 else None
            ),
        )

    @staticmethod
    def summarize_by_regime(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
        grouped: dict[str, list[Mapping[str, object]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("regime") or "UNKNOWN"), []).append(row)
        output = []
        for regime, group in sorted(grouped.items()):
            summary = ShadowDirectionalReplayService.summarize(group)
            output.append({"regime": regime, **summary.as_record()})
        return output
