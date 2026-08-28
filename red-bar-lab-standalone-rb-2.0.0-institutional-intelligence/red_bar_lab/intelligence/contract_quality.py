from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from red_bar_lab.utils import safe_float


@dataclass(frozen=True)
class ContractQualityMetric:
    strike: float
    option_type: str
    premium: float | None
    oi: float | None
    volume: float | None
    inferred_atm: float | None
    atm_distance_points: float | None
    quality_score: float
    quality_band: str
    eligible: bool

    @property
    def weight(self) -> float:
        if not self.eligible:
            return 0.10
        return max(0.10, min(1.0, self.quality_score / 100.0))

    def as_dict(self) -> dict[str, object]:
        return {
            "Strike": self.strike,
            "Side": self.option_type,
            "Premium": self.premium,
            "OI": self.oi,
            "Volume": self.volume,
            "Inferred ATM": self.inferred_atm,
            "ATM Distance": self.atm_distance_points,
            "Contract Quality %": self.quality_score,
            "Quality Band": self.quality_band,
            "Qualified": self.eligible,
            "Contribution Weight": round(self.weight, 3),
        }


class ContractQualityEngine:
    """Advisory quality weighting for option-chain evidence."""

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
        return frame.to_dict(orient="records")

    @classmethod
    def infer_atm(cls, frame: pd.DataFrame) -> float | None:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return None
        best: tuple[float, float] | None = None
        for row in cls._records(frame):
            strike = safe_float(row.get("strike"))
            call = safe_float(row.get("call_ltp"))
            put = safe_float(row.get("put_ltp"))
            if strike is None or call is None or put is None or call <= 0 or put <= 0:
                continue
            candidate = (abs(call - put), strike)
            if best is None or candidate < best:
                best = candidate
        return None if best is None else float(best[1])

    @classmethod
    def _strike_step(cls, frame: pd.DataFrame) -> float:
        strikes = (
            pd.to_numeric(frame.get("strike"), errors="coerce")
            .dropna()
            .sort_values()
            .unique()
        )
        if len(strikes) < 2:
            return 50.0
        diffs = pd.Series(strikes).diff().dropna()
        diffs = diffs[diffs > 0]
        return float(diffs.median()) if not diffs.empty else 50.0

    @staticmethod
    def _band(score: float) -> str:
        if score >= 75:
            return "HIGH"
        if score >= 50:
            return "MEDIUM"
        if score >= 35:
            return "LOW"
        return "VERY_LOW"

    @classmethod
    def evaluate(cls, frame: pd.DataFrame) -> tuple[ContractQualityMetric, ...]:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return ()
        atm = cls.infer_atm(frame)
        step = max(1.0, cls._strike_step(frame))
        result: list[ContractQualityMetric] = []
        for row in cls._records(frame):
            strike = safe_float(row.get("strike"))
            if strike is None:
                continue
            distance = abs(strike - atm) if atm is not None else None
            distance_steps = (distance / step) if distance is not None else 8.0
            proximity_score = max(0.0, 100.0 - distance_steps * 12.5)
            for side, prefix in (("CE", "call"), ("PE", "put")):
                premium = safe_float(row.get(f"{prefix}_ltp"))
                oi = safe_float(row.get(f"{prefix}_oi"))
                volume = safe_float(row.get(f"{prefix}_volume"))
                premium_score = min(100.0, max(0.0, (premium or 0.0) / 10.0 * 100.0))
                oi_score = min(100.0, max(0.0, (oi or 0.0) / 500000.0 * 100.0))
                volume_score = min(100.0, max(0.0, (volume or 0.0) / 1000000.0 * 100.0))
                score = round(
                    max(
                        0.0,
                        min(
                            100.0,
                            proximity_score * 0.35
                            + premium_score * 0.25
                            + oi_score * 0.25
                            + volume_score * 0.15,
                        ),
                    ),
                    2,
                )
                result.append(
                    ContractQualityMetric(
                        strike=round(strike, 2),
                        option_type=side,
                        premium=premium,
                        oi=oi,
                        volume=volume,
                        inferred_atm=round(atm, 2) if atm is not None else None,
                        atm_distance_points=round(distance, 2) if distance is not None else None,
                        quality_score=score,
                        quality_band=cls._band(score),
                        eligible=score >= 35.0,
                    )
                )
        return tuple(result)
