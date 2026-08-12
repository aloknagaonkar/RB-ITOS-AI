from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class OIVelocityMetric:
    strike: float
    option_type: str
    oi: float | None
    change_1m_pct: float | None
    change_5m_pct: float | None
    change_15m_pct: float | None
    acceleration_pct: float | None
    state: str

    def as_dict(self) -> dict[str, object]:
        return {
            "Strike": self.strike,
            "Side": self.option_type,
            "OI": self.oi,
            "OI Velocity 1m %": self.change_1m_pct,
            "OI Velocity 5m %": self.change_5m_pct,
            "OI Velocity 15m %": self.change_15m_pct,
            "OI Acceleration": self.acceleration_pct,
            "OI Velocity State": self.state,
        }


class OIVelocityEngine:
    """Point-in-time OI velocity from persisted option-chain snapshots only."""

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
    def _frame_at_or_before(
        snapshots: list[tuple[pd.Timestamp, pd.DataFrame]], target: pd.Timestamp
    ) -> pd.DataFrame | None:
        eligible = [frame for ts, frame in snapshots if ts <= target]
        return eligible[-1] if eligible else None

    @staticmethod
    def _row(frame: pd.DataFrame | None, strike: float) -> pd.Series | None:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return None
        strikes = pd.to_numeric(frame["strike"], errors="coerce")
        match = frame.loc[(strikes - float(strike)).abs() < 1e-6]
        return None if match.empty else match.iloc[0]

    @classmethod
    def _oi(cls, frame: pd.DataFrame | None, strike: float, option_type: str) -> float | None:
        row = cls._row(frame, strike)
        if row is None:
            return None
        prefix = "call" if option_type == "CE" else "put"
        return cls._num(row.get(f"{prefix}_oi"))

    @staticmethod
    def classify(change_1m: float | None, change_5m: float | None, change_15m: float | None) -> str:
        values = [v for v in (change_1m, change_5m, change_15m) if v is not None]
        if not values:
            return "UNKNOWN"
        if abs(change_1m or 0.0) < 0.25 and abs(change_5m or 0.0) < 0.75:
            return "STABLE"
        same_positive = (change_1m or 0.0) > 0 and (change_5m or 0.0) > 0
        same_negative = (change_1m or 0.0) < 0 and (change_5m or 0.0) < 0
        if same_positive and abs(change_1m or 0.0) * 5 > abs(change_5m or 0.0) * 1.20:
            return "ACCELERATING_UP"
        if same_negative and abs(change_1m or 0.0) * 5 > abs(change_5m or 0.0) * 1.20:
            return "ACCELERATING_DOWN"
        if change_1m is not None and change_5m is not None and change_1m * change_5m < 0:
            return "REVERSING"
        if same_positive:
            return "RISING"
        if same_negative:
            return "FALLING"
        return "MIXED"

    @classmethod
    def evaluate(
        cls,
        snapshots: Iterable[tuple[pd.Timestamp, pd.DataFrame]],
        *,
        strikes: Iterable[float] | None = None,
    ) -> tuple[OIVelocityMetric, ...]:
        ordered = sorted(
            ((pd.Timestamp(ts), frame) for ts, frame in snapshots if frame is not None and not frame.empty),
            key=lambda item: item[0],
        )
        if not ordered:
            return ()
        latest_ts, latest = ordered[-1]
        if strikes is None:
            if "strike" not in latest.columns:
                return ()
            strike_values = pd.to_numeric(latest["strike"], errors="coerce").dropna().tolist()
        else:
            strike_values = [float(v) for v in strikes]

        frame_1m = cls._frame_at_or_before(ordered, latest_ts - pd.Timedelta(minutes=1))
        frame_5m = cls._frame_at_or_before(ordered, latest_ts - pd.Timedelta(minutes=5))
        frame_15m = cls._frame_at_or_before(ordered, latest_ts - pd.Timedelta(minutes=15))
        result: list[OIVelocityMetric] = []
        for strike in sorted(set(float(v) for v in strike_values)):
            for side in ("CE", "PE"):
                current = cls._oi(latest, strike, side)
                c1 = cls._pct(current, cls._oi(frame_1m, strike, side))
                c5 = cls._pct(current, cls._oi(frame_5m, strike, side))
                c15 = cls._pct(current, cls._oi(frame_15m, strike, side))
                acceleration = None
                if c1 is not None and c5 is not None:
                    acceleration = c1 - (c5 / 5.0)
                result.append(OIVelocityMetric(
                    strike=round(strike, 2), option_type=side, oi=current,
                    change_1m_pct=round(c1, 3) if c1 is not None else None,
                    change_5m_pct=round(c5, 3) if c5 is not None else None,
                    change_15m_pct=round(c15, 3) if c15 is not None else None,
                    acceleration_pct=round(acceleration, 3) if acceleration is not None else None,
                    state=cls.classify(c1, c5, c15),
                ))
        return tuple(result)
