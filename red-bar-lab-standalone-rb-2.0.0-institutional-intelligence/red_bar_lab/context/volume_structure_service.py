from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from red_bar_lab.context.volume_structure import (
    build_volume_structure_snapshot,
    write_volume_structure_csv,
)


@dataclass(frozen=True)
class VolumeStructureReport:
    signals_found: int
    snapshots_built: int
    skipped: int
    output_path: Path


class RedBarVolumeStructureService:
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
                instrument_key,
                interval_minutes=1,
            )
        )

        snapshots = []
        skipped = 0

        for signal in signals:
            if not signal.get("confirmation_timestamp"):
                continue

            trading_date = date.fromisoformat(
                str(signal["trading_date"])
            )
            if trading_date not in available:
                skipped += 1
                continue

            current = self.historical.read_day(
                instrument_key,
                trading_date,
                interval_minutes=1,
            )

            try:
                snapshot = build_volume_structure_snapshot(
                    signal=signal,
                    instrument_key=instrument_key,
                    current_day=current,
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
                f"volume_structure_{date_from.isoformat()}_"
                f"{date_to.isoformat()}.csv"
            )
        )
        write_volume_structure_csv(snapshots, output)
        self.database.upsert_volume_structure_snapshots(snapshots)

        return snapshots, VolumeStructureReport(
            signals_found=len(signals),
            snapshots_built=len(snapshots),
            skipped=skipped,
            output_path=output,
        )
