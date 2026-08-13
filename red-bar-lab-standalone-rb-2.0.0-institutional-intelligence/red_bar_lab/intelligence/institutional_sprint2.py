from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.institutional_flow import InstitutionalOptionFlowEngine
from red_bar_lab.intelligence.oi_velocity import OIVelocityEngine, OIVelocityMetric
from red_bar_lab.intelligence.premium_flow import PremiumFlowEngine, PremiumFlowMetric
from red_bar_lab.intelligence.strike_rotation import StrikeRotationEngine, StrikeRotationResult
from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine, BuySellStrength
from red_bar_lab.intelligence.contract_quality import ContractQualityEngine, ContractQualityMetric
from red_bar_lab.intelligence.institutional_confidence import (
    InstitutionalConfidenceEngine,
    InstitutionalConfidence,
)


@dataclass(frozen=True)
class InstitutionalSprint2Snapshot:
    snapshot_timestamp: str | None
    previous_snapshot_timestamp: str | None
    option_expiry: str | None
    flow: object
    oi_velocity: tuple[OIVelocityMetric, ...]
    premium_flow: tuple[PremiumFlowMetric, ...]
    contract_quality: tuple[ContractQualityMetric, ...]
    rotation: StrikeRotationResult
    strength: BuySellStrength
    confidence: InstitutionalConfidence
    snapshots_used: int
    status: str
    reason: str


class InstitutionalSprint2Service:
    """Read-only aggregation of live institutional intelligence.

    Inputs come only from persisted ONLINE option-chain snapshots. The service
    never writes candidate, order, committee, portfolio, queue or execution state.
    """

    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def _artifact(path_value: object) -> pd.DataFrame:
        if not path_value:
            return pd.DataFrame()
        try:
            path = Path(str(path_value))
            return pd.read_csv(path) if path.exists() else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    def _snapshots(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> list[tuple[pd.Timestamp, dict[str, object], pd.DataFrame]]:
        history = self.database.read_option_chain_history(
            instrument_key,
            trading_date,
            trading_date,
            limit=2000,
        )

        # Read cheap SQLite metadata for the session first. OI Velocity and
        # Premium Flow only require latest/previous plus point-in-time frames at
        # 1m, 5m and 15m lookbacks, so parsing every ONLINE CSV is unnecessary.
        metadata: list[tuple[pd.Timestamp, dict[str, object]]] = []
        for meta in history:
            if str(meta.get("collector_mode") or "").upper() != "ONLINE":
                continue
            try:
                ts = pd.Timestamp(meta.get("snapshot_timestamp"))
            except Exception:
                continue
            if pd.isna(ts):
                continue
            metadata.append((ts, dict(meta)))
        metadata.sort(key=lambda item: item[0])
        if not metadata:
            return []

        artifact_cache: dict[int, pd.DataFrame] = {}

        def load(index: int) -> pd.DataFrame:
            if index not in artifact_cache:
                artifact_cache[index] = self._artifact(
                    metadata[index][1].get("chain_artifact_path")
                )
            return artifact_cache[index]

        def usable_at_or_before(
            start_index: int,
            target: pd.Timestamp | None = None,
        ) -> int | None:
            for index in range(start_index, -1, -1):
                if target is not None and metadata[index][0] > target:
                    continue
                if not load(index).empty:
                    return index
            return None

        latest_index = usable_at_or_before(len(metadata) - 1)
        if latest_index is None:
            return []

        selected = {latest_index}
        previous_index = usable_at_or_before(latest_index - 1)
        if previous_index is not None:
            selected.add(previous_index)

        latest_ts = metadata[latest_index][0]
        for minutes in (1, 5, 15):
            reference_index = usable_at_or_before(
                latest_index - 1,
                latest_ts - pd.Timedelta(minutes=minutes),
            )
            if reference_index is not None:
                selected.add(reference_index)

        usable = [
            (metadata[index][0], metadata[index][1], load(index))
            for index in sorted(selected)
        ]
        usable.sort(key=lambda item: item[0])
        return usable

    def latest(self, instrument_key: str, trading_date: str) -> InstitutionalSprint2Snapshot:
        snapshots = self._snapshots(instrument_key, trading_date)
        if len(snapshots) < 2:
            empty_flow = InstitutionalOptionFlowEngine.evaluate_frames(
                pd.DataFrame(), pd.DataFrame()
            )
            rotation = StrikeRotationEngine.evaluate(pd.DataFrame(), pd.DataFrame())
            strength = BuySellStrengthEngine.evaluate(())
            confidence = InstitutionalConfidenceEngine.evaluate(
                strength, (), (), (), rotation
            )
            return InstitutionalSprint2Snapshot(
                None, None, None, empty_flow, (), (), (), rotation, strength,
                confidence, len(snapshots), "WAITING",
                "At least two ONLINE option-chain snapshots are required; 5-15 minutes of history improves velocity confidence.",
            )

        previous_ts, _, previous = snapshots[-2]
        current_ts, current_meta, current = snapshots[-1]
        flow = InstitutionalOptionFlowEngine.evaluate_frames(
            current,
            previous,
            snapshot_timestamp=current_ts.isoformat(),
            previous_snapshot_timestamp=previous_ts.isoformat(),
            option_expiry=str(current_meta.get("option_expiry") or "") or None,
        )
        time_series = [(ts, frame) for ts, _, frame in snapshots]
        velocity = OIVelocityEngine.evaluate(time_series)
        premium = PremiumFlowEngine.evaluate(time_series)
        quality = ContractQualityEngine.evaluate(current)
        rotation = StrikeRotationEngine.evaluate(current, previous)
        velocity_by_key = {(r.strike, r.option_type): r for r in velocity}
        quality_by_key = {(r.strike, r.option_type): r for r in quality}
        strength = BuySellStrengthEngine.evaluate(flow.rows, velocity_by_key, quality_by_key)
        confidence = InstitutionalConfidenceEngine.evaluate(
            strength,
            flow.rows,
            velocity,
            premium,
            rotation,
            quality_by_key,
        )
        return InstitutionalSprint2Snapshot(
            current_ts.isoformat(), previous_ts.isoformat(), flow.option_expiry,
            flow, velocity, premium, quality, rotation, strength, confidence,
            len(snapshots), "READY" if flow.status == "READY" else "WAITING",
            f"Used {len(snapshots)} ONLINE snapshots; contract-quality weighting is advisory and execution impact remains NONE.",
        )