from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class PremiumFlowMetric:
    strike: float
    option_type: str
    premium: float | None
    change_1m_pct: float | None
    change_5m_pct: float | None
    change_15m_pct: float | None
    state: str
    strength_pct: float

    def as_dict(self) -> dict[str, object]:
        return {
            "Strike": self.strike,
            "Side": self.option_type,
            "Premium": self.premium,
            "Premium Velocity 1m %": self.change_1m_pct,
            "Premium Velocity 5m %": self.change_5m_pct,
            "Premium Velocity 15m %": self.change_15m_pct,
            "Premium Flow": self.state,
            "Premium Strength %": self.strength_pct,
        }


class PremiumFlowEngine:
    """Premium expansion/compression/exhaustion using captured point-in-time chains."""

    @staticmethod
    def _num(value: object) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pct(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / abs(previous) * 100.0

    @staticmethod
    def _at_or_before(snapshots, target):
        frames = [frame for ts, frame in snapshots if ts <= target]
        return frames[-1] if frames else None

    @classmethod
    def _premium(cls, frame: pd.DataFrame | None, strike: float, side: str) -> float | None:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return None
        strikes = pd.to_numeric(frame["strike"], errors="coerce")
        match = frame.loc[(strikes - float(strike)).abs() < 1e-6]
        if match.empty:
            return None
        prefix = "call" if side == "CE" else "put"
        return cls._num(match.iloc[0].get(f"{prefix}_ltp"))

    @staticmethod
    def classify(change_1m: float | None, change_5m: float | None, change_15m: float | None) -> str:
        if change_1m is None and change_5m is None:
            return "UNKNOWN"
        c1, c5, c15 = change_1m or 0.0, change_5m or 0.0, change_15m or 0.0
        if abs(c1) < 0.20 and abs(c5) < 0.60:
            return "COMPRESSION"
        if c5 > 1.0 and c1 > 0:
            if c15 > 0 and c5 > max(1.0, c15 / 3.0):
                return "EXPANSION_ACCELERATING"
            return "EXPANSION"
        if c5 < -1.0 and c1 < 0:
            return "DECAY"
        if c5 > 1.0 and c1 < 0:
            return "EXHAUSTION"
        if c5 < -1.0 and c1 > 0:
            return "REVERSAL_EXPANSION"
        return "MIXED"

    @staticmethod
    def strength(change_1m: float | None, change_5m: float | None) -> float:
        c1 = abs(change_1m or 0.0)
        c5 = abs(change_5m or 0.0)
        return round(min(100.0, c1 * 12.0 + c5 * 4.0), 2)

    @classmethod
    def evaluate(cls, snapshots: Iterable[tuple[pd.Timestamp, pd.DataFrame]]) -> tuple[PremiumFlowMetric, ...]:
        ordered = sorted(
            ((pd.Timestamp(ts), frame) for ts, frame in snapshots if frame is not None and not frame.empty),
            key=lambda item: item[0],
        )
        if not ordered:
            return ()
        latest_ts, latest = ordered[-1]
        if "strike" not in latest.columns:
            return ()
        strikes = pd.to_numeric(latest["strike"], errors="coerce").dropna().unique().tolist()
        f1 = cls._at_or_before(ordered, latest_ts - pd.Timedelta(minutes=1))
        f5 = cls._at_or_before(ordered, latest_ts - pd.Timedelta(minutes=5))
        f15 = cls._at_or_before(ordered, latest_ts - pd.Timedelta(minutes=15))
        result: list[PremiumFlowMetric] = []
        for strike in sorted(float(v) for v in strikes):
            for side in ("CE", "PE"):
                current = cls._premium(latest, strike, side)
                c1 = cls._pct(current, cls._premium(f1, strike, side))
                c5 = cls._pct(current, cls._premium(f5, strike, side))
                c15 = cls._pct(current, cls._premium(f15, strike, side))
                result.append(PremiumFlowMetric(
                    round(strike, 2), side, current,
                    round(c1, 3) if c1 is not None else None,
                    round(c5, 3) if c5 is not None else None,
                    round(c15, 3) if c15 is not None else None,
                    cls.classify(c1, c5, c15), cls.strength(c1, c5),
                ))
        return tuple(result)
