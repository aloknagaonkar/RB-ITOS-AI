from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class OpportunityEvaluation:
    signal_id: str
    signal_age_seconds: float
    entry_mode: str
    direction: str
    opportunity_score: float
    structure_score: float
    momentum_score: float
    reward_score: float
    option_health_score: float
    market_context_score: float
    time_score: float
    reward_remaining_pct: float
    move_consumed_pct: float
    structure_valid: bool
    opposite_red_bar: bool
    candidate_score: float
    spread_score: float
    liquidity_score: float
    vwap_score: float
    ema_score: float
    raw_momentum_score: float
    eligible: bool
    decision: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class OpportunityIntelligenceEngine:
    """Evaluate whether an older confirmed Red Bar still has entry edge.

    Fresh signals are still governed by the existing Current Decision Engine.
    For signals older than the normal freshness window, this engine can grant a
    guarded paper-entry extension when the opportunity remains exceptionally
    strong.

    The first model is intentionally deterministic and auditable. It can be
    validated and reweighted later using the stored opportunity history.
    """

    def __init__(
        self,
        *,
        minimum_opportunity_score: float = 85.0,
        minimum_extended_candidate_score: float = 85.0,
        minimum_reward_remaining_pct: float = 40.0,
        minimum_liquidity_score: float = 15.0,
        minimum_spread_score: float = 8.0,
        minimum_momentum_score: float = 6.0,
    ):
        self.minimum_opportunity_score = float(minimum_opportunity_score)
        self.minimum_extended_candidate_score = float(
            minimum_extended_candidate_score
        )
        self.minimum_reward_remaining_pct = float(
            minimum_reward_remaining_pct
        )
        self.minimum_liquidity_score = float(minimum_liquidity_score)
        self.minimum_spread_score = float(minimum_spread_score)
        self.minimum_momentum_score = float(minimum_momentum_score)

    @staticmethod
    def _time_score(age_seconds: float) -> float:
        age = max(0.0, float(age_seconds))
        if age <= 180:
            return 10.0
        if age <= 300:
            return 8.0
        if age <= 600:
            return 6.0
        if age <= 900:
            return 3.0
        return 0.0

    @staticmethod
    def _structure_valid(
        *,
        direction: str,
        spot_price: float,
        confirmation_high: float,
        confirmation_low: float,
    ) -> bool:
        direction = str(direction or "").upper()
        if direction == "BULLISH":
            return not (
                confirmation_low > 0
                and spot_price < confirmation_low
            )
        if direction == "BEARISH":
            return not (
                confirmation_high > 0
                and spot_price > confirmation_high
            )
        return False

    @staticmethod
    def _reward_remaining(
        *,
        direction: str,
        spot_price: float,
        confirmation_high: float,
        confirmation_low: float,
        confirmation_close: float,
    ) -> tuple[float, float]:
        """Return remaining/consumed opportunity using Red Bar range extension.

        Two confirmation-candle ranges beyond the confirmation close is treated
        as fully consumed for the first empirical model. This is a transparent
        proxy until historical learning can replace it with a data-fitted
        expected-move model.
        """
        candle_range = max(
            confirmation_high - confirmation_low,
            abs(confirmation_close) * 0.0005,
            0.01,
        )
        direction = str(direction or "").upper()
        if direction == "BULLISH":
            progress = max(0.0, spot_price - confirmation_close)
        elif direction == "BEARISH":
            progress = max(0.0, confirmation_close - spot_price)
        else:
            progress = 0.0

        consumed = min(
            100.0,
            max(0.0, progress / (2.0 * candle_range) * 100.0),
        )
        return round(100.0 - consumed, 2), round(consumed, 2)

    def evaluate(
        self,
        *,
        signal: dict[str, object],
        candidate,
        spot_price: float,
        signal_age_seconds: float,
        opposite_red_bar_confirmed: bool,
        freshness_seconds: float = 180.0,
    ) -> OpportunityEvaluation:
        direction = str(signal.get("direction") or "").upper()
        signal_id = str(signal.get("signal_id") or "")
        high = _num(signal.get("confirmation_high"))
        low = _num(signal.get("confirmation_low"))
        close = _num(
            signal.get("confirmation_close"),
            _num(signal.get("underlying_entry"), spot_price),
        )

        structure_valid = self._structure_valid(
            direction=direction,
            spot_price=float(spot_price),
            confirmation_high=high,
            confirmation_low=low,
        )
        reward_remaining, move_consumed = self._reward_remaining(
            direction=direction,
            spot_price=float(spot_price),
            confirmation_high=high,
            confirmation_low=low,
            confirmation_close=close,
        )

        candidate_score = _num(candidate.total_score)
        spread_score = _num(candidate.spread_score)
        liquidity_score = _num(candidate.liquidity_score)
        volume_score = _num(candidate.volume_score)
        oi_score = _num(candidate.oi_score)
        vwap_score = _num(candidate.vwap_score)
        ema_score = _num(candidate.ema_score)
        raw_momentum = _num(candidate.momentum_score)

        # RB-1.5.0 Opportunity Health: current market strength, not signal age.
        # Weights: structure 20, VWAP 15, EMA 15, momentum 15, volume 10,
        # OI 10, liquidity 10, spread 5. Signal age is informational only.
        structure_score = 20.0 if structure_valid else 0.0
        vwap_health = 15.0 if vwap_score > 0 else 0.0
        ema_health = 15.0 if ema_score > 0 else 0.0
        momentum_score = min(15.0, max(0.0, raw_momentum / 10.0 * 15.0))
        volume_health = min(10.0, max(0.0, volume_score / 15.0 * 10.0))
        oi_health = min(10.0, max(0.0, oi_score / 10.0 * 10.0))
        liquidity_health = min(10.0, max(0.0, liquidity_score / 20.0 * 10.0))
        spread_health = min(5.0, max(0.0, spread_score / 15.0 * 5.0))
        reward_score = min(20.0, max(0.0, reward_remaining / 100.0 * 20.0))
        option_health_score = round(vwap_health + ema_health + liquidity_health + spread_health, 2)
        market_context_score = round(volume_health + oi_health, 2)
        time_score = self._time_score(signal_age_seconds)
        opportunity_score = round(
            structure_score + vwap_health + ema_health + momentum_score
            + volume_health + oi_health + liquidity_health + spread_health, 2
        )

        entry_mode = (
            "FRESH_SIGNAL"
            if float(signal_age_seconds) <= float(freshness_seconds)
            else "OPPORTUNITY_EXTENSION"
        )

        # Only true opportunity invalidation / execution-quality failures block.
        # Weak individual indicators are absorbed into the 0-100 health score.
        blockers: list[str] = []
        if not structure_valid:
            blockers.append("STRUCTURE_INVALID")
        if opposite_red_bar_confirmed:
            blockers.append("OPPOSITE_RED_BAR")
        if reward_remaining < self.minimum_reward_remaining_pct:
            blockers.append("REWARD_CONSUMED")
        if spread_score <= 0:
            blockers.append("SPREAD")
        if liquidity_score <= 0:
            blockers.append("LIQUIDITY")
        if opportunity_score < self.minimum_opportunity_score:
            blockers.append(
                f"OPPORTUNITY_HEALTH={opportunity_score:.2f}<MIN={self.minimum_opportunity_score:.2f}"
            )

        eligible = not blockers
        decision = f"BUY {candidate.contract.option_type}" if eligible else "SKIP"
        reason = "OPPORTUNITY_HEALTH_PASS" if eligible else " | ".join(blockers)

        return OpportunityEvaluation(
            signal_id=signal_id,
            signal_age_seconds=round(float(signal_age_seconds), 2),
            entry_mode=entry_mode,
            direction=direction,
            opportunity_score=opportunity_score,
            structure_score=round(structure_score, 2),
            momentum_score=round(momentum_score, 2),
            reward_score=round(reward_score, 2),
            option_health_score=round(option_health_score, 2),
            market_context_score=round(market_context_score, 2),
            time_score=round(time_score, 2),
            reward_remaining_pct=reward_remaining,
            move_consumed_pct=move_consumed,
            structure_valid=structure_valid,
            opposite_red_bar=bool(opposite_red_bar_confirmed),
            candidate_score=round(candidate_score, 2),
            spread_score=round(spread_score, 2),
            liquidity_score=round(liquidity_score, 2),
            vwap_score=round(vwap_score, 2),
            ema_score=round(ema_score, 2),
            raw_momentum_score=round(raw_momentum, 2),
            eligible=eligible,
            decision=decision,
            reason=reason,
        )
