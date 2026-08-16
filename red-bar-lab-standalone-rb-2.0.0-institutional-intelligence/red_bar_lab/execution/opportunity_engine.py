from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from red_bar_lab.execution.execution_policy import is_rsi_primary


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
    """Evaluate whether a confirmed Red Bar still has current entry edge.

    Reward Remaining / Move Consumed remain calculated for research and historical
    comparison, but they no longer have execution authority. The production paper
    monitor adds completed-underlying 5-minute EMA10 continuation as the trend gate.
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
        # Backward-compatible research threshold only.
        self.minimum_reward_remaining_pct = float(minimum_reward_remaining_pct)
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
        """Legacy research geometry for remaining/consumed opportunity.

        This is retained only so old/new behavior can be compared historically.
        It no longer blocks a trade.
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
        signal_source = str(
            signal.get("signal_source")
            or signal.get("source")
            or ""
        ).upper()
        is_directional_regime = (
            signal_source == "DIRECTIONAL_REGIME_INTELLIGENCE"
            or signal_id.startswith("DRI-")
        )
        rsi_primary = is_rsi_primary(signal)
        red_bar_alignment = str(
            signal.get("red_bar_alignment") or ""
        ).upper()
        effective_opposite_red_bar = bool(
            opposite_red_bar_confirmed
        )
        if is_directional_regime:
            effective_opposite_red_bar = red_bar_alignment in {
                "OPPOSITE",
                "OPPOSITE_DIRECTION",
                "CONFLICT",
                "BEARISH_FOR_BULLISH",
                "BULLISH_FOR_BEARISH",
            }

        high = _num(signal.get("confirmation_high"))
        low = _num(signal.get("confirmation_low"))
        close = _num(
            signal.get("confirmation_close"),
            _num(signal.get("underlying_entry"), spot_price),
        )

        structure_valid = (
            True
            if rsi_primary
            else self._structure_valid(
                direction=direction,
                spot_price=float(spot_price),
                confirmation_high=high,
                confirmation_low=low,
            )
        )
        if rsi_primary:
            effective_opposite_red_bar = False
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
            (
                100.0 if spread_score > 0 and liquidity_score > 0 else 0.0
            )
            if rsi_primary
            else (
                structure_score + vwap_health + ema_health + momentum_score
                + volume_health + oi_health
                + liquidity_health + spread_health
            ),
            2,
        )

        entry_mode = (
            "FRESH_SIGNAL"
            if float(signal_age_seconds) <= float(freshness_seconds)
            else "OPPORTUNITY_EXTENSION"
        )

        blockers: list[str] = []
        if not rsi_primary and not structure_valid:
            blockers.append("STRUCTURE_INVALID")
        if not rsi_primary and effective_opposite_red_bar:
            blockers.append("OPPOSITE_RED_BAR")
        # REWARD_CONSUMED intentionally removed from execution blockers.
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
        reason = (
            "RSI_ENTRY_POLICY_PASS | EMA_RED_BAR_DRI_INFORMATIONAL_ONLY"
            if eligible and rsi_primary
            else "OPPORTUNITY_HEALTH_PASS | REWARD_METRICS_INFORMATIONAL_ONLY"
            if eligible
            else " | ".join(blockers)
        )

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
            opposite_red_bar=bool(effective_opposite_red_bar),
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
