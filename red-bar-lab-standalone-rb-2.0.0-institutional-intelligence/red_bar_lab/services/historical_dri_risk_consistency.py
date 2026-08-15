from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class HistoricalDRIPromotionCriteria:
    minimum_profitable_days_pct: float = 60.0
    minimum_profit_factor: float = 1.5
    require_positive_median_daily_points: bool = True
    require_positive_total_net_points: bool = True
    maximum_single_day_profit_concentration_pct: float = 50.0
    maximum_consecutive_losing_days: int = 3


@dataclass(frozen=True)
class HistoricalDRISlicePerformance:
    trades: int
    wins: int
    losses: int
    net_points: float
    average_points: float
    profit_factor: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "Trades": self.trades,
            "Wins": self.wins,
            "Losses": self.losses,
            "Net Points": round(self.net_points, 3),
            "Average Points": round(self.average_points, 3),
            "Profit Factor": (
                round(self.profit_factor, 3)
                if self.profit_factor is not None
                else None
            ),
        }


@dataclass(frozen=True)
class HistoricalDRIRiskConsistencyReport:
    evaluated_days: int
    profitable_days: int
    losing_days: int
    flat_days: int
    profitable_day_pct: float
    total_net_points: float
    median_daily_points: float
    average_winner: float
    average_loss: float
    profit_factor: float | None
    maximum_losing_streak: int
    maximum_consecutive_losing_days: int
    maximum_daily_drawdown: float
    single_day_profit_concentration_pct: float
    direction_performance: Mapping[str, HistoricalDRISlicePerformance]
    tier_performance: Mapping[str, HistoricalDRISlicePerformance]
    entry_type_performance: Mapping[str, HistoricalDRISlicePerformance]
    trailing_comparison: Mapping[str, HistoricalDRISlicePerformance]
    promotion_checks: Mapping[str, bool]
    promotion_passed: bool

    def summary(self) -> dict[str, object]:
        return {
            "Evaluated Days": self.evaluated_days,
            "Profitable Days": self.profitable_days,
            "Losing Days": self.losing_days,
            "Flat Days": self.flat_days,
            "Profitable Day %": round(self.profitable_day_pct, 2),
            "Total Net Points": round(self.total_net_points, 3),
            "Median Daily Points": round(self.median_daily_points, 3),
            "Average Winner": round(self.average_winner, 3),
            "Average Loss": round(self.average_loss, 3),
            "Profit Factor": (
                round(self.profit_factor, 3)
                if self.profit_factor is not None
                else None
            ),
            "Maximum Losing Streak": self.maximum_losing_streak,
            "Maximum Consecutive Losing Days": (
                self.maximum_consecutive_losing_days
            ),
            "Maximum Daily Drawdown": round(self.maximum_daily_drawdown, 3),
            "Single-Day Profit Concentration %": round(
                self.single_day_profit_concentration_pct, 2
            ),
            "Promotion Passed": self.promotion_passed,
        }

    def promotion_rows(self) -> list[dict[str, object]]:
        return [
            {"Criterion": name, "Passed": passed}
            for name, passed in self.promotion_checks.items()
        ]

    def slice_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group, values in (
            ("Direction", self.direction_performance),
            ("Market Action Tier", self.tier_performance),
            ("Entry Type", self.entry_type_performance),
            ("Trailing Model", self.trailing_comparison),
        ):
            for name, performance in values.items():
                rows.append(
                    {
                        "Group": group,
                        "Segment": name,
                        **performance.as_dict(),
                    }
                )
        return rows


def analyze_historical_dri_risk_consistency(
    replay_results: Iterable[object],
    *,
    criteria: HistoricalDRIPromotionCriteria | None = None,
) -> HistoricalDRIRiskConsistencyReport:
    """Analyze a replay window without changing any strategy decisions.

    Only WOULD_TAKE rows with a numeric outcome contribute to trade metrics.
    Results are sorted by trading date, while row order within each day remains
    unchanged so streak and drawdown calculations remain deterministic.
    """

    cfg = criteria or HistoricalDRIPromotionCriteria()
    ordered = sorted(
        tuple(replay_results),
        key=lambda result: str(getattr(result, "trading_date", "")),
    )
    daily_points: list[float] = []
    executed_by_day: list[list[object]] = []

    for result in ordered:
        rows = [
            row
            for row in tuple(getattr(result, "rows", ()) or ())
            if getattr(row, "execution", None) == "WOULD_TAKE"
            and _numeric(getattr(row, "outcome_points", None)) is not None
        ]
        executed_by_day.append(rows)
        daily_points.append(
            sum(float(getattr(row, "outcome_points")) for row in rows)
        )

    all_rows = [row for rows in executed_by_day for row in rows]
    points = [float(getattr(row, "outcome_points")) for row in all_rows]
    winners = [point for point in points if point > 0.0]
    losses = [point for point in points if point < 0.0]

    total_net = sum(daily_points)
    profitable_days = sum(point > 0.0 for point in daily_points)
    losing_days = sum(point < 0.0 for point in daily_points)
    flat_days = sum(point == 0.0 for point in daily_points)
    profitable_pct = (
        profitable_days / len(daily_points) * 100.0 if daily_points else 0.0
    )
    profit_factor = _profit_factor(points)
    maximum_trade_losing_streak = _maximum_negative_streak(points)
    maximum_losing_days = _maximum_negative_streak(daily_points)
    maximum_daily_drawdown = max(
        (_maximum_drawdown([
            float(getattr(row, "outcome_points")) for row in rows
        ]) for rows in executed_by_day),
        default=0.0,
    )
    concentration = _single_day_profit_concentration(daily_points, total_net)

    direction = _group_rows(
        all_rows,
        lambda row: _normalize_direction(getattr(row, "direction", None)),
        lambda row: float(getattr(row, "outcome_points")),
        expected=("BULLISH", "BEARISH"),
    )
    tier = _group_rows(
        all_rows,
        _market_action_tier,
        lambda row: float(getattr(row, "outcome_points")),
        expected=("STRONG", "MODERATE"),
    )
    entry_type = _group_rows(
        all_rows,
        _entry_type,
        lambda row: float(getattr(row, "outcome_points")),
        expected=("FIRST_DIRECTION", "RESET_ENTRY"),
    )
    trailing = _trailing_comparison(all_rows)

    checks = {
        "Profitable days >= 60%": (
            profitable_pct >= cfg.minimum_profitable_days_pct
        ),
        "Profit factor >= 1.5": (
            profit_factor is not None
            and profit_factor >= cfg.minimum_profit_factor
        ),
        "Median daily points > 0": (
            (median(daily_points) if daily_points else 0.0) > 0.0
            if cfg.require_positive_median_daily_points
            else True
        ),
        "Total net points positive": (
            total_net > 0.0
            if cfg.require_positive_total_net_points
            else True
        ),
        "No single day > 50% of total profit": (
            concentration <= cfg.maximum_single_day_profit_concentration_pct
        ),
        "Maximum consecutive losing days <= 3": (
            maximum_losing_days <= cfg.maximum_consecutive_losing_days
        ),
    }

    return HistoricalDRIRiskConsistencyReport(
        evaluated_days=len(daily_points),
        profitable_days=profitable_days,
        losing_days=losing_days,
        flat_days=flat_days,
        profitable_day_pct=profitable_pct,
        total_net_points=total_net,
        median_daily_points=median(daily_points) if daily_points else 0.0,
        average_winner=sum(winners) / len(winners) if winners else 0.0,
        average_loss=sum(losses) / len(losses) if losses else 0.0,
        profit_factor=profit_factor,
        maximum_losing_streak=maximum_trade_losing_streak,
        maximum_consecutive_losing_days=maximum_losing_days,
        maximum_daily_drawdown=maximum_daily_drawdown,
        single_day_profit_concentration_pct=concentration,
        direction_performance=direction,
        tier_performance=tier,
        entry_type_performance=entry_type,
        trailing_comparison=trailing,
        promotion_checks=checks,
        promotion_passed=all(checks.values()),
    )


def _numeric(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _profit_factor(points: Sequence[float]) -> float | None:
    gross_profit = sum(point for point in points if point > 0.0)
    gross_loss = abs(sum(point for point in points if point < 0.0))
    if gross_loss == 0.0:
        return None if gross_profit == 0.0 else float("inf")
    return gross_profit / gross_loss


def _maximum_negative_streak(points: Sequence[float]) -> int:
    longest = 0
    current = 0
    for point in points:
        if point < 0.0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _maximum_drawdown(points: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for point in points:
        equity += point
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _single_day_profit_concentration(
    daily_points: Sequence[float],
    total_net: float,
) -> float:
    if total_net <= 0.0:
        return 100.0 if daily_points else 0.0
    largest_profitable_day = max(
        (point for point in daily_points if point > 0.0),
        default=0.0,
    )
    return largest_profitable_day / total_net * 100.0


def _normalize_direction(value: object) -> str:
    text = str(value or "").upper()
    if text in {"UP", "LONG", "CALL", "CE", "BULLISH"}:
        return "BULLISH"
    if text in {"DOWN", "SHORT", "PUT", "PE", "BEARISH"}:
        return "BEARISH"
    return text or "UNKNOWN"


def _market_action_tier(row: object) -> str:
    tier = str(getattr(row, "reset_market_action_tier", "") or "").upper()
    if tier in {"STRONG", "MODERATE"}:
        return tier
    return "UNGATED_FIRST_DIRECTION"


def _entry_type(row: object) -> str:
    if (
        bool(getattr(row, "reset_seen", False))
        or bool(getattr(row, "reexpansion_detected", False))
        or _market_action_tier(row) in {"STRONG", "MODERATE"}
    ):
        return "RESET_ENTRY"
    return "FIRST_DIRECTION"


def _group_rows(
    rows: Sequence[object],
    key,
    points,
    *,
    expected: Sequence[str] = (),
) -> dict[str, HistoricalDRISlicePerformance]:
    grouped: dict[str, list[float]] = {name: [] for name in expected}
    for row in rows:
        grouped.setdefault(str(key(row)), []).append(float(points(row)))
    return {
        name: _slice_performance(values)
        for name, values in grouped.items()
    }


def _slice_performance(points: Sequence[float]) -> HistoricalDRISlicePerformance:
    return HistoricalDRISlicePerformance(
        trades=len(points),
        wins=sum(point > 0.0 for point in points),
        losses=sum(point < 0.0 for point in points),
        net_points=sum(points),
        average_points=sum(points) / len(points) if points else 0.0,
        profit_factor=_profit_factor(points),
    )


def _trailing_comparison(
    rows: Sequence[object],
) -> dict[str, HistoricalDRISlicePerformance]:
    fixed: list[float] = []
    adaptive: list[float] = []
    for row in rows:
        entry = _numeric(getattr(row, "option_entry_price", None))
        fixed_exit = _numeric(getattr(row, "trailing_exit_price", None))
        adaptive_exit = _numeric(
            getattr(row, "adaptive_trailing_exit_price", None)
        )
        if entry is not None and fixed_exit is not None:
            fixed.append(fixed_exit - entry)
        if entry is not None and adaptive_exit is not None:
            adaptive.append(adaptive_exit - entry)
    return {
        "FIXED": _slice_performance(fixed),
        "ADAPTIVE_AUDIT": _slice_performance(adaptive),
    }
