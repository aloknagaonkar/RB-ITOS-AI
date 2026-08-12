from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


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
        # Keep low-quality contracts visible but prevent them from dominating
        # aggregated institutional intelligence.
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
    """Advisory quality weighting for option-chain evidence.

    Raw OI/premium velocity is never changed. This layer only controls how much
    each contract contributes to aggregate Shadow intelligence. ATM is inferred
    from the strike where call/put premiums are closest, which is robust when a
    separate spot field is not persisted with the chain artifact.
    """

    @staticmethod
    def _num(value: object) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def infer_atm(cls, frame: pd.DataFrame) -> float | None:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return None
        best: tuple[float, float] | None = None
        for _, row in frame.iterrows():
            strike = cls._num(row.get("strike"))
            call = cls._num(row.get("call_ltp"))
            put = cls._num(row.get("put_ltp"))
            if strike is None or call is None or put is None or call <= 0 or put <= 0:
                continue
            candidate = (abs(call - put), strike)
            if best is None or candidate < best:
                best = candidate
        return None if best is None else float(best[1])

    @classmethod
    def _strike_step(cls, frame: pd.DataFrame) -> float:
        strikes = pd.to_numeric(frame.get("strike"), errors="coerce").dropna().sort_values().unique()
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
        for _, row in frame.iterrows():
            strike = cls._num(row.get("strike"))
            if strike is None:
                continue
            distance = abs(strike - atm) if atm is not None else None
            distance_steps = (distance / step) if distance is not None else 8.0
            proximity_score = max(0.0, 100.0 - distance_steps * 12.5)
            for side, prefix in (("CE", "call"), ("PE", "put")):
                premium = cls._num(row.get(f"{prefix}_ltp"))
                oi = cls._num(row.get(f"{prefix}_oi"))
                volume = cls._num(row.get(f"{prefix}_volume"))
                premium_score = min(100.0, max(0.0, (premium or 0.0) / 10.0 * 100.0))
                oi_score = min(100.0, max(0.0, (oi or 0.0) / 500000.0 * 100.0))
                volume_score = min(100.0, max(0.0, (volume or 0.0) / 1000000.0 * 100.0))
                score = (
                    proximity_score * 0.35
                    + premium_score * 0.25
                    + oi_score * 0.25
                    + volume_score * 0.15
                )
                score = round(max(0.0, min(100.0, score)), 2)
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
