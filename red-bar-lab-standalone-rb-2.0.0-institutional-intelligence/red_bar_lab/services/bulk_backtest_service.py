from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.strategy.level_engine import build_daily_levels
from red_bar_lab.strategy.signal_engine import scan_reference_levels
from red_bar_lab.strategy.trade_engine import evaluate_active_signals


@dataclass(frozen=True)
class BulkBacktestDayResult:
    trading_date: date
    levels: int
    attempts: int
    active: int
    trades: int
    status: str
    message: str = ""


@dataclass(frozen=True)
class BulkBacktestResult:
    start_date: date
    end_date: date
    processed_days: tuple[BulkBacktestDayResult, ...]
    skipped_days: tuple[BulkBacktestDayResult, ...]

    @property
    def trading_days_processed(self) -> int:
        return len(self.processed_days)

    @property
    def total_active_signals(self) -> int:
        return sum(item.active for item in self.processed_days)

    @property
    def total_trade_models(self) -> int:
        return sum(item.trades for item in self.processed_days)


class BulkHistoricalBacktestService:
    """Run the Red Bar historical pipeline across a cached date range.

    The bulk runner intentionally uses only locally cached one-minute candles.
    It does not call Upstox. Missing dates are skipped and reported so data
    acquisition remains a separate, explicit step.
    """

    def __init__(
        self,
        historical: RedBarHistoricalService,
        database: RedBarDatabase,
        *,
        progress_callback: Callable[[int, int, date], None] | None = None,
    ) -> None:
        self.historical = historical
        self.database = database
        self.progress_callback = progress_callback

    def run(
        self,
        instrument_key: str,
        start_date: date,
        end_date: date,
    ) -> BulkBacktestResult:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        cached_dates = [
            day
            for day in self.historical.available_dates(
                instrument_key, interval_minutes=1
            )
            if start_date <= day <= end_date
        ]

        processed: list[BulkBacktestDayResult] = []
        skipped: list[BulkBacktestDayResult] = []
        total = len(cached_dates)

        for idx, trading_date in enumerate(cached_dates, start=1):
            if self.progress_callback:
                self.progress_callback(idx, total, trading_date)

            current = self.historical.read_day(
                instrument_key, trading_date, interval_minutes=1
            )
            if current.empty:
                skipped.append(
                    BulkBacktestDayResult(
                        trading_date, 0, 0, 0, 0,
                        "SKIPPED", "Cached candle file is empty."
                    )
                )
                continue

            previous_dates = [
                day
                for day in self.historical.available_dates(
                    instrument_key, interval_minutes=1
                )
                if day < trading_date
            ][-10:]

            previous = [
                (
                    day,
                    self.historical.read_day(
                        instrument_key, day, interval_minutes=1
                    ),
                )
                for day in previous_dates
            ]

            daily = build_daily_levels(
                trading_date,
                current,
                previous,
                previous_days=10,
            )
            levels = list(daily.previous_day_levels)
            levels.extend(
                level
                for level in (
                    daily.first_candle,
                    daily.next_red_candle,
                    daily.mid_session_candle,
                )
                if level is not None
            )

            if not levels:
                skipped.append(
                    BulkBacktestDayResult(
                        trading_date, 0, 0, 0, 0,
                        "SKIPPED", "No reference levels could be built."
                    )
                )
                continue

            self.database.replace_reference_levels(
                instrument_key,
                trading_date.isoformat(),
                levels,
            )

            scan = scan_reference_levels(current, levels)
            self.database.replace_signal_attempts(
                "BULK_BACKTEST",
                instrument_key,
                trading_date.isoformat(),
                scan.attempts,
            )

            trades = evaluate_active_signals(
                current,
                scan.active,
                instrument_key=instrument_key,
                trading_date=trading_date.isoformat(),
            )
            self.database.replace_paper_trade_outcomes(
                instrument_key,
                trading_date.isoformat(),
                trades,
            )

            processed.append(
                BulkBacktestDayResult(
                    trading_date=trading_date,
                    levels=len(levels),
                    attempts=len(scan.attempts),
                    active=len(scan.active),
                    trades=len(trades),
                    status="COMPLETE",
                )
            )

        return BulkBacktestResult(
            start_date=start_date,
            end_date=end_date,
            processed_days=tuple(processed),
            skipped_days=tuple(skipped),
        )
