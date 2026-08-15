from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from red_bar_lab.services.historical_dri_risk_consistency import (
    HistoricalDRIRiskConsistencyReport,
    analyze_historical_dri_risk_consistency,
)


@dataclass(frozen=True)
class HistoricalDRIWindowAttempt:
    trading_date: date
    status: str
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "Trading Date": self.trading_date.isoformat(),
            "Status": self.status,
            "Reason": self.reason,
        }


@dataclass(frozen=True)
class HistoricalDRIReplayWindow:
    requested_days: int
    replay_results: tuple[object, ...]
    attempts: tuple[HistoricalDRIWindowAttempt, ...]
    report: HistoricalDRIRiskConsistencyReport

    @property
    def completed_days(self) -> int:
        return len(self.replay_results)

    @property
    def complete(self) -> bool:
        return self.completed_days == self.requested_days

    @property
    def promotion_passed(self) -> bool:
        return self.complete and self.report.promotion_passed

    @property
    def selected_dates(self) -> tuple[date, ...]:
        return tuple(
            getattr(result, "trading_date") for result in self.replay_results
        )

    def daily_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for result in self.replay_results:
            rows.append(
                {
                    "Trading Date": getattr(result, "trading_date").isoformat(),
                    "Bundles": int(getattr(result, "active_signals", 0)),
                    "TAKE": int(getattr(result, "approved", 0)),
                    "WAIT": int(getattr(result, "waiting", 0)),
                    "BLOCK": int(getattr(result, "blocked", 0)),
                    "Wins": int(getattr(result, "winners", 0)),
                    "Losses": int(getattr(result, "losers", 0)),
                    "Correct Skips": int(getattr(result, "correct_skips", 0)),
                    "Accuracy %": round(
                        float(getattr(result, "decision_accuracy_pct", 0.0)), 2
                    ),
                    "Net Option Points": round(
                        float(getattr(result, "net_points", 0.0)), 3
                    ),
                }
            )
        return rows

    def attempt_rows(self) -> list[dict[str, object]]:
        return [attempt.as_dict() for attempt in self.attempts]


def run_latest_ready_dri_window(
    available_dates: Iterable[date],
    *,
    end_date: date,
    requested_days: int,
    validate_day: Callable[[date], object],
    run_day: Callable[[date], object],
    progress_callback: Callable[[int, int, date, str], None] | None = None,
) -> HistoricalDRIReplayWindow:
    """Collect the latest successful replay days without changing strategy logic.

    Dates are inspected newest-first up to ``end_date``. A date contributes only
    when option replay coverage is ready and the existing DRI replay completes.
    Failed or incomplete dates are retained as diagnostics while the scan keeps
    moving backward until the requested number of successful days is collected.
    """

    target = int(requested_days)
    if target <= 0:
        raise ValueError("requested_days must be greater than zero")

    candidates = sorted(
        {candidate for candidate in available_dates if candidate <= end_date},
        reverse=True,
    )
    attempts: list[HistoricalDRIWindowAttempt] = []
    successful: list[object] = []

    for candidate in candidates:
        if len(successful) >= target:
            break
        if progress_callback is not None:
            progress_callback(len(successful), target, candidate, "CHECKING")

        try:
            coverage = validate_day(candidate)
        except Exception as exc:
            attempts.append(
                HistoricalDRIWindowAttempt(
                    candidate,
                    "VALIDATION_FAILED",
                    f"{type(exc).__name__}: {exc}",
                )
            )
            if progress_callback is not None:
                progress_callback(
                    len(successful), target, candidate, "VALIDATION_FAILED"
                )
            continue

        if not bool(getattr(coverage, "replay_ready", False)):
            reason = str(
                getattr(coverage, "reason", "Option replay is not ready.")
            )
            attempts.append(
                HistoricalDRIWindowAttempt(candidate, "NOT_READY", reason)
            )
            if progress_callback is not None:
                progress_callback(len(successful), target, candidate, "NOT_READY")
            continue

        try:
            result = run_day(candidate)
        except Exception as exc:
            attempts.append(
                HistoricalDRIWindowAttempt(
                    candidate,
                    "REPLAY_FAILED",
                    f"{type(exc).__name__}: {exc}",
                )
            )
            if progress_callback is not None:
                progress_callback(len(successful), target, candidate, "REPLAY_FAILED")
            continue

        successful.append(result)
        attempts.append(HistoricalDRIWindowAttempt(candidate, "REPLAYED"))
        if progress_callback is not None:
            progress_callback(len(successful), target, candidate, "REPLAYED")

    ordered_results = tuple(
        sorted(
            successful,
            key=lambda result: getattr(result, "trading_date"),
        )
    )
    report = analyze_historical_dri_risk_consistency(ordered_results)
    return HistoricalDRIReplayWindow(
        requested_days=target,
        replay_results=ordered_results,
        attempts=tuple(attempts),
        report=report,
    )
