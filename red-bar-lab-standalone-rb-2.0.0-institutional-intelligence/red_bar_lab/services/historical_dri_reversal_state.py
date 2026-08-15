from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import pandas as pd

from red_bar_lab.services.historical_dri_refinements import (
    strong_expansion_candle,
)


class ReversalState(str, Enum):
    NEUTRAL = "NEUTRAL"
    ACTIVE_BULLISH = "ACTIVE_BULLISH"
    ACTIVE_BEARISH = "ACTIVE_BEARISH"
    PENDING_BULLISH_REVERSAL = "PENDING_BULLISH_REVERSAL"
    PENDING_BEARISH_REVERSAL = "PENDING_BEARISH_REVERSAL"
    PROVISIONAL_BULLISH_REVERSAL = "PROVISIONAL_BULLISH_REVERSAL"
    PROVISIONAL_BEARISH_REVERSAL = "PROVISIONAL_BEARISH_REVERSAL"


@dataclass(frozen=True)
class ReversalDecision:
    state: ReversalState
    confirmed: bool
    reason: str
    provisional: bool = False
    ema10_ok: bool | None = None
    ema30_ok: bool | None = None


class HistoricalDRIReversalStateMachine:
    """Historical-only reversal confirmation from completed underlying candles."""

    def __init__(self, confirmation_window_bars: int = 5) -> None:
        self.state = ReversalState.NEUTRAL
        self.active_direction: str | None = None
        self.last_invalidation: float | None = None
        self.pending_direction: str | None = None
        self.pending_started_at: pd.Timestamp | None = None
        self.pending_count: int = 0
        self.confirmation_window_bars = int(confirmation_window_bars)

    @staticmethod
    def _frame(candles: pd.DataFrame | None, moment) -> pd.DataFrame:
        if (
            candles is None
            or candles.empty
            or "timestamp" not in candles.columns
            or moment is None
        ):
            return pd.DataFrame()
        result = candles.copy()
        result["timestamp"] = pd.to_datetime(
            result["timestamp"], errors="coerce", utc=True
        ).dt.tz_convert("Asia/Kolkata")
        moment = pd.Timestamp(moment)
        if moment.tzinfo is None:
            moment = moment.tz_localize("Asia/Kolkata")
        else:
            moment = moment.tz_convert("Asia/Kolkata")
        result = result.loc[result["timestamp"] <= moment].copy()
        for column in ("open", "high", "low", "close"):
            result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result.dropna(
            subset=["timestamp", "open", "high", "low", "close"]
        ).sort_values("timestamp")
        if not result.empty:
            result["ema10"] = result["close"].ewm(
                span=10, adjust=False
            ).mean()
            result["ema30"] = result["close"].ewm(
                span=30, adjust=False
            ).mean()
        return result

    def record_taken(self, direction: str, *, invalidation_level: float) -> None:
        direction = str(direction or "").upper()
        self.active_direction = direction
        self.last_invalidation = float(invalidation_level)
        self.pending_direction = None
        self.pending_started_at = None
        self.pending_count = 0
        self.state = (
            ReversalState.ACTIVE_BULLISH
            if direction == "BULLISH"
            else ReversalState.ACTIVE_BEARISH
        )

    def _update_dynamic_invalidation(self, frame: pd.DataFrame) -> None:
        if self.active_direction is None or frame.empty:
            return
        recent = frame.tail(self.confirmation_window_bars)
        if self.active_direction == "BULLISH":
            candidate = float(recent["low"].min())
            self.last_invalidation = (
                candidate
                if self.last_invalidation is None
                else max(float(self.last_invalidation), candidate)
            )
        else:
            candidate = float(recent["high"].max())
            self.last_invalidation = (
                candidate
                if self.last_invalidation is None
                else min(float(self.last_invalidation), candidate)
            )

    @staticmethod
    def _two_directional_closes(frame: pd.DataFrame, direction: str) -> bool:
        if len(frame) < 2:
            return False
        last_two = frame.tail(2)
        if direction == "BULLISH":
            return bool(
                (last_two["close"] > last_two["open"]).all()
                and last_two["close"].is_monotonic_increasing
            )
        return bool(
            (last_two["close"] < last_two["open"]).all()
            and last_two["close"].is_monotonic_decreasing
        )

    @staticmethod
    def _ema_evidence(
        frame: pd.DataFrame,
        direction: str,
    ) -> tuple[bool, bool]:
        if len(frame) < 2:
            return False, False
        latest = frame.iloc[-1]
        previous = frame.iloc[-2]
        close = float(latest["close"])
        ema10 = float(latest["ema10"])
        ema10_prev = float(previous["ema10"])
        ema30 = float(latest["ema30"])
        ema30_prev = float(previous["ema30"])

        ema30_ready = len(frame) >= 30
        if direction == "BULLISH":
            ema10_ok = close > ema10 and ema10 > ema10_prev
            ema30_ok = (
                ema30_ready
                and close > ema30
                and ema30 > ema30_prev
            )
        else:
            ema10_ok = close < ema10 and ema10 < ema10_prev
            ema30_ok = (
                ema30_ready
                and close < ema30
                and ema30 < ema30_prev
            )
        return bool(ema10_ok), bool(ema30_ok)

    def evaluate_opposite_event(
        self,
        direction: str,
        *,
        close_price: float,
        metrics: dict,
        setup_type: str,
        candles: pd.DataFrame | None = None,
        moment=None,
    ) -> ReversalDecision:
        direction = str(direction or "").upper()
        setup_type = str(setup_type or "").upper()
        use_candles = (
            candles is not None and moment is not None and not candles.empty
        )
        frame = self._frame(candles, moment) if use_candles else pd.DataFrame()

        if self.active_direction is None:
            return ReversalDecision(self.state, False, "NO_ACTIVE_REGIME")

        if direction == self.active_direction:
            self.pending_direction = None
            self.pending_started_at = None
            self.pending_count = 0
            self._update_dynamic_invalidation(frame)
            self.state = (
                ReversalState.ACTIVE_BULLISH
                if direction == "BULLISH"
                else ReversalState.ACTIVE_BEARISH
            )
            return ReversalDecision(
                self.state, False, "SAME_DIRECTION_CONTINUATION"
            )

        expected_setup = (
            "EARLY_1M_BULLISH_BREAK"
            if direction == "BULLISH"
            else "EARLY_1M_BEARISH_BREAK"
        )
        if setup_type != expected_setup:
            return ReversalDecision(
                self.state, False, "OPPOSITE_EVENT_NOT_STRUCTURE_BREAK"
            )

        if self.pending_direction != direction:
            self.pending_direction = direction
            self.pending_started_at = pd.Timestamp(moment) if moment else None
            self.pending_count = 1
        else:
            self.pending_count += 1

        recent = frame.tail(self.confirmation_window_bars)
        momentum_ok = bool(metrics.get("momentum_ok"))
        two_closes = (
            self._two_directional_closes(recent, direction)
            if use_candles
            else self.pending_count >= 2
        )
        if use_candles:
            ema10_ok, ema30_ok = self._ema_evidence(recent, direction)
        else:
            legacy_ema = bool(metrics.get("ema_ok") is True)
            ema10_ok, ema30_ok = legacy_ema, legacy_ema

        invalidation_broken = (
            self.last_invalidation is not None
            and (
                float(close_price) > float(self.last_invalidation)
                if direction == "BULLISH"
                else float(close_price) < float(self.last_invalidation)
            )
        )

        expansion_candle = (
            strong_expansion_candle(recent, direction)
            if use_candles else False
        )
        directional_confirmation = bool(
            two_closes or expansion_candle
        )
        provisional = bool(
            momentum_ok and directional_confirmation and ema10_ok
        )
        confirmed = bool(
            provisional and (invalidation_broken or ema30_ok)
        )

        if confirmed:
            self.active_direction = direction
            self.last_invalidation = None
            self.pending_direction = None
            self.pending_started_at = None
            self.pending_count = 0
            self.state = (
                ReversalState.ACTIVE_BULLISH
                if direction == "BULLISH"
                else ReversalState.ACTIVE_BEARISH
            )
            reason = (
                "CONFIRMED_REVERSAL_INVALIDATION"
                if invalidation_broken
                else "CONFIRMED_REVERSAL_EMA30"
            )
            return ReversalDecision(
                self.state,
                True,
                reason,
                provisional=False,
                ema10_ok=ema10_ok,
                ema30_ok=ema30_ok,
            )

        if provisional:
            self.state = (
                ReversalState.PROVISIONAL_BULLISH_REVERSAL
                if direction == "BULLISH"
                else ReversalState.PROVISIONAL_BEARISH_REVERSAL
            )
            return ReversalDecision(
                self.state,
                False,
                "PROVISIONAL_REVERSAL_AWAITING_EMA30_OR_INVALIDATION",
                provisional=True,
                ema10_ok=ema10_ok,
                ema30_ok=ema30_ok,
            )

        self.state = (
            ReversalState.PENDING_BULLISH_REVERSAL
            if direction == "BULLISH"
            else ReversalState.PENDING_BEARISH_REVERSAL
        )
        missing = []
        if not momentum_ok:
            missing.append("MOMENTUM")
        if not two_closes:
            missing.append("TWO_UNDERLYING_CLOSES_OR_EXPANSION")
        if not ema10_ok:
            missing.append("EMA_FLIP_EMA10")
        return ReversalDecision(
            self.state,
            False,
            "PENDING_REVERSAL_" + "_".join(missing),
            provisional=False,
            ema10_ok=ema10_ok,
            ema30_ok=ema30_ok,
        )
