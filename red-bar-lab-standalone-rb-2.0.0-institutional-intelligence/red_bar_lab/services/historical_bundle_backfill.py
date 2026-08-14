from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from typing import Mapping
import hashlib

import pandas as pd

from red_bar_lab.intelligence.stateful_multitimeframe_regime import (
    StatefulMultiTimeframeRegimeEngine,
)
from red_bar_lab.intelligence.transition_sequence_state_machine import (
    TransitionSequenceStateMachine,
)
from red_bar_lab.intelligence.fresh_setup_signal_engine import (
    FreshSetupSignalEngine,
)
from red_bar_lab.services.attribution_context import build_attribution_context
from red_bar_lab.services.fresh_setup_bundle import build_setup_bundles
from red_bar_lab.services.fresh_setup_bundle_store import (
    FreshSetupBundleStore,
    canonical_bundle_identity,
)
from red_bar_lab.services.fresh_setup_signal_store import FreshSetupSignalStore
from red_bar_lab.services.stateful_regime_store import StatefulRegimeStore
from red_bar_lab.services.transition_sequence_store import TransitionSequenceStore


@dataclass(frozen=True)
class HistoricalBundleBackfillRequest:
    instrument_key: str
    date_from: date
    date_to: date
    start_time: time
    end_time: time
    persist_artifacts: bool = True
    maximum_days: int = 90

    def validate(self) -> None:
        if self.date_to < self.date_from:
            raise ValueError("End date must be on or after start date.")
        days = (self.date_to - self.date_from).days + 1
        if days > self.maximum_days:
            raise ValueError(
                f"Range contains {days} calendar days; maximum is "
                f"{self.maximum_days}."
            )
        if self.end_time < self.start_time:
            raise ValueError("End time must be after start time.")


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(
        result["timestamp"], errors="coerce"
    )
    return (
        result.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _deterministic_transition_id(
    direction: str,
    started_at: str,
) -> str:
    raw = f"{direction}|{started_at}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    stamp = (
        started_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
    )
    return f"TRH-{direction[:4]}-{stamp}-{digest}"


class HistoricalV43BundleBackfill:
    """Generate missing v4.3 research artifacts from historical candles.

    Candidate, opportunity, Committee, queue and order tables are never
    written. Only v4.3 research JSONL artifacts may be persisted.
    """

    def __init__(self, *, historical, layout):
        self.historical = historical
        self.layout = layout

    def run(
        self,
        request: HistoricalBundleBackfillRequest,
    ) -> dict[str, object]:
        request.validate()
        safe = self.layout._safe_instrument(request.instrument_key)

        regime_store = StatefulRegimeStore(
            self.layout.settings.runs_root
            / "stateful_regime_v43"
            / f"{safe}.jsonl"
        )
        transition_store = TransitionSequenceStore(
            self.layout.settings.runs_root
            / "transition_sequence_v43"
            / f"{safe}.jsonl"
        )
        signal_store = FreshSetupSignalStore(
            self.layout.settings.runs_root
            / "fresh_setup_signals_v43"
            / f"{safe}.jsonl"
        )
        bundle_store = FreshSetupBundleStore(
            self.layout.settings.runs_root
            / "fresh_setup_bundles_v43"
            / f"{safe}.jsonl"
        )

        existing_rows = bundle_store.read_all()
        existing_bundle_ids = {
            str(row.get("bundle_id") or "")
            for row in existing_rows
        }
        existing_canonical = {
            canonical_bundle_identity(row)
            for row in existing_rows
        }

        result_rows: list[dict[str, object]] = []
        totals = {
            "days_requested": 0,
            "days_with_candles": 0,
            "days_without_candles": 0,
            "bars_evaluated": 0,
            "snapshots_generated": 0,
            "transitions_generated": 0,
            "signals_generated": 0,
            "bundles_generated": 0,
            "bundles_inserted": 0,
            "bundles_skipped_existing": 0,
        }

        current = request.date_from
        previous_snapshot: Mapping[str, object] | None = None
        previous_transition: Mapping[str, object] | None = None

        while current <= request.date_to:
            totals["days_requested"] += 1
            if current.weekday() >= 5:
                result_rows.append({
                    "trading_date": current.isoformat(),
                    "status": "WEEKEND_SKIPPED",
                    "one_minute_rows": 0,
                    "five_minute_rows": 0,
                    "bars_evaluated": 0,
                    "bundles_generated": 0,
                    "bundles_inserted": 0,
                    "execution_allowed": False,
                })
                current += timedelta(days=1)
                continue

            self.historical.load_or_download(
                request.instrument_key,
                current,
                current,
                interval_minutes=1,
                force=False,
            )
            self.historical.load_or_download(
                request.instrument_key,
                current,
                current,
                interval_minutes=5,
                force=False,
            )
            one = _prepare(
                self.historical.read_day(
                    request.instrument_key,
                    current,
                    interval_minutes=1,
                )
            )
            five = _prepare(
                self.historical.read_day(
                    request.instrument_key,
                    current,
                    interval_minutes=5,
                )
            )

            if one.empty or five.empty:
                totals["days_without_candles"] += 1
                result_rows.append({
                    "trading_date": current.isoformat(),
                    "status": "NO_CANDLE_DATA",
                    "one_minute_rows": len(one),
                    "five_minute_rows": len(five),
                    "bars_evaluated": 0,
                    "bundles_generated": 0,
                    "bundles_inserted": 0,
                    "execution_allowed": False,
                })
                current += timedelta(days=1)
                continue

            totals["days_with_candles"] += 1
            day_evaluated = day_bundles = day_inserted = 0

            for index in range(34, len(five)):
                five_slice = five.iloc[: index + 1].copy()
                five_ts = pd.Timestamp(
                    five_slice.iloc[-1]["timestamp"]
                )
                local_time = five_ts.time().replace(tzinfo=None)
                if not (
                    request.start_time
                    <= local_time
                    <= request.end_time
                ):
                    continue

                one_cutoff = five_ts + pd.Timedelta(minutes=4)
                one_slice = one.loc[
                    one["timestamp"] <= one_cutoff
                ].copy()
                if len(one_slice) < 35:
                    continue

                snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
                    one_slice,
                    five_slice,
                    previous_state=previous_snapshot,
                ).as_record()
                snapshot["instrument_key"] = request.instrument_key
                snapshot["historical_backfill"] = True
                snapshot["source_read_only"] = True

                transition = TransitionSequenceStateMachine().advance(
                    snapshot,
                    previous=previous_transition,
                )
                if transition is None:
                    previous_snapshot = snapshot
                    continue

                transition_record = transition.as_record()
                transition_record["transition_id"] = (
                    _deterministic_transition_id(
                        str(transition_record.get("direction") or ""),
                        str(transition_record.get("started_at") or ""),
                    )
                )
                transition_record["historical_backfill"] = True
                transition_record["source_read_only"] = True

                attribution = build_attribution_context(
                    snapshot,
                    transition_record,
                ).as_record()
                signals = FreshSetupSignalEngine().detect(
                    snapshot,
                    transition_record,
                    attribution,
                )
                signal_records = [
                    {
                        **signal.as_record(),
                        "historical_backfill": True,
                        "source_read_only": True,
                    }
                    for signal in signals
                ]
                bundle_records = [
                    {
                        **bundle.as_record(),
                        "instrument_key": request.instrument_key,
                        "historical_backfill": True,
                        "source_read_only": True,
                    }
                    for bundle in build_setup_bundles(signal_records)
                ]

                day_evaluated += 1
                totals["bars_evaluated"] += 1
                totals["snapshots_generated"] += 1
                totals["transitions_generated"] += 1
                totals["signals_generated"] += len(signal_records)
                totals["bundles_generated"] += len(bundle_records)
                day_bundles += len(bundle_records)

                if request.persist_artifacts:
                    regime_store.append_once(snapshot)
                    transition_store.append_once(transition_record)
                    signal_store.resolve_many_once(signal_records)
                    inserted = bundle_store.append_many_once(
                        bundle_records
                    )
                    day_inserted += inserted
                    totals["bundles_inserted"] += inserted
                    for bundle in bundle_records:
                        bundle_id = str(bundle.get("bundle_id") or "")
                        canonical = canonical_bundle_identity(bundle)
                        if (
                            bundle_id in existing_bundle_ids
                            or canonical in existing_canonical
                        ):
                            totals["bundles_skipped_existing"] += 1
                        else:
                            existing_bundle_ids.add(bundle_id)
                            existing_canonical.add(canonical)

                previous_snapshot = snapshot
                previous_transition = transition_record

            result_rows.append({
                "trading_date": current.isoformat(),
                "status": "PROCESSED",
                "one_minute_rows": len(one),
                "five_minute_rows": len(five),
                "bars_evaluated": day_evaluated,
                "bundles_generated": day_bundles,
                "bundles_inserted": day_inserted,
                "execution_allowed": False,
            })
            current += timedelta(days=1)

        return {
            "summary": {
                **totals,
                "persist_artifacts": request.persist_artifacts,
                "source_read_only": True,
                "execution_allowed": False,
            },
            "days": result_rows,
        }
