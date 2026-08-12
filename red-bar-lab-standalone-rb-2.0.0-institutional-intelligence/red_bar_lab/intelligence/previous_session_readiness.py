from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.previous_session_context import (
    PreviousSessionContextService,
    PreviousSessionHistoricalAdapter,
    PreviousSessionReadiness,
)


class PreviousSessionReadinessResolver(PreviousSessionHistoricalAdapter):
    """Resolve Sprint-3 readiness using the same trust rules as context selection.

    Database trading_date metadata alone is not sufficient. A persisted snapshot is
    counted only when its actual snapshot_timestamp is before the selected trading
    date, its source is trusted, and its chain artifact exists and is readable.
    Readiness is evaluated for the latest usable completed session, never by counting
    unrelated/current/future rows returned by a broad database query.
    """

    @staticmethod
    def _timestamp(row: dict[str, object]) -> pd.Timestamp | None:
        try:
            ts = pd.Timestamp(row.get("snapshot_timestamp"))
        except Exception:
            return None
        if pd.isna(ts):
            return None
        return ts.tz_localize("Asia/Kolkata") if ts.tzinfo is None else ts.tz_convert("Asia/Kolkata")

    @staticmethod
    def _artifact_valid(row: dict[str, object]) -> bool:
        path_value = row.get("chain_artifact_path")
        if not path_value:
            return False
        try:
            path = Path(str(path_value))
            if not path.exists():
                return False
            frame = pd.read_csv(path)
            return not frame.empty and "strike" in frame.columns
        except Exception:
            return False

    @classmethod
    def _trusted_rows_before(
        cls,
        rows: list[dict[str, object]],
        target: date,
    ) -> list[tuple[pd.Timestamp, str, dict[str, object]]]:
        usable: list[tuple[pd.Timestamp, str, dict[str, object]]] = []
        for raw in rows:
            row = dict(raw)
            mode = str(row.get("collector_mode") or "").upper()
            if mode != "ONLINE" and mode not in PreviousSessionContextService.TRUSTED_HISTORICAL_MODES:
                continue
            ts = cls._timestamp(row)
            if ts is None or ts.date() >= target:
                continue
            if not cls._artifact_valid(row):
                continue
            source = "ONLINE" if mode == "ONLINE" else "HISTORICAL"
            usable.append((ts, source, row))
        return usable

    def ensure_previous_session(self, instrument_key: str, trading_date: str) -> PreviousSessionReadiness:
        target = date.fromisoformat(str(trading_date))
        history = self.database.read_option_chain_history(
            instrument_key,
            (target - timedelta(days=21)).isoformat(),
            (target - timedelta(days=1)).isoformat(),
            limit=5000,
        )
        usable = self._trusted_rows_before([dict(row) for row in history], target)

        if usable:
            previous_date = max(item[0].date() for item in usable)
            same_day = [item for item in usable if item[0].date() == previous_date]
            online = [item for item in same_day if item[1] == "ONLINE"]
            historical = [item for item in same_day if item[1] == "HISTORICAL"]
            selected = online if online else historical
            source = "ONLINE" if online else "HISTORICAL"
            return PreviousSessionReadiness(
                target.isoformat(),
                previous_date.isoformat(),
                len(online),
                len(historical),
                0,
                0,
                "READY",
                f"Trustworthy {source} snapshots exist for completed previous session {previous_date.isoformat()}; "
                f"{len(selected)} snapshot(s) are available to Sprint 3.",
            )

        # No trustworthy persisted session exists. Bypass the legacy broad-count
        # readiness shortcut and inspect the historical artifact store directly.
        artifact_day, manifest = self._find_previous_artifact_day(instrument_key, target)
        contracts = [row for row in manifest.get("contracts", []) if isinstance(row, dict)]
        if artifact_day is None or not contracts:
            return PreviousSessionReadiness(
                target.isoformat(),
                None,
                0,
                0,
                0,
                0,
                "BACKFILL_REQUIRED",
                "No trustworthy persisted previous-session snapshots and no local historical option-contract artifacts were found. "
                "Run Historical Option Sync for a prior completed trading session.",
            )

        chains = self._build_timestamp_chains(instrument_key, artifact_day, contracts)
        if len(chains) < 2:
            return PreviousSessionReadiness(
                target.isoformat(),
                artifact_day.isoformat(),
                0,
                0,
                len(contracts),
                0,
                "ARTIFACTS_INCOMPLETE",
                "Historical contracts exist, but fewer than two complete CE/PE one-minute chain timestamps could be reconstructed.",
            )

        selected = sorted(chains)[-2:]
        for ts in selected:
            self._persist_snapshot(
                instrument_key,
                artifact_day,
                str(manifest.get("expiry") or "") or None,
                ts,
                chains[ts],
            )
        return PreviousSessionReadiness(
            target.isoformat(),
            artifact_day.isoformat(),
            0,
            2,
            len(contracts),
            2,
            "ADAPTED",
            f"Adapted the final two trustworthy one-minute historical option-chain snapshots from {artifact_day.isoformat()} "
            "and persisted them as HISTORICAL.",
        )
