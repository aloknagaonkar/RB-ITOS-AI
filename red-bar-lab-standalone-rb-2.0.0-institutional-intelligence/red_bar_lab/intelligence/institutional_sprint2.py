from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.institutional_flow import InstitutionalOptionFlowEngine
from red_bar_lab.intelligence.oi_velocity import OIVelocityEngine, OIVelocityMetric
from red_bar_lab.intelligence.premium_flow import PremiumFlowEngine, PremiumFlowMetric
from red_bar_lab.intelligence.strike_rotation import StrikeRotationEngine, StrikeRotationResult
from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine, BuySellStrength
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
        usable = []
        for meta in history:
            if str(meta.get("collector_mode") or "").upper() != "ONLINE":
                continue
            frame = self._artifact(meta.get("chain_artifact_path"))
            if frame.empty:
                continue
            ts = pd.Timestamp(meta.get("snapshot_timestamp"))
            if pd.isna(ts):
                continue
            usable.append((ts, dict(meta), frame))
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
                None,
                None,
                None,
                empty_flow,
                (),
                (),
                rotation,
                strength,
                confidence,
                len(snapshots),
                "WAITING",
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
        rotation = StrikeRotationEngine.evaluate(current, previous)
        velocity_by_key = {(r.strike, r.option_type): r for r in velocity}
        strength = BuySellStrengthEngine.evaluate(flow.rows, velocity_by_key)
        confidence = InstitutionalConfidenceEngine.evaluate(
            strength,
            flow.rows,
            velocity,
            premium,
            rotation,
        )
        return InstitutionalSprint2Snapshot(
            current_ts.isoformat(),
            previous_ts.isoformat(),
            flow.option_expiry,
            flow,
            velocity,
            premium,
            rotation,
            strength,
            confidence,
            len(snapshots),
            "READY" if flow.status == "READY" else "WAITING",
            f"Used {len(snapshots)} ONLINE snapshots; execution impact remains NONE.",
        )
