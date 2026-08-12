from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class StrengthContribution:
    strike: float
    option_type: str
    activity: str
    behaviour: str
    directional_bias: str
    base_confidence: float
    velocity_alignment: float
    quality_weight: float
    weighted_score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "Strike": self.strike,
            "Side": self.option_type,
            "Activity": self.activity,
            "OI Behaviour": self.behaviour,
            "Direction": self.directional_bias,
            "Base Confidence %": round(self.base_confidence, 2),
            "Velocity Multiplier": round(self.velocity_alignment, 2),
            "Quality Weight": round(self.quality_weight, 3),
            "Weighted Contribution": round(self.weighted_score, 2),
        }


@dataclass(frozen=True)
class BuySellStrength:
    buying_strength_pct: float
    selling_strength_pct: float
    neutral_strength_pct: float
    net_strength: float
    market_conviction: str
    breadth_pct: float
    reason: str
    contributions: tuple[StrengthContribution, ...] = ()


class BuySellStrengthEngine:
    """Aggregate directional institutional evidence without execution authority."""

    @staticmethod
    def _velocity_alignment(row, velocity) -> float:
        if velocity is None:
            return 1.0
        value = velocity.change_5m_pct
        if value is None:
            return 1.0
        behaviour = str(getattr(row, "behaviour", ""))
        aligned = (
            ("BUILDUP" in behaviour and value > 0)
            or (("COVERING" in behaviour or "UNWINDING" in behaviour) and value < 0)
        )
        return 1.15 if aligned else 0.90

    @staticmethod
    def _quality_weight(quality) -> float:
        if quality is None:
            return 1.0
        return float(getattr(quality, "weight", 1.0))

    @classmethod
    def evaluate(
        cls,
        flow_rows: Iterable,
        velocity_by_key: dict[tuple[float, str], object] | None = None,
        quality_by_key: dict[tuple[float, str], object] | None = None,
    ) -> BuySellStrength:
        velocity_by_key = velocity_by_key or {}
        quality_by_key = quality_by_key or {}
        bullish = bearish = neutral = 0.0
        directional_rows = total_rows = 0
        qualified_rows = 0
        contributions: list[StrengthContribution] = []
        for row in flow_rows:
            total_rows += 1
            base = max(1.0, float(getattr(row, "confidence_pct", 0.0)))
            strike = float(getattr(row, "strike", 0.0))
            option_type = str(getattr(row, "option_type", ""))
            key = (strike, option_type)
            quality = quality_by_key.get(key)
            quality_weight = cls._quality_weight(quality)
            if quality is None or bool(getattr(quality, "eligible", True)):
                qualified_rows += 1
            velocity_alignment = cls._velocity_alignment(row, velocity_by_key.get(key))
            score = base * velocity_alignment * quality_weight
            bias = str(getattr(row, "directional_bias", "NEUTRAL"))
            contributions.append(
                StrengthContribution(
                    strike=strike,
                    option_type=option_type,
                    activity=str(getattr(row, "institutional_activity", "")),
                    behaviour=str(getattr(row, "behaviour", "")),
                    directional_bias=bias,
                    base_confidence=base,
                    velocity_alignment=velocity_alignment,
                    quality_weight=quality_weight,
                    weighted_score=score,
                )
            )
            if bias == "BULLISH":
                bullish += score
                directional_rows += 1
            elif bias == "BEARISH":
                bearish += score
                directional_rows += 1
            else:
                neutral += score

        total = bullish + bearish + neutral
        contribution_trace = tuple(contributions)
        if total <= 0:
            return BuySellStrength(
                0.0, 0.0, 100.0, 0.0, "LOW", 0.0,
                "No directional institutional evidence available.",
                contribution_trace,
            )

        buy = bullish / total * 100.0
        sell = bearish / total * 100.0
        neu = max(0.0, 100.0 - buy - sell)
        net = buy - sell
        participation = buy + sell
        disagreement = min(buy, sell)
        if participation >= 70 and disagreement >= 25:
            conviction = "HIGH_CONFLICT"
        elif abs(net) >= 30 and participation >= 60:
            conviction = "HIGH"
        elif abs(net) >= 15:
            conviction = "MEDIUM"
        else:
            conviction = "LOW"
        breadth = directional_rows / total_rows * 100.0 if total_rows else 0.0
        leader = "buying" if net > 0 else "selling" if net < 0 else "balanced"
        quality_note = (
            f" Quality-weighted contribution used; {qualified_rows}/{total_rows} contracts meet the advisory quality threshold."
            if quality_by_key else ""
        )
        return BuySellStrength(
            round(buy, 2), round(sell, 2), round(neu, 2), round(net, 2), conviction,
            round(breadth, 2),
            f"Institutional {leader} evidence leads by {abs(net):.1f} percentage points across {directional_rows}/{total_rows} directional samples.{quality_note}",
            contribution_trace,
        )
