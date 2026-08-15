from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DRIOutcomeReconciliationReport:
    executed_trades: int
    headline_comparable: int
    baseline_comparable: int
    fixed_comparable: int
    adaptive_comparable: int
    headline_net_points: float
    baseline_net_points: float
    fixed_net_points: float
    adaptive_net_points: float
    headline_vs_baseline_delta: float
    headline_vs_fixed_delta: float
    headline_vs_adaptive_delta: float
    rows: tuple[dict[str, object], ...]

    def summary_rows(self) -> list[dict[str, object]]:
        return [
            {
                "Model": "HEADLINE_OUTCOME",
                "Comparable Trades": self.headline_comparable,
                "Net Points": round(self.headline_net_points, 3),
                "Delta vs Headline": 0.0,
                "Basis": "Stored outcome_points used by replay headline metrics",
            },
            {
                "Model": "BASELINE_EXIT",
                "Comparable Trades": self.baseline_comparable,
                "Net Points": round(self.baseline_net_points, 3),
                "Delta vs Headline": round(-self.headline_vs_baseline_delta, 3),
                "Basis": "option_exit_price - option_entry_price",
            },
            {
                "Model": "FIXED_TRAILING",
                "Comparable Trades": self.fixed_comparable,
                "Net Points": round(self.fixed_net_points, 3),
                "Delta vs Headline": round(-self.headline_vs_fixed_delta, 3),
                "Basis": "trailing_exit_price - option_entry_price",
            },
            {
                "Model": "ADAPTIVE_TRAILING_AUDIT",
                "Comparable Trades": self.adaptive_comparable,
                "Net Points": round(self.adaptive_net_points, 3),
                "Delta vs Headline": round(-self.headline_vs_adaptive_delta, 3),
                "Basis": "adaptive_trailing_exit_price - option_entry_price",
            },
        ]


def reconcile_historical_dri_outcomes(
    replay_results: Iterable[object],
) -> DRIOutcomeReconciliationReport:
    detail: list[dict[str, object]] = []
    headline: list[float] = []
    baseline: list[float] = []
    fixed: list[float] = []
    adaptive: list[float] = []

    for result in sorted(
        tuple(replay_results),
        key=lambda item: str(getattr(item, "trading_date", "")),
    ):
        trading_date = getattr(result, "trading_date", None)
        for row in tuple(getattr(result, "rows", ()) or ()):
            if str(getattr(row, "execution", "")) != "WOULD_TAKE":
                continue
            entry = _number(getattr(row, "option_entry_price", None))
            headline_points = _number(getattr(row, "outcome_points", None))
            baseline_exit = _number(getattr(row, "option_exit_price", None))
            fixed_exit = _number(getattr(row, "trailing_exit_price", None))
            adaptive_exit = _number(
                getattr(row, "adaptive_trailing_exit_price", None)
            )
            baseline_points = _difference(baseline_exit, entry)
            fixed_points = _difference(fixed_exit, entry)
            adaptive_points = _difference(adaptive_exit, entry)

            if headline_points is not None:
                headline.append(headline_points)
            if baseline_points is not None:
                baseline.append(baseline_points)
            if fixed_points is not None:
                fixed.append(fixed_points)
            if adaptive_points is not None:
                adaptive.append(adaptive_points)

            detail.append(
                {
                    "Trading Date": (
                        trading_date.isoformat()
                        if hasattr(trading_date, "isoformat")
                        else str(trading_date or "")
                    ),
                    "Time": getattr(row, "timestamp", None),
                    "Signal": getattr(row, "signal_id", None),
                    "Direction": getattr(row, "direction", None),
                    "Entry": entry,
                    "Headline Points": headline_points,
                    "Headline Basis": getattr(row, "outcome_basis", None),
                    "Baseline Exit": baseline_exit,
                    "Baseline Points": baseline_points,
                    "Baseline Exit Reason": getattr(row, "exit_reason", None),
                    "Fixed Trailing Exit": fixed_exit,
                    "Fixed Trailing Points": fixed_points,
                    "Fixed Exit Reason": getattr(
                        row, "trailing_exit_reason", None
                    ),
                    "Adaptive Exit": adaptive_exit,
                    "Adaptive Points": adaptive_points,
                    "Adaptive Exit Reason": getattr(
                        row, "adaptive_trailing_exit_reason", None
                    ),
                    "Headline - Baseline": _delta(
                        headline_points, baseline_points
                    ),
                    "Headline - Fixed": _delta(headline_points, fixed_points),
                    "Headline - Adaptive": _delta(
                        headline_points, adaptive_points
                    ),
                    "Comparable": all(
                        value is not None
                        for value in (
                            headline_points,
                            baseline_points,
                            fixed_points,
                            adaptive_points,
                        )
                    ),
                }
            )

    headline_net = sum(headline)
    baseline_net = sum(baseline)
    fixed_net = sum(fixed)
    adaptive_net = sum(adaptive)
    return DRIOutcomeReconciliationReport(
        executed_trades=len(detail),
        headline_comparable=len(headline),
        baseline_comparable=len(baseline),
        fixed_comparable=len(fixed),
        adaptive_comparable=len(adaptive),
        headline_net_points=headline_net,
        baseline_net_points=baseline_net,
        fixed_net_points=fixed_net,
        adaptive_net_points=adaptive_net,
        headline_vs_baseline_delta=headline_net - baseline_net,
        headline_vs_fixed_delta=headline_net - fixed_net,
        headline_vs_adaptive_delta=headline_net - adaptive_net,
        rows=tuple(detail),
    )


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _difference(exit_price: float | None, entry: float | None) -> float | None:
    if exit_price is None or entry is None:
        return None
    return exit_price - entry


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right
