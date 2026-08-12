from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StrikeRotationResult:
    call_center_previous: float | None
    call_center_current: float | None
    put_center_previous: float | None
    put_center_current: float | None
    call_shift_points: float | None
    put_shift_points: float | None
    state: str
    confidence_pct: float


class StrikeRotationEngine:
    """Detect where option OI concentration is migrating between snapshots."""

    @staticmethod
    def _center(frame: pd.DataFrame, prefix: str) -> float | None:
        if frame is None or frame.empty or "strike" not in frame.columns or f"{prefix}_oi" not in frame.columns:
            return None
        strike = pd.to_numeric(frame["strike"], errors="coerce")
        oi = pd.to_numeric(frame[f"{prefix}_oi"], errors="coerce").clip(lower=0)
        valid = strike.notna() & oi.notna() & (oi > 0)
        if not valid.any():
            return None
        weights = oi.loc[valid]
        return float((strike.loc[valid] * weights).sum() / weights.sum())

    @classmethod
    def evaluate(cls, current: pd.DataFrame, previous: pd.DataFrame) -> StrikeRotationResult:
        cc0, cc1 = cls._center(previous, "call"), cls._center(current, "call")
        pc0, pc1 = cls._center(previous, "put"), cls._center(current, "put")
        call_shift = None if cc0 is None or cc1 is None else cc1 - cc0
        put_shift = None if pc0 is None or pc1 is None else pc1 - pc0
        shifts = [abs(v) for v in (call_shift, put_shift) if v is not None]
        if not shifts:
            return StrikeRotationResult(cc0, cc1, pc0, pc1, call_shift, put_shift, "UNKNOWN", 0.0)
        magnitude = max(shifts)
        if magnitude < 10:
            state = "STABLE"
        elif (call_shift or 0) > 10 and (put_shift or 0) > 10:
            state = "UPWARD_ROTATION"
        elif (call_shift or 0) < -10 and (put_shift or 0) < -10:
            state = "DOWNWARD_ROTATION"
        else:
            state = "DIVERGENT_ROTATION"
        confidence = round(min(100.0, magnitude), 2)
        return StrikeRotationResult(
            round(cc0, 2) if cc0 is not None else None,
            round(cc1, 2) if cc1 is not None else None,
            round(pc0, 2) if pc0 is not None else None,
            round(pc1, 2) if pc1 is not None else None,
            round(call_shift, 2) if call_shift is not None else None,
            round(put_shift, 2) if put_shift is not None else None,
            state, confidence,
        )
