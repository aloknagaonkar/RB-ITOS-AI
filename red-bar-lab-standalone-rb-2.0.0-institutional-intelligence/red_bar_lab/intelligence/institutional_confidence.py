from __future__ import annotations

from dataclasses import dataclass


ICI_WEIGHTS = {
    "Directional Edge": 0.35,
    "OI Velocity": 0.20,
    "Premium Flow": 0.20,
    "Strike Rotation": 0.10,
    "Breadth": 0.15,
}


@dataclass(frozen=True)
class InstitutionalConfidence:
    score: float
    direction: str
    quality: str
    directional_edge: float
    data_coverage_pct: float
    components: dict[str, float]
    execution_impact: str = "NONE"

    @property
    def coverage_multiplier(self) -> float:
        return round(0.60 + 0.40 * (self.data_coverage_pct / 100.0), 6)

    @property
    def component_audit(self) -> tuple[dict[str, object], ...]:
        rows = []
        for name, raw_score in self.components.items():
            weight = ICI_WEIGHTS[name]
            pre_coverage = float(raw_score) * weight
            final_contribution = pre_coverage * self.coverage_multiplier
            interpretation = (
                "VERY_STRONG" if raw_score >= 80
                else "STRONG" if raw_score >= 65
                else "MODERATE" if raw_score >= 50
                else "WEAK" if raw_score >= 30
                else "VERY_WEAK"
            )
            rows.append({
                "Component": name,
                "Raw Score %": round(float(raw_score), 2),
                "Weight %": round(weight * 100.0, 2),
                "Pre-Coverage Contribution": round(pre_coverage, 2),
                "Coverage Multiplier": round(self.coverage_multiplier, 4),
                "Final ICI Contribution": round(final_contribution, 2),
                "Interpretation": interpretation,
            })
        return tuple(rows)

    @property
    def reconstructed_score(self) -> float:
        return round(sum(float(row["Final ICI Contribution"]) for row in self.component_audit), 2)

    @property
    def explanation(self) -> str:
        strongest = max(self.components.items(), key=lambda item: item[1])
        weakest = min(self.components.items(), key=lambda item: item[1])
        return (
            f"ICI {self.score:.1f}% is {self.direction} / {self.quality}. "
            f"Strongest component is {strongest[0]} at {strongest[1]:.1f}%; "
            f"weakest is {weakest[0]} at {weakest[1]:.1f}%. "
            f"Data coverage is {self.data_coverage_pct:.1f}%, applying a {self.coverage_multiplier:.3f} coverage multiplier. "
            "This is an advisory explanation only; execution impact remains NONE."
        )


class InstitutionalConfidenceEngine:
    """Headline advisory confidence for Sprint 2. Never modifies execution state."""

    @staticmethod
    def evaluate(
        strength,
        flow_rows,
        velocity_rows,
        premium_rows,
        rotation,
        quality_by_key: dict[tuple[float, str], object] | None = None,
    ) -> InstitutionalConfidence:
        quality_by_key = quality_by_key or {}

        def weight_for(row) -> float:
            key = (float(getattr(row, "strike", 0.0)), str(getattr(row, "option_type", "")))
            quality = quality_by_key.get(key)
            return float(getattr(quality, "weight", 1.0)) if quality is not None else 1.0

        directional_edge = abs(float(getattr(strength, "net_strength", 0.0)))
        direction = (
            "BULLISH" if strength.net_strength > 5
            else "BEARISH" if strength.net_strength < -5
            else "NEUTRAL"
        )
        flow_component = min(100.0, directional_edge * 2.0)

        velocity_known = [r for r in velocity_rows if getattr(r, "change_5m_pct", None) is not None]
        velocity_component = 0.0
        if velocity_known:
            weighted_value = weighted_total = 0.0
            for row in velocity_known:
                row_weight = weight_for(row)
                state = str(getattr(row, "state", ""))
                activity = 0.0 if state in {"UNKNOWN", "STABLE"} else 70.0
                if state.startswith("ACCELERATING"):
                    activity = 100.0
                weighted_value += activity * row_weight
                weighted_total += row_weight
            velocity_component = weighted_value / max(1e-9, weighted_total)

        premium_known = [r for r in premium_rows if getattr(r, "change_5m_pct", None) is not None]
        premium_component = 0.0
        if premium_known:
            weighted_value = weighted_total = 0.0
            for row in premium_known:
                row_weight = weight_for(row)
                weighted_value += min(100.0, float(getattr(row, "strength_pct", 0.0))) * row_weight
                weighted_total += row_weight
            premium_component = weighted_value / max(1e-9, weighted_total)

        rotation_component = min(100.0, float(getattr(rotation, "confidence_pct", 0.0)))
        directional_flow = [
            r for r in flow_rows
            if getattr(r, "directional_bias", "NEUTRAL") != "NEUTRAL"
        ]
        data_coverage = min(
            100.0,
            (len(velocity_known) + len(premium_known))
            / max(1, 2 * len(flow_rows)) * 100.0,
        )
        breadth_component = float(getattr(strength, "breadth_pct", 0.0))

        components = {
            "Directional Edge": round(flow_component, 2),
            "OI Velocity": round(velocity_component, 2),
            "Premium Flow": round(premium_component, 2),
            "Strike Rotation": round(rotation_component, 2),
            "Breadth": round(breadth_component, 2),
        }
        score = sum(components[name] * ICI_WEIGHTS[name] for name in ICI_WEIGHTS)
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
        return InstitutionalConfidence(
            score,
            direction,
            quality,
            round(directional_edge, 2),
            round(data_coverage, 2),
            components,
        )
