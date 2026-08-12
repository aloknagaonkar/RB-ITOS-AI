from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ShadowModuleResult:
    module: str
    status: str
    direction: str
    confidence: float
    recommendation: str
    reason: str
    execution_impact: str = "NONE"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowDecision:
    current_decision: str
    shadow_decision: str
    shadow_confidence: float
    agreement: str
    portfolio_conflict: bool
    portfolio_action: str
    modules: tuple[ShadowModuleResult, ...]
    evaluated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "current_decision": self.current_decision,
            "shadow_decision": self.shadow_decision,
            "shadow_confidence": self.shadow_confidence,
            "agreement": self.agreement,
            "portfolio_conflict": self.portfolio_conflict,
            "portfolio_action": self.portfolio_action,
            "modules": [item.as_dict() for item in self.modules],
            "evaluated_at": self.evaluated_at,
        }


def _result(
    module: str,
    status: str,
    direction: str,
    confidence: float,
    recommendation: str,
    reason: str,
) -> ShadowModuleResult:
    return ShadowModuleResult(
        module=module,
        status=status,
        direction=direction,
        confidence=round(max(0.0, min(100.0, confidence)), 1),
        recommendation=recommendation,
        reason=reason,
    )


class ShadowIntelligenceEngine:
    """Observation-only intelligence.

    This engine never places, closes, reverses, or modifies a paper trade.
    It produces auditable module evidence. From RB-0.9.2 onward, historically
    validated persisted evidence may be consumed by the separate Institutional
    Execution Committee; the shadow engine itself still has no order authority.
    """

    def evaluate(
        self,
        *,
        current_decision: str,
        direction: str,
        spot_price: float | None,
        pcr_oi: float | None,
        call_wall: float | None,
        put_wall: float | None,
        max_pain: float | None,
        chain_rows,
        best_candidate: dict[str, object] | None,
        market_features: dict[str, object] | None,
        open_orders: list[dict[str, object]],
    ) -> ShadowDecision:
        desired_option = "CE" if direction == "BULLISH" else "PE"
        desired_action = (
            "BUY CE" if direction == "BULLISH"
            else "BUY PE" if direction == "BEARISH"
            else "WAIT"
        )
        modules: list[ShadowModuleResult] = []

        # PCR: directional observation only, not a gate.
        pcr = _num(pcr_oi)
        if pcr is None:
            modules.append(_result(
                "PCR", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "PCR is unavailable in the current snapshot."
            ))
        elif pcr >= 1.10:
            conf = min(95.0, 65.0 + (pcr - 1.10) * 100.0)
            modules.append(_result(
                "PCR", "PASS", "BULLISH", conf, "BUY CE",
                f"PCR(OI)={pcr:.2f} shows put OI dominance."
            ))
        elif pcr <= 0.90:
            conf = min(95.0, 65.0 + (0.90 - pcr) * 100.0)
            modules.append(_result(
                "PCR", "PASS", "BEARISH", conf, "BUY PE",
                f"PCR(OI)={pcr:.2f} shows call OI dominance."
            ))
        else:
            modules.append(_result(
                "PCR", "NEUTRAL", "NEUTRAL", 55, "WAIT",
                f"PCR(OI)={pcr:.2f} is inside the neutral observation band."
            ))

        # OI change from the live option-chain snapshot.
        call_change = put_change = 0.0
        change_available = False
        try:
            if chain_rows is not None and len(chain_rows):
                if "call_oi_change" in chain_rows.columns:
                    call_change = float(
                        chain_rows["call_oi_change"].fillna(0).sum()
                    )
                    change_available = True
                if "put_oi_change" in chain_rows.columns:
                    put_change = float(
                        chain_rows["put_oi_change"].fillna(0).sum()
                    )
                    change_available = True
        except Exception:
            change_available = False

        if not change_available:
            modules.append(_result(
                "OI Change", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "Change-in-OI is unavailable for this snapshot."
            ))
        else:
            denominator = max(abs(call_change) + abs(put_change), 1.0)
            imbalance = (put_change - call_change) / denominator
            if imbalance >= 0.15:
                modules.append(_result(
                    "OI Change", "PASS", "BULLISH",
                    60 + min(35, abs(imbalance) * 40), "BUY CE",
                    f"Put ΔOI {put_change:,.0f} exceeds call ΔOI "
                    f"{call_change:,.0f}."
                ))
            elif imbalance <= -0.15:
                modules.append(_result(
                    "OI Change", "PASS", "BEARISH",
                    60 + min(35, abs(imbalance) * 40), "BUY PE",
                    f"Call ΔOI {call_change:,.0f} exceeds put ΔOI "
                    f"{put_change:,.0f}."
                ))
            else:
                modules.append(_result(
                    "OI Change", "NEUTRAL", "NEUTRAL", 55, "WAIT",
                    "Call/put change-in-OI is balanced."
                ))

        # Max pain is intentionally informational; it does not claim direction.
        mp = _num(max_pain)
        spot = _num(spot_price)
        if mp is None or spot is None:
            modules.append(_result(
                "Max Pain", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "Max-pain comparison is unavailable."
            ))
        else:
            distance_pct = abs(spot - mp) / max(abs(spot), 1.0) * 100.0
            modules.append(_result(
                "Max Pain", "NEUTRAL", "INFORMATIONAL",
                max(35.0, 70.0 - distance_pct * 15.0), "WAIT",
                f"Spot {spot:.2f}; max pain {mp:.2f}; "
                f"distance {distance_pct:.2f}%."
            ))

        # Call/put walls.
        cw, pw = _num(call_wall), _num(put_wall)
        if spot is None or cw is None or pw is None:
            modules.append(_result(
                "Call / Put Wall", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "Wall comparison is unavailable."
            ))
        elif spot > cw:
            modules.append(_result(
                "Call / Put Wall", "PASS", "BULLISH", 78, "BUY CE",
                f"Spot {spot:.2f} is above call wall {cw:.2f}."
            ))
        elif spot < pw:
            modules.append(_result(
                "Call / Put Wall", "PASS", "BEARISH", 78, "BUY PE",
                f"Spot {spot:.2f} is below put wall {pw:.2f}."
            ))
        else:
            modules.append(_result(
                "Call / Put Wall", "WARNING", "RANGE", 60, "WAIT",
                f"Spot is between put wall {pw:.2f} and call wall {cw:.2f}."
            ))

        # Greeks are evaluated as contract quality for the current direction.
        candidate = best_candidate or {}
        delta = _num(candidate.get("Delta"))
        gamma = _num(candidate.get("Gamma"))
        iv = _num(candidate.get("IV"))
        theta = _num(candidate.get("Theta"))
        vega = _num(candidate.get("Vega"))
        if delta is None and gamma is None and iv is None:
            modules.append(_result(
                "Greeks", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "Greeks are unavailable for the best current candidate."
            ))
        else:
            quality = 0.0
            checks = 0
            if delta is not None:
                checks += 1
                abs_delta = abs(delta)
                quality += 1.0 if 0.35 <= abs_delta <= 0.65 else 0.5
            if gamma is not None:
                checks += 1
                quality += 1.0 if gamma > 0 else 0.0
            if iv is not None:
                checks += 1
                quality += 1.0 if 5 <= iv <= 60 else 0.5
            if theta is not None:
                checks += 1
                quality += 1.0 if theta <= 0 else 0.5
            if vega is not None:
                checks += 1
                quality += 1.0 if vega >= 0 else 0.5
            confidence = 50.0 + 45.0 * (quality / max(checks, 1))
            status = "PASS" if confidence >= 75 else "WARNING"
            modules.append(_result(
                "Greeks", status, direction if direction != "WAIT" else "NEUTRAL",
                confidence, desired_action if status == "PASS" else "WAIT",
                f"Δ={delta}; Γ={gamma}; IV={iv}; Θ={theta}; Vega={vega}."
            ))

        features = market_features or {}
        market = features.get("market_context") or {}
        volume = features.get("volume_structure") or {}

        # Market context: use only features actually persisted by the platform.
        trend_5m = str(market.get("trend_5m") or "").upper()
        if trend_5m in {"BULLISH", "UP", "UPTREND"}:
            modules.append(_result(
                "Market Context", "PASS", "BULLISH", 78, "BUY CE",
                f"Persisted 5m trend is {trend_5m}."
            ))
        elif trend_5m in {"BEARISH", "DOWN", "DOWNTREND"}:
            modules.append(_result(
                "Market Context", "PASS", "BEARISH", 78, "BUY PE",
                f"Persisted 5m trend is {trend_5m}."
            ))
        else:
            modules.append(_result(
                "Market Context", "NEUTRAL", "NEUTRAL", 45, "WAIT",
                "No decisive persisted 5m trend is available."
            ))

        bull_structure = _num(volume.get("bullish_structure_score"))
        bear_structure = _num(volume.get("bearish_structure_score"))
        structure_state = str(volume.get("structure_state") or "")
        if bull_structure is None and bear_structure is None:
            modules.append(_result(
                "Market Structure", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "Structure scores are not available for this signal."
            ))
        elif (bull_structure or 0) > (bear_structure or 0):
            gap = (bull_structure or 0) - (bear_structure or 0)
            modules.append(_result(
                "Market Structure", "PASS", "BULLISH",
                min(92, 60 + gap * 4), "BUY CE",
                f"{structure_state or 'structure'}; bullish score "
                f"{bull_structure} > bearish {bear_structure}."
            ))
        elif (bear_structure or 0) > (bull_structure or 0):
            gap = (bear_structure or 0) - (bull_structure or 0)
            modules.append(_result(
                "Market Structure", "PASS", "BEARISH",
                min(92, 60 + gap * 4), "BUY PE",
                f"{structure_state or 'structure'}; bearish score "
                f"{bear_structure} > bullish {bull_structure}."
            ))
        else:
            modules.append(_result(
                "Market Structure", "WARNING", "MIXED", 55, "WAIT",
                f"{structure_state or 'Structure'} is not directionally decisive."
            ))

        relative_volume = _num(volume.get("relative_volume_20m"))
        volume_trend = str(volume.get("volume_trend_5m") or "")
        if relative_volume is None:
            modules.append(_result(
                "Volume Intelligence", "NEUTRAL", "UNKNOWN", 0, "WAIT",
                "Relative-volume data is unavailable."
            ))
        elif relative_volume >= 1.5:
            modules.append(_result(
                "Volume Intelligence", "PASS", direction, 82, desired_action,
                f"Relative volume={relative_volume:.2f}; trend={volume_trend or 'NA'}."
            ))
        elif relative_volume >= 1.0:
            modules.append(_result(
                "Volume Intelligence", "NEUTRAL", direction, 62, "WAIT",
                f"Relative volume={relative_volume:.2f}; not a strong expansion."
            ))
        else:
            modules.append(_result(
                "Volume Intelligence", "WARNING", "WEAK", 45, "WAIT",
                f"Relative volume={relative_volume:.2f} is below average."
            ))

        # Multi-timeframe and Wyckoff remain explicit data-pending observations.
        modules.append(_result(
            "Multi-Timeframe", "NEUTRAL", "DATA PENDING", 0, "WAIT",
            "15m/5m/1m agreement is not yet persisted as one validated feature."
        ))
        modules.append(_result(
            "Wyckoff", "NEUTRAL", "DATA PENDING", 0, "WAIT",
            "Wyckoff phase is not yet a validated persisted entry-time feature."
        ))

        # Portfolio intelligence: observation only in this release.
        open_types = [
            str(row.get("option_type") or "").upper()
            for row in open_orders
            if row.get("status") == "OPEN"
        ]
        opposite = "PE" if desired_option == "CE" else "CE"
        portfolio_conflict = opposite in open_types
        if not open_types:
            portfolio_action = "ALLOW"
            modules.append(_result(
                "Portfolio", "PASS", "FLAT", 90, desired_action,
                "No open paper exposure conflicts with the current direction."
            ))
        elif portfolio_conflict:
            portfolio_action = "REVERSE"
            modules.append(_result(
                "Portfolio", "CONFLICT", "OPPOSITE", 90, "REVERSE",
                f"Current signal prefers {desired_option}, while open portfolio "
                f"contains {opposite}. Observation only."
            ))
        elif desired_option in open_types:
            portfolio_action = "HOLD"
            modules.append(_result(
                "Portfolio", "WARNING", "SAME DIRECTION", 78, "HOLD",
                f"Open portfolio already contains {desired_option} exposure."
            ))
        else:
            portfolio_action = "WAIT"
            modules.append(_result(
                "Portfolio", "NEUTRAL", "MIXED", 55, "WAIT",
                "Portfolio exposure is mixed or unavailable."
            ))

        # Committee vote excludes informational/data-pending portfolio action.
        directional = [
            item for item in modules
            if item.recommendation in {"BUY CE", "BUY PE", "WAIT"}
            and item.confidence > 0
            and item.module not in {"Max Pain", "Portfolio"}
        ]
        votes = {"BUY CE": 0.0, "BUY PE": 0.0, "WAIT": 0.0}
        for item in directional:
            votes[item.recommendation] += max(item.confidence, 1.0)

        shadow_decision = max(votes, key=votes.get) if directional else "WAIT"
        matching_conf = [
            item.confidence for item in directional
            if item.recommendation == shadow_decision
        ]
        shadow_confidence = mean(matching_conf) if matching_conf else 0.0

        normalized_current = str(current_decision or "WAIT").upper()
        if normalized_current in {"PAPER BUY", "BUY"}:
            normalized_current = desired_action
        agreement = (
            "YES" if normalized_current == shadow_decision
            else "PARTIAL" if shadow_decision == "WAIT"
            else "NO"
        )

        return ShadowDecision(
            current_decision=normalized_current,
            shadow_decision=shadow_decision,
            shadow_confidence=round(shadow_confidence, 1),
            agreement=agreement,
            portfolio_conflict=portfolio_conflict,
            portfolio_action=portfolio_action,
            modules=tuple(modules),
            evaluated_at=datetime.now(IST).isoformat(),
        )
