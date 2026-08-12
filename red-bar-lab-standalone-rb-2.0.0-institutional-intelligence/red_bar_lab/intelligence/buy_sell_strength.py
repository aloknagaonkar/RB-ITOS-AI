from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BuySellStrength:
    buying_strength_pct: float
    selling_strength_pct: float
    neutral_strength_pct: float
    net_strength: float
    market_conviction: str
    breadth_pct: float
    reason: str


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

    @classmethod
    def evaluate(
        cls,
        flow_rows: Iterable,
        velocity_by_key: dict[tuple[float, str], object] | None = None,
    ) -> BuySellStrength:
        velocity_by_key = velocity_by_key or {}
        bullish = bearish = neutral = 0.0
        directional_rows = total_rows = 0
        for row in flow_rows:
            total_rows += 1
            base = max(1.0, float(getattr(row, "confidence_pct", 0.0)))
            key = (float(getattr(row, "strike", 0.0)), str(getattr(row, "option_type", "")))
            score = base * cls._velocity_alignment(row, velocity_by_key.get(key))
            bias = str(getattr(row, "directional_bias", "NEUTRAL"))
            if bias == "BULLISH":
                bullish += score
                directional_rows += 1
            elif bias == "BEARISH":
                bearish += score
                directional_rows += 1
            else:
                neutral += score

        total = bullish + bearish + neutral
        if total <= 0:
            return BuySellStrength(
                0.0, 0.0, 100.0, 0.0, "LOW", 0.0,
                "No directional institutional evidence available.",
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
        return BuySellStrength(
            round(buy, 2), round(sell, 2), round(neu, 2), round(net, 2), conviction,
            round(breadth, 2),
            f"Institutional {leader} evidence leads by {abs(net):.1f} percentage points across {directional_rows}/{total_rows} directional samples.",
        )
