from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from red_bar_lab.context.volume_structure import (
    build_volume_structure_snapshot,
    write_volume_structure_csv,
)
from red_bar_lab.services.candle_selection_outcome import build_candle_enrichment_outcome
from red_bar_lab.services.candle_source_adapters import (
    build_historical_candle_reader,
    build_live_persisted_candle_reader,
)
from red_bar_lab.services.point_in_time_candle_source import (
    select_point_in_time_completed_candles,
)
from red_bar_lab.services.signal_enrichment_outcome_store import (
    persist_signal_enrichment_outcomes,
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
        self.live_reader = build_live_persisted_candle_reader(settings)
        self.historical_reader = build_historical_candle_reader(historical)

    def build_for_range(self, instrument_key: str, date_from: date, date_to: date):
        signals = self.database.read_signal_attempts_range(
            instrument_key, date_from.isoformat(), date_to.isoformat()
        )
        snapshots = []
        outcomes = []
        skipped = 0

        for signal in signals:
            confirmation = signal.get("confirmation_timestamp")
            signal_id = str(signal.get("signal_id") or "").strip()
            if not confirmation or not signal_id:
                continue

            selection = select_point_in_time_completed_candles(
                instrument_key=instrument_key,
                timeframe="1m",
                cutoff_timestamp=confirmation,
                live_reader=self.live_reader,
                historical_reader=self.historical_reader,
                current_date=date.today(),
            )
            outcomes.append(
                build_candle_enrichment_outcome(
                    signal_id=signal_id,
                    stage="VOLUME",
                    selection=selection,
                    attempt_timestamp=str(confirmation),
                )
            )
            if selection.status != "READY":
                skipped += 1
                continue

            try:
                snapshot = build_volume_structure_snapshot(
                    signal=signal,
                    instrument_key=instrument_key,
                    current_day=pd.DataFrame(selection.rows),
                )
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue
            snapshots.append(snapshot)

        output = (
            self.settings.artifacts_root
            / "context"
            / instrument_key.replace("|", "_")
            / f"volume_structure_{date_from.isoformat()}_{date_to.isoformat()}.csv"
        )
        write_volume_structure_csv(snapshots, output)
        self.database.upsert_volume_structure_snapshots(snapshots)
        if outcomes:
            persist_signal_enrichment_outcomes(self.settings.database_path, outcomes)

        return snapshots, VolumeStructureReport(
            signals_found=len(signals),
            snapshots_built=len(snapshots),
            skipped=skipped,
            output_path=output,
        )
