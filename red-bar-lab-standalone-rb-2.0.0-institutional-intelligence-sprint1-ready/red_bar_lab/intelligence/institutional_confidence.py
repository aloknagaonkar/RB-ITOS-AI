from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstitutionalConfidence:
    score: float
    direction: str
    quality: str
    directional_edge: float
    data_coverage_pct: float
    components: dict[str, float]
    execution_impact: str = "NONE"


class InstitutionalConfidenceEngine:
    """Headline advisory confidence for Sprint 2. Never modifies execution state."""

    @staticmethod
    def evaluate(strength, flow_rows, velocity_rows, premium_rows, rotation) -> InstitutionalConfidence:
        directional_edge = abs(float(getattr(strength, "net_strength", 0.0)))
        direction = "BULLISH" if strength.net_strength > 5 else "BEARISH" if strength.net_strength < -5 else "NEUTRAL"
        flow_component = min(100.0, directional_edge * 2.0)

        velocity_known = [r for r in velocity_rows if getattr(r, "change_5m_pct", None) is not None]
        velocity_component = 0.0
        if velocity_known:
            accelerating = sum(1 for r in velocity_known if str(getattr(r, "state", "")).startswith("ACCELERATING"))
            moving = sum(1 for r in velocity_known if getattr(r, "state", "") not in {"UNKNOWN", "STABLE"})
            velocity_component = min(100.0, (accelerating * 1.5 + moving) / max(1, len(velocity_known)) * 70.0)

        premium_known = [r for r in premium_rows if getattr(r, "change_5m_pct", None) is not None]
        premium_component = 0.0
        if premium_known:
            premium_component = sum(min(100.0, float(getattr(r, "strength_pct", 0.0))) for r in premium_known) / len(premium_known)

        rotation_component = min(100.0, float(getattr(rotation, "confidence_pct", 0.0)))
        directional_flow = [r for r in flow_rows if getattr(r, "directional_bias", "NEUTRAL") != "NEUTRAL"]
        data_coverage = min(100.0, (len(velocity_known) + len(premium_known)) / max(1, 2 * len(flow_rows)) * 100.0)
        breadth_component = float(getattr(strength, "breadth_pct", 0.0))

        components = {
            "Directional Edge": round(flow_component, 2),
            "OI Velocity": round(velocity_component, 2),
            "Premium Flow": round(premium_component, 2),
            "Strike Rotation": round(rotation_component, 2),
            "Breadth": round(breadth_component, 2),
        }
        score = (
            flow_component * 0.35
            + velocity_component * 0.20
            + premium_component * 0.20
            + rotation_component * 0.10
            + breadth_component * 0.15
        )
        score *= 0.60 + 0.40 * (data_coverage / 100.0)
        score = round(min(100.0, max(0.0, score)), 2)
        if score >= 80:
            quality = "VERY_STRONG"
        elif score >= 65:
            quality = "STRONG"
        elif score >= 50:
            quality = "MODERATE"
        elif score >= 30:
            quality = "WEAK"
        else:
            quality = "INSUFFICIENT"
        if not directional_flow:
            direction = "NEUTRAL"
        return InstitutionalConfidence(score, direction, quality, round(directional_edge, 2), round(data_coverage, 2), components)
