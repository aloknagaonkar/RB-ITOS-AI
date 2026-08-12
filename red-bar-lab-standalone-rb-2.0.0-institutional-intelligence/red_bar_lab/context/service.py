from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from red_bar_lab.context.market_context import (
    build_market_context_snapshot,
    write_market_context_csv,
)


@dataclass(frozen=True)
class MarketContextReport:
    signals_found: int
    snapshots_built: int
    skipped: int
    output_path: Path


class RedBarMarketContextService:
    def __init__(self, historical, database, settings):
        self.historical = historical
        self.database = database
        self.settings = settings

    def build_for_range(
        self,
        instrument_key: str,
        date_from: date,
        date_to: date,
    ):
        signals = self.database.read_signal_attempts_range(
            instrument_key,
            date_from.isoformat(),
            date_to.isoformat(),
        )
        available = set(
            self.historical.available_dates(
                instrument_key, interval_minutes=1
            )
        )

        snapshots = []
        skipped = 0

        for signal in signals:
            if not signal.get("confirmation_timestamp"):
                continue

            trading_date = date.fromisoformat(str(signal["trading_date"]))
            if trading_date not in available:
                skipped += 1
                continue

            prior = sorted(day for day in available if day < trading_date)
            prior_day = prior[-1] if prior else None

            current = self.historical.read_day(
                instrument_key,
                trading_date,
                interval_minutes=1,
            )
            previous = (
                self.historical.read_day(
                    instrument_key,
                    prior_day,
                    interval_minutes=1,
                )
                if prior_day is not None else None
            )

            try:
                snapshot = build_market_context_snapshot(
                    signal=signal,
                    instrument_key=instrument_key,
                    current_day=current,
                    previous_day=previous,
                )
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue

            snapshots.append(snapshot)

        output = (
            self.settings.artifacts_root
            / "context"
            / instrument_key.replace("|", "_")
            / (
                f"market_context_{date_from.isoformat()}_"
                f"{date_to.isoformat()}.csv"
            )
        )
        write_market_context_csv(snapshots, output)
        self.database.upsert_market_context_snapshots(snapshots)

        return snapshots, MarketContextReport(
            signals_found=len(signals),
            snapshots_built=len(snapshots),
            skipped=skipped,
            output_path=output,
        )
