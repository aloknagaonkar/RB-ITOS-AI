from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable


@dataclass(frozen=True)
class HistoricalDRIDayValidation:
    trading_date: date
    status: str
    bundles: int = 0
    take: int = 0
    wait: int = 0
    block: int = 0
    wins: int = 0
    losses: int = 0
    false_positives: int = 0
    correct_skips: int = 0
    accuracy_pct: float = 0.0
    net_points: float = 0.0
    elapsed_seconds: float = 0.0
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "Trading Date": self.trading_date.isoformat(),
            "Status": self.status,
            "Bundles": self.bundles,
            "TAKE": self.take,
            "WAIT": self.wait,
            "BLOCK": self.block,
            "Wins": self.wins,
            "Losses": self.losses,
            "False Positives": self.false_positives,
            "Correct Skips": self.correct_skips,
            "Accuracy %": round(self.accuracy_pct, 2),
            "Net Option Points": round(self.net_points, 3),
            "Elapsed Seconds": round(self.elapsed_seconds, 2),
            "Error": self.error,
        }


@dataclass(frozen=True)
class HistoricalDRIBatchValidation:
    days: tuple[HistoricalDRIDayValidation, ...]

    @property
    def successful_days(self) -> int:
        return sum(day.status == "PASS" for day in self.days)

    @property
    def failed_days(self) -> int:
        return sum(day.status != "PASS" for day in self.days)

    @property
    def bundles(self) -> int:
        return sum(day.bundles for day in self.days if day.status == "PASS")

    @property
    def take(self) -> int:
        return sum(day.take for day in self.days if day.status == "PASS")

    @property
    def wait(self) -> int:
        return sum(day.wait for day in self.days if day.status == "PASS")

    @property
    def block(self) -> int:
        return sum(day.block for day in self.days if day.status == "PASS")

    @property
    def wins(self) -> int:
        return sum(day.wins for day in self.days if day.status == "PASS")

    @property
    def losses(self) -> int:
        return sum(day.losses for day in self.days if day.status == "PASS")

    @property
    def false_positives(self) -> int:
        return sum(day.false_positives for day in self.days if day.status == "PASS")

    @property
    def correct_skips(self) -> int:
        return sum(day.correct_skips for day in self.days if day.status == "PASS")

    @property
    def net_points(self) -> float:
        return sum(day.net_points for day in self.days if day.status == "PASS")

    @property
    def mean_daily_accuracy_pct(self) -> float:
        values = [day.accuracy_pct for day in self.days if day.status == "PASS"]
        return sum(values) / len(values) if values else 0.0

    def rows(self) -> list[dict[str, object]]:
        return [day.as_dict() for day in self.days]


def validate_historical_dri_dates(
    dates: Iterable[date],
    *,
    run_day: Callable[[date], tuple[object, float]],
    progress_callback: Callable[[int, int, date, str], None] | None = None,
) -> HistoricalDRIBatchValidation:
    ordered_dates = tuple(dict.fromkeys(dates))
    results: list[HistoricalDRIDayValidation] = []
    total = len(ordered_dates)

    for index, trading_date in enumerate(ordered_dates, start=1):
        if progress_callback is not None:
            progress_callback(index - 1, total, trading_date, "RUNNING")
        try:
            replay_result, elapsed_seconds = run_day(trading_date)
            results.append(
                HistoricalDRIDayValidation(
                    trading_date=trading_date,
                    status="PASS",
                    bundles=int(getattr(replay_result, "active_signals", 0)),
                    take=int(getattr(replay_result, "approved", 0)),
                    wait=int(getattr(replay_result, "waiting", 0)),
                    block=int(getattr(replay_result, "blocked", 0)),
                    wins=int(getattr(replay_result, "winners", 0)),
                    losses=int(getattr(replay_result, "losers", 0)),
                    false_positives=int(getattr(replay_result, "false_positives", 0)),
                    correct_skips=int(getattr(replay_result, "correct_skips", 0)),
                    accuracy_pct=float(getattr(replay_result, "decision_accuracy_pct", 0.0)),
                    net_points=float(getattr(replay_result, "net_points", 0.0)),
                    elapsed_seconds=float(elapsed_seconds or 0.0),
                )
            )
        except Exception as exc:
            results.append(
                HistoricalDRIDayValidation(
                    trading_date=trading_date,
                    status="FAILED",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        if progress_callback is not None:
            progress_callback(index, total, trading_date, results[-1].status)

    return HistoricalDRIBatchValidation(days=tuple(results))
