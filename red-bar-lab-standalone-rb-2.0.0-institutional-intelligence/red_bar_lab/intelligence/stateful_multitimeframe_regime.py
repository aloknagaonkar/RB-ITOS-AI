from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


REGIMES = (
    "BULLISH",
    "BEARISH",
    "SIDEWAYS",
    "TRANSITION_BULLISH",
    "TRANSITION_BEARISH",
    "CONFLICT",
)


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("Multi-timeframe regime evaluation requires candle data.")
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce")
    result = (
        result.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
    if len(result) < 35:
        raise ValueError("At least 35 completed candles are required per timeframe.")
    return result


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False).mean()


def _atr(frame: pd.DataFrame, length: int = 14) -> float:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = true_range.rolling(length, min_periods=length).mean().iloc[-1]
    if pd.isna(value):
        return 0.0
    return max(0.0, float(value))


def _confirmed_pivots(
    frame: pd.DataFrame,
    *,
    left: int = 2,
    right: int = 2,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    highs = frame["high"].astype(float).reset_index(drop=True)
    lows = frame["low"].astype(float).reset_index(drop=True)
    timestamps = frame["timestamp"].reset_index(drop=True)

    pivot_highs: list[dict[str, object]] = []
    pivot_lows: list[dict[str, object]] = []

    for index in range(left, len(frame) - right):
        high_window = highs.iloc[index-left:index+right+1]
        low_window = lows.iloc[index-left:index+right+1]
        current_high = float(highs.iloc[index])
        current_low = float(lows.iloc[index])

        if current_high == float(high_window.max()) and (high_window == current_high).sum() == 1:
            pivot_highs.append({
                "timestamp": pd.Timestamp(timestamps.iloc[index]).isoformat(),
                "price": current_high,
                "index": index,
            })

        if current_low == float(low_window.min()) and (low_window == current_low).sum() == 1:
            pivot_lows.append({
                "timestamp": pd.Timestamp(timestamps.iloc[index]).isoformat(),
                "price": current_low,
                "index": index,
            })

    return pivot_highs, pivot_lows


def _confirmed_swing_geometry(
    frame: pd.DataFrame,
    *,
    minimum_distance_atr: float = 0.35,
) -> dict[str, object]:
    atr = _atr(frame)
    pivot_highs, pivot_lows = _confirmed_pivots(frame)

    if atr <= 0:
        return {
            "valid": False,
            "status": "STRUCTURE_UNAVAILABLE",
            "atr": atr,
            "swing_high": None,
            "swing_low": None,
            "swing_high_timestamp": None,
            "swing_low_timestamp": None,
            "pivot_highs": pivot_highs[-5:],
            "pivot_lows": pivot_lows[-5:],
        }

    if not pivot_highs or not pivot_lows:
        return {
            "valid": False,
            "status": "STRUCTURE_UNAVAILABLE",
            "atr": atr,
            "swing_high": None,
            "swing_low": None,
            "swing_high_timestamp": None,
            "swing_low_timestamp": None,
            "pivot_highs": pivot_highs[-5:],
            "pivot_lows": pivot_lows[-5:],
        }

    swing_high = pivot_highs[-1]
    swing_low = pivot_lows[-1]
    distance = abs(float(swing_high["price"]) - float(swing_low["price"]))

    if distance < atr * minimum_distance_atr:
        return {
            "valid": False,
            "status": "STRUCTURE_DISTANCE_TOO_SMALL",
            "atr": atr,
            "swing_high": float(swing_high["price"]),
            "swing_low": float(swing_low["price"]),
            "swing_high_timestamp": swing_high["timestamp"],
            "swing_low_timestamp": swing_low["timestamp"],
            "pivot_highs": pivot_highs[-5:],
            "pivot_lows": pivot_lows[-5:],
        }

    return {
        "valid": True,
        "status": "CONFIRMED",
        "atr": atr,
        "swing_high": float(swing_high["price"]),
        "swing_low": float(swing_low["price"]),
        "swing_high_timestamp": swing_high["timestamp"],
        "swing_low_timestamp": swing_low["timestamp"],
        "pivot_highs": pivot_highs[-5:],
        "pivot_lows": pivot_lows[-5:],
    }


def _structure(frame: pd.DataFrame) -> dict[str, bool]:
    pivot_highs, pivot_lows = _confirmed_pivots(frame)

    higher_high = (
        len(pivot_highs) >= 2
        and float(pivot_highs[-1]["price"]) > float(pivot_highs[-2]["price"])
    )
    lower_high = (
        len(pivot_highs) >= 2
        and float(pivot_highs[-1]["price"]) < float(pivot_highs[-2]["price"])
    )
    higher_low = (
        len(pivot_lows) >= 2
        and float(pivot_lows[-1]["price"]) > float(pivot_lows[-2]["price"])
    )
    lower_low = (
        len(pivot_lows) >= 2
        and float(pivot_lows[-1]["price"]) < float(pivot_lows[-2]["price"])
    )

    return {
        "higher_high": bool(higher_high),
        "higher_low": bool(higher_low),
        "lower_high": bool(lower_high),
        "lower_low": bool(lower_low),
    }


def _facts(frame: pd.DataFrame) -> dict[str, object]:
    close = frame["close"].astype(float)
    ema10 = _ema(close, 10)
    ema30 = _ema(close, 30)
    slope10 = float(ema10.iloc[-1] - ema10.iloc[-4])
    momentum = float(close.iloc[-1] - close.iloc[-4])
    geometry = _confirmed_swing_geometry(frame)
    structure = _structure(frame)

    breakout = (
        bool(geometry["valid"])
        and float(close.iloc[-1]) > float(geometry["swing_high"])
    )
    breakdown = (
        bool(geometry["valid"])
        and float(close.iloc[-1]) < float(geometry["swing_low"])
    )

    return {
        "timestamp": frame.iloc[-1]["timestamp"],
        "close": float(close.iloc[-1]),
        "ema10": float(ema10.iloc[-1]),
        "ema30": float(ema30.iloc[-1]),
        "ema10_slope": slope10,
        "momentum": momentum,
        "swing_high": geometry["swing_high"],
        "swing_low": geometry["swing_low"],
        "swing_high_timestamp": geometry["swing_high_timestamp"],
        "swing_low_timestamp": geometry["swing_low_timestamp"],
        "structure_valid": bool(geometry["valid"]),
        "structure_status": geometry["status"],
        "atr": float(geometry["atr"]),
        "pivot_highs": geometry["pivot_highs"],
        "pivot_lows": geometry["pivot_lows"],
        "breakout": breakout,
        "breakdown": breakdown,
        **structure,
    }


@dataclass(frozen=True)
class StatefulRegimeSnapshot:
    timestamp: str
    previous_regime: str
    current_regime: str
    bullish_score: int
    bearish_score: int
    transition_stage: str
    transition_progress: int
    five_minute_regime: str
    one_minute_state: str
    last_swing_high: float | None
    last_swing_low: float | None
    swing_high_timestamp: str | None
    swing_low_timestamp: str | None
    structure_status: str
    break_level: float | None
    invalidation_level: float | None
    structure_diagnostics: tuple[dict[str, object], ...]
    evidence: tuple[str, ...]
    red_bar_support: str
    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "evidence": list(self.evidence),
            "structure_diagnostics": [dict(item) for item in self.structure_diagnostics],
            "execution_allowed": False,
        }


def _scores(five: Mapping[str, object], one: Mapping[str, object]) -> tuple[int, int, list[str]]:
    bull = bear = 0
    evidence: list[str] = []

    if five["close"] > five["ema10"]:
        bull += 20; evidence.append("5M_CLOSE_ABOVE_EMA10")
    else:
        bear += 20; evidence.append("5M_CLOSE_BELOW_EMA10")

    if five["ema10_slope"] > 0:
        bull += 15; evidence.append("5M_EMA10_RISING")
    elif five["ema10_slope"] < 0:
        bear += 15; evidence.append("5M_EMA10_FALLING")

    if one["ema10"] > one["ema30"]:
        bull += 15; evidence.append("1M_EMA10_ABOVE_EMA30")
    else:
        bear += 15; evidence.append("1M_EMA10_BELOW_EMA30")

    if one["structure_valid"]:
        if one["higher_high"]:
            bull += 15; evidence.append("1M_HIGHER_HIGH")
        if one["higher_low"]:
            bull += 15; evidence.append("1M_HIGHER_LOW")
        if one["lower_high"]:
            bear += 15; evidence.append("1M_LOWER_HIGH")
        if one["lower_low"]:
            bear += 15; evidence.append("1M_LOWER_LOW")
    else:
        evidence.append(str(one["structure_status"]))

    if one["breakout"]:
        bull += 10; evidence.append("1M_STRUCTURE_BREAKOUT")
    if one["breakdown"]:
        bear += 10; evidence.append("1M_STRUCTURE_BREAKDOWN")

    if one["momentum"] > 0:
        bull += 10; evidence.append("1M_POSITIVE_MOMENTUM")
    elif one["momentum"] < 0:
        bear += 10; evidence.append("1M_NEGATIVE_MOMENTUM")

    return min(100, bull), min(100, bear), evidence


def _classify(bull: int, bear: int) -> str:
    if bull >= 70 and bear < 40:
        return "BULLISH"
    if bear >= 70 and bull < 40:
        return "BEARISH"
    if bull < 55 and bear < 55:
        return "SIDEWAYS"
    if abs(bull - bear) <= 15:
        return "CONFLICT"
    return "TRANSITION_BULLISH" if bull > bear else "TRANSITION_BEARISH"


def _transition_stage(previous: str, current: str, one: Mapping[str, object]) -> tuple[str, int]:
    if current in {"BULLISH", "TRANSITION_BULLISH"}:
        stages = [
            ("BULLISH_HIGHER_LOW_FORMED", one["higher_low"]),
            ("BULLISH_EMA10_RECLAIMED", one["close"] > one["ema10"]),
            ("BULLISH_EMA10_SLOPE_POSITIVE", one["ema10_slope"] > 0),
            ("BULLISH_STRUCTURE_BREAK", one["breakout"]),
            ("BULLISH_EMA10_ABOVE_EMA30", one["ema10"] > one["ema30"]),
        ]
    elif current in {"BEARISH", "TRANSITION_BEARISH"}:
        stages = [
            ("BEARISH_LOWER_HIGH_FORMED", one["lower_high"]),
            ("BEARISH_EMA10_LOST", one["close"] < one["ema10"]),
            ("BEARISH_EMA10_SLOPE_NEGATIVE", one["ema10_slope"] < 0),
            ("BEARISH_STRUCTURE_BREAK", one["breakdown"]),
            ("BEARISH_EMA10_BELOW_EMA30", one["ema10"] < one["ema30"]),
        ]
    else:
        return ("NO_ACTIVE_TRANSITION", 0)

    completed = [name for name, ok in stages if ok]
    if not completed:
        return ("TRANSITION_WATCH", 0)
    return completed[-1], len(completed)


class StatefulMultiTimeframeRegimeEngine:
    def evaluate(
        self,
        one_minute_candles: pd.DataFrame,
        five_minute_candles: pd.DataFrame,
        *,
        previous_state: Mapping[str, object] | None = None,
        red_bar_context: Mapping[str, object] | None = None,
    ) -> StatefulRegimeSnapshot:
        one = _facts(_prepare(one_minute_candles))
        five = _facts(_prepare(five_minute_candles))
        bull, bear, evidence = _scores(five, one)
        current = _classify(bull, bear)
        previous = str((previous_state or {}).get("current_regime") or "UNKNOWN")
        stage, progress = _transition_stage(previous, current, one)

        direction = "BULLISH" if bull > bear else "BEARISH"
        if one["structure_valid"]:
            break_level = one["swing_high"] if direction == "BULLISH" else one["swing_low"]
            invalidation = one["swing_low"] if direction == "BULLISH" else one["swing_high"]
        else:
            break_level = None
            invalidation = None

        red_bar_direction = str((red_bar_context or {}).get("direction") or "")
        red_bar_support = (
            "ALIGNED" if red_bar_direction == direction
            else "COUNTER_TREND" if red_bar_direction
            else "NOT_AVAILABLE"
        )

        return StatefulRegimeSnapshot(
            timestamp=pd.Timestamp(five["timestamp"]).isoformat(),
            previous_regime=previous,
            current_regime=current,
            bullish_score=bull,
            bearish_score=bear,
            transition_stage=stage,
            transition_progress=progress,
            five_minute_regime=(
                "BULLISH" if five["close"] > five["ema10"] and five["ema10_slope"] > 0
                else "BEARISH" if five["close"] < five["ema10"] and five["ema10_slope"] < 0
                else "SIDEWAYS"
            ),
            one_minute_state=(
                "BULLISH_STRUCTURE" if one["higher_high"] or one["higher_low"]
                else "BEARISH_STRUCTURE" if one["lower_high"] or one["lower_low"]
                else "NEUTRAL"
            ),
            last_swing_high=(
                float(one["swing_high"]) if one["swing_high"] is not None else None
            ),
            last_swing_low=(
                float(one["swing_low"]) if one["swing_low"] is not None else None
            ),
            swing_high_timestamp=one["swing_high_timestamp"],
            swing_low_timestamp=one["swing_low_timestamp"],
            structure_status=str(one["structure_status"]),
            break_level=(
                float(break_level) if break_level is not None else None
            ),
            invalidation_level=(
                float(invalidation) if invalidation is not None else None
            ),
            structure_diagnostics=tuple(
                [{"type": "PIVOT_HIGH", **item} for item in one["pivot_highs"]]
                + [{"type": "PIVOT_LOW", **item} for item in one["pivot_lows"]]
            ),
            evidence=tuple(evidence),
            red_bar_support=red_bar_support,
            execution_allowed=False,
        )
