from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class ReentryResetConfig:
    reset_lookback_minutes: int = 20
    minimum_reset_bars: int = 2
    reset_tolerance_points: float = 12.0
    minimum_rebreak_points: float = 3.0
    minimum_momentum_body_ratio: float = 0.45


@dataclass(frozen=True)
class ReentryDecision:
    allowed: bool
    reason: str
    reset_seen: bool
    fresh_structure: bool
    momentum_reexpanded: bool


class ResetAndRebreakGate:
    def __init__(self, config: ReentryResetConfig | None = None) -> None:
        self.config = config or ReentryResetConfig()
        self._last_taken: dict[str, dict[str, object]] = {}

    @staticmethod
    def _to_ist(frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty or "timestamp" not in frame.columns:
            return pd.DataFrame()
        result = frame.copy()
        result["timestamp"] = pd.to_datetime(
            result["timestamp"], errors="coerce", utc=True
        ).dt.tz_convert("Asia/Kolkata")
        return result.dropna(subset=["timestamp"]).sort_values("timestamp")

    def record_taken(
        self,
        direction: str,
        moment,
        *,
        trigger_level: float,
        invalidation_level: float,
    ) -> None:
        self._last_taken[str(direction or "").upper()] = {
            "moment": pd.Timestamp(moment),
            "trigger": float(trigger_level),
            "invalidation": float(invalidation_level),
        }

    def reset_opposite(self, new_direction: str) -> None:
        direction = str(new_direction or "").upper()
        opposite = "BEARISH" if direction == "BULLISH" else "BULLISH"
        self._last_taken.pop(opposite, None)

    def evaluate(
        self,
        direction: str,
        moment,
        candles: pd.DataFrame,
        *,
        trigger_level: float,
        invalidation_level: float,
    ) -> ReentryDecision:
        direction = str(direction or "").upper()
        previous = self._last_taken.get(direction)
        if previous is None:
            return ReentryDecision(
                allowed=True,
                reason="FIRST_DIRECTIONAL_ENTRY",
                reset_seen=True,
                fresh_structure=True,
                momentum_reexpanded=True,
            )

        frame = self._to_ist(candles)
        if frame.empty:
            return ReentryDecision(
                allowed=False,
                reason="RESET_REBREAK_NO_CANDLES",
                reset_seen=False,
                fresh_structure=False,
                momentum_reexpanded=False,
            )

        now = pd.Timestamp(moment)
        if now.tzinfo is None:
            now = now.tz_localize("Asia/Kolkata")
        else:
            now = now.tz_convert("Asia/Kolkata")

        previous_moment = pd.Timestamp(previous["moment"])
        if previous_moment.tzinfo is None:
            previous_moment = previous_moment.tz_localize("Asia/Kolkata")
        else:
            previous_moment = previous_moment.tz_convert("Asia/Kolkata")

        start = max(
            previous_moment,
            now - pd.Timedelta(minutes=self.config.reset_lookback_minutes),
        )
        window = frame.loc[
            (frame["timestamp"] > start) & (frame["timestamp"] <= now)
        ].copy()

        if len(window) < int(self.config.minimum_reset_bars):
            return ReentryDecision(
                allowed=False,
                reason="RESET_REBREAK_INSUFFICIENT_BARS",
                reset_seen=False,
                fresh_structure=False,
                momentum_reexpanded=False,
            )

        for column in ("open", "high", "low", "close"):
            window[column] = pd.to_numeric(window[column], errors="coerce")
        window = window.dropna(subset=["open", "high", "low", "close"])
        if len(window) < int(self.config.minimum_reset_bars):
            return ReentryDecision(
                allowed=False,
                reason="RESET_REBREAK_INVALID_CANDLES",
                reset_seen=False,
                fresh_structure=False,
                momentum_reexpanded=False,
            )

        close = window["close"]
        ema10 = close.ewm(span=10, adjust=False).mean()
        tolerance = float(self.config.reset_tolerance_points)
        previous_trigger = float(previous["trigger"])
        previous_invalidation = float(previous["invalidation"])

        bullish_candle = window["close"] > window["open"]
        bearish_candle = window["close"] < window["open"]

        if direction == "BULLISH":
            reset_zone_touch = (
                (window["low"] <= ema10 + tolerance)
                | (window["low"] <= previous_trigger + tolerance)
                | (window["low"] <= previous_invalidation + tolerance)
            )
            reset_seen = bool((bearish_candle & reset_zone_touch).any())
            prior_high = float(window.iloc[:-1]["high"].max())
            fresh_structure = (
                float(trigger_level)
                >= prior_high + float(self.config.minimum_rebreak_points)
            )
        else:
            reset_zone_touch = (
                (window["high"] >= ema10 - tolerance)
                | (window["high"] >= previous_trigger - tolerance)
                | (window["high"] >= previous_invalidation - tolerance)
            )
            reset_seen = bool((bullish_candle & reset_zone_touch).any())
            prior_low = float(window.iloc[:-1]["low"].min())
            fresh_structure = (
                float(trigger_level)
                <= prior_low - float(self.config.minimum_rebreak_points)
            )

        last = window.iloc[-1]
        candle_range = max(float(last["high"]) - float(last["low"]), 1e-9)
        body = abs(float(last["close"]) - float(last["open"]))
        body_ratio = body / candle_range
        directional_close = (
            float(last["close"]) > float(last["open"])
            if direction == "BULLISH"
            else float(last["close"]) < float(last["open"])
        )
        momentum_reexpanded = bool(
            directional_close
            and body_ratio >= float(self.config.minimum_momentum_body_ratio)
        )

        if not reset_seen:
            reason = "NO_RESET_BEFORE_REBREAK"
        elif not fresh_structure:
            reason = "NO_FRESH_STRUCTURE_REBREAK"
        elif not momentum_reexpanded:
            reason = "MOMENTUM_NOT_REEXPANDED"
        else:
            reason = "RESET_AND_REBREAK_CONFIRMED"

        return ReentryDecision(
            allowed=bool(reset_seen and fresh_structure and momentum_reexpanded),
            reason=reason,
            reset_seen=bool(reset_seen),
            fresh_structure=bool(fresh_structure),
            momentum_reexpanded=bool(momentum_reexpanded),
        )
