from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from red_bar_lab.utils import safe_float


def _trade_action(order: dict[str, object]) -> str:
    option_type = str(order.get("option_type") or "").upper()
    if option_type == "CE":
        return "BUY CE"
    if option_type == "PE":
        return "BUY PE"
    return "WAIT"


def _result_label(pnl: float) -> str:
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "BREAKEVEN"


@dataclass(frozen=True)
class ShadowValidationSummary:
    closed_trades: int
    current_wins: int
    current_losses: int
    current_breakeven: int
    current_win_rate: float
    shadow_resolved: int
    shadow_correct: int
    shadow_wrong: int
    shadow_accuracy: float | None
    agreement_count: int
    agreement_rate: float | None
    agreement_wins: int
    agreement_win_rate: float | None
    disagreement_count: int
    shadow_better: int
    current_better: int
    unresolved_disagreements: int
    latest_shadow_decision: str
    latest_shadow_confidence: float
    stability_minutes: float
    stability_samples: int


class ShadowValidationService:
    """Evidence-only validation for RB-0.7.6.2.

    Accuracy is intentionally conservative. An opposite shadow recommendation
    is NOT labelled correct/incorrect from the executed trade alone because
    that would require a counterfactual price path for the opposite contract.
    Such cases remain UNRESOLVED.
    """

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _latest_by_signal(
        evaluations: list[dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        latest: dict[str, dict[str, object]] = {}
        for row in evaluations:
            signal_id = str(row.get("signal_id") or "")
            if not signal_id:
                continue
            previous = latest.get(signal_id)
            if (
                previous is None
                or str(row.get("evaluated_at") or "")
                > str(previous.get("evaluated_at") or "")
            ):
                latest[signal_id] = row
        return latest

    @staticmethod
    def _resolve_shadow(
        *,
        actual_action: str,
        trade_result: str,
        shadow_action: str,
    ) -> str:
        if shadow_action == actual_action:
            if trade_result == "WIN":
                return "SHADOW_CORRECT"
            if trade_result == "LOSS":
                return "SHADOW_WRONG"
            return "UNRESOLVED"

        if shadow_action == "WAIT":
            if trade_result == "LOSS":
                return "SHADOW_CORRECT"
            if trade_result == "WIN":
                return "CURRENT_CORRECT"
            return "UNRESOLVED"

        # Opposite-direction calls require a real counterfactual option path.
        return "UNRESOLVED"

    def evaluate(self) -> dict[str, object]:
        orders = self.database.read_paper_execution_orders("PAPER-STD")
        closed = [
            row for row in orders
            if str(row.get("status") or "") == "CLOSED"
            and row.get("signal_id")
        ]
        evaluations = self.database.read_shadow_intelligence_evaluations(
            limit=100000
        )
        latest_by_signal = self._latest_by_signal(evaluations)

        current_wins = current_losses = current_breakeven = 0
        agreement_count = agreement_wins = 0
        disagreement_count = 0
        shadow_correct = shadow_wrong = 0
        shadow_better = current_better = unresolved = 0
        resolved_rows: list[dict[str, object]] = []

        for order in closed:
            pnl = safe_float(order.get("realized_pnl"), default=0.0)
            result = _result_label(pnl)
            if result == "WIN":
                current_wins += 1
            elif result == "LOSS":
                current_losses += 1
            else:
                current_breakeven += 1

            signal_id = str(order.get("signal_id") or "")
            shadow = latest_by_signal.get(signal_id)
            if not shadow:
                continue

            actual_action = _trade_action(order)
            shadow_action = str(
                shadow.get("shadow_decision") or "WAIT"
            ).upper()
            is_agreement = actual_action == shadow_action
            if is_agreement:
                agreement_count += 1
                if result == "WIN":
                    agreement_wins += 1
            else:
                disagreement_count += 1

            resolution = self._resolve_shadow(
                actual_action=actual_action,
                trade_result=result,
                shadow_action=shadow_action,
            )
            if resolution == "SHADOW_CORRECT":
                shadow_correct += 1
                if not is_agreement:
                    shadow_better += 1
            elif resolution == "SHADOW_WRONG":
                shadow_wrong += 1
            elif resolution == "CURRENT_CORRECT":
                current_better += 1
            else:
                unresolved += 1

            resolved_rows.append(
                {
                    "Signal": signal_id,
                    "Actual": actual_action,
                    "Shadow": shadow_action,
                    "Agreement": "YES" if is_agreement else "NO",
                    "Trade Result": result,
                    "P&L ₹": pnl,
                    "Validation": resolution,
                    "Shadow Confidence": safe_float(
                        shadow.get("shadow_confidence"),
                        default=0.0,
                    ),
                    "Evaluated At": shadow.get("evaluated_at"),
                }
            )

        closed_count = len(closed)
        current_win_rate = (
            current_wins / closed_count * 100.0
            if closed_count else 0.0
        )
        shadow_resolved = shadow_correct + shadow_wrong + current_better
        # For shadow accuracy, CURRENT_CORRECT is evidence that shadow WAIT was
        # wrong; SHADOW_WRONG is agreement with a losing trade.
        shadow_incorrect = shadow_wrong + current_better
        shadow_accuracy = (
            shadow_correct / (shadow_correct + shadow_incorrect) * 100.0
            if shadow_correct + shadow_incorrect else None
        )
        covered = len(resolved_rows)
        agreement_rate = (
            agreement_count / covered * 100.0 if covered else None
        )
        agreement_win_rate = (
            agreement_wins / agreement_count * 100.0
            if agreement_count else None
        )

        stability = self.recommendation_stability(evaluations)
        latest = evaluations[0] if evaluations else {}

        return {
            "summary": ShadowValidationSummary(
                closed_trades=closed_count,
                current_wins=current_wins,
                current_losses=current_losses,
                current_breakeven=current_breakeven,
                current_win_rate=round(current_win_rate, 2),
                shadow_resolved=shadow_correct + shadow_incorrect,
                shadow_correct=shadow_correct,
                shadow_wrong=shadow_incorrect,
                shadow_accuracy=(
                    round(shadow_accuracy, 2)
                    if shadow_accuracy is not None else None
                ),
                agreement_count=agreement_count,
                agreement_rate=(
                    round(agreement_rate, 2)
                    if agreement_rate is not None else None
                ),
                agreement_wins=agreement_wins,
                agreement_win_rate=(
                    round(agreement_win_rate, 2)
                    if agreement_win_rate is not None else None
                ),
                disagreement_count=disagreement_count,
                shadow_better=shadow_better,
                current_better=current_better,
                unresolved_disagreements=unresolved,
                latest_shadow_decision=str(
                    latest.get("shadow_decision") or "NO DATA"
                ),
                latest_shadow_confidence=safe_float(
                    latest.get("shadow_confidence"),
                    default=0.0,
                ),
                stability_minutes=stability["minutes"],
                stability_samples=stability["samples"],
            ),
            "trade_comparison": resolved_rows,
            "module_scoreboard": self.module_scoreboard(
                closed=closed,
                evaluations=evaluations,
            ),
            "stability": stability,
        }

    def module_scoreboard(
        self,
        *,
        closed: list[dict[str, object]],
        evaluations: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        latest_by_signal = self._latest_by_signal(evaluations)
        counters: dict[str, Counter] = defaultdict(Counter)

        for order in closed:
            signal_id = str(order.get("signal_id") or "")
            shadow = latest_by_signal.get(signal_id)
            if not shadow:
                continue

            actual_action = _trade_action(order)
            result = _result_label(safe_float(order.get("realized_pnl"), default=0.0))

            for module in shadow.get("modules") or []:
                name = str(module.get("module") or "UNKNOWN")
                recommendation = str(
                    module.get("recommendation") or "WAIT"
                ).upper()
                confidence = safe_float(module.get("confidence"), default=0.0)

                counters[name]["observations"] += 1
                if confidence > 0:
                    counters[name]["scored"] += 1

                resolution = self._resolve_shadow(
                    actual_action=actual_action,
                    trade_result=result,
                    shadow_action=recommendation,
                )
                if resolution == "SHADOW_CORRECT":
                    counters[name]["correct"] += 1
                    counters[name]["resolved"] += 1
                elif resolution in {"SHADOW_WRONG", "CURRENT_CORRECT"}:
                    counters[name]["wrong"] += 1
                    counters[name]["resolved"] += 1
                else:
                    counters[name]["unresolved"] += 1

        rows = []
        for name in sorted(counters):
            item = counters[name]
            resolved = int(item["resolved"])
            accuracy = (
                item["correct"] / resolved * 100.0 if resolved else None
            )
            observations = int(item["observations"])
            coverage = (
                resolved / observations * 100.0
                if observations else 0.0
            )

            if (
                resolved >= 30
                and accuracy is not None
                and accuracy >= 70.0
                and coverage >= 50.0
            ):
                lifecycle = "VALIDATED"
                promotion = "CANDIDATE"
            elif resolved >= 10:
                lifecycle = "OBSERVE"
                promotion = "MORE EVIDENCE"
            else:
                lifecycle = "OBSERVE"
                promotion = "LEARNING"

            rows.append(
                {
                    "Module": name,
                    "Status": lifecycle,
                    "Resolved Samples": resolved,
                    "Correct": int(item["correct"]),
                    "Wrong": int(item["wrong"]),
                    "Unresolved": int(item["unresolved"]),
                    "Accuracy %": (
                        round(accuracy, 2)
                        if accuracy is not None else None
                    ),
                    "Resolved Coverage %": round(coverage, 2),
                    "Promotion": promotion,
                    "Execution Impact": "NONE",
                }
            )
        return rows

    @staticmethod
    def recommendation_stability(
        evaluations: list[dict[str, object]],
    ) -> dict[str, object]:
        if not evaluations:
            return {
                "decision": "NO DATA",
                "minutes": 0.0,
                "samples": 0,
                "started_at": None,
                "last_seen_at": None,
            }

        ordered = sorted(
            evaluations,
            key=lambda row: str(row.get("evaluated_at") or ""),
        )
        latest_decision = str(
            ordered[-1].get("shadow_decision") or "WAIT"
        )

        streak = []
        for row in reversed(ordered):
            if str(row.get("shadow_decision") or "WAIT") != latest_decision:
                break
            streak.append(row)
        streak.reverse()

        first = str(streak[0].get("evaluated_at") or "") if streak else ""
        last = str(streak[-1].get("evaluated_at") or "") if streak else ""
        minutes = 0.0
        try:
            start = datetime.fromisoformat(first)
            end = datetime.fromisoformat(last)
            minutes = max(0.0, (end - start).total_seconds() / 60.0)
        except Exception:
            minutes = 0.0

        return {
            "decision": latest_decision,
            "minutes": round(minutes, 2),
            "samples": len(streak),
            "started_at": first or None,
            "last_seen_at": last or None,
        }
