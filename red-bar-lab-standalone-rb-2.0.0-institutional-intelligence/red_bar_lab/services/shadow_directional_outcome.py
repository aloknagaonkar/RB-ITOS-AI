from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class ShadowDirectionalOutcome:
    signal_timestamp: pd.Timestamp
    direction: str
    entry_price: float
    price_after_5m: float | None
    price_after_15m: float | None
    price_after_30m: float | None
    move_after_5m: float | None
    move_after_15m: float | None
    move_after_30m: float | None
    maximum_favorable_excursion: float | None
    maximum_adverse_excursion: float | None
    direction_correct_5m: bool | None
    direction_correct_15m: bool | None
    direction_correct_30m: bool | None
    fully_resolved: bool

    def as_record(self) -> dict[str, object]:
        return {
            "signal_timestamp": self.signal_timestamp.isoformat(),
            "direction": self.direction,
            "entry_price": self.entry_price,
            "price_after_5m": self.price_after_5m,
            "price_after_15m": self.price_after_15m,
            "price_after_30m": self.price_after_30m,
            "move_after_5m": self.move_after_5m,
            "move_after_15m": self.move_after_15m,
            "move_after_30m": self.move_after_30m,
            "maximum_favorable_excursion": self.maximum_favorable_excursion,
            "maximum_adverse_excursion": self.maximum_adverse_excursion,
            "direction_correct_5m": self.direction_correct_5m,
            "direction_correct_15m": self.direction_correct_15m,
            "direction_correct_30m": self.direction_correct_30m,
            "fully_resolved": self.fully_resolved,
            "execution_allowed": False,
        }


def _directional_move(direction: str, entry: float, future: float) -> float:
    raw = future - entry
    return raw if direction == "BULLISH" else -raw


def _correct(move: float | None) -> bool | None:
    return None if move is None else move > 0


def evaluate_shadow_outcome(
    candles: pd.DataFrame,
    transition: Mapping[str, object],
    *,
    horizon_minutes: int = 30,
) -> ShadowDirectionalOutcome:
    """Evaluate future movement without using candles unavailable at signal time."""
    if candles is None or candles.empty:
        raise ValueError("Outcome evaluation requires candle data.")

    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = (
        frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )

    signal_ts = pd.Timestamp(
        transition.get("candle_timestamp") or transition.get("timestamp")
    )
    direction = str(transition.get("direction") or "").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("Outcome evaluation supports BULLISH or BEARISH transitions.")

    matches = frame.index[frame["timestamp"] == signal_ts].tolist()
    if not matches:
        raise ValueError("Signal candle timestamp is not present in candle data.")

    index = matches[-1]
    entry = float(frame.iloc[index]["close"])

    def checkpoint(minutes: int) -> float | None:
        bars = minutes // 5
        target = index + bars
        if target >= len(frame):
            return None
        return float(frame.iloc[target]["close"])

    p5 = checkpoint(5)
    p15 = checkpoint(15)
    p30 = checkpoint(30)

    available_end = min(index + horizon_minutes // 5, len(frame) - 1)
    future = frame.iloc[index + 1 : available_end + 1]

    mfe = None
    mae = None
    if not future.empty:
        if direction == "BULLISH":
            mfe = float(future["high"].max()) - entry
            mae = entry - float(future["low"].min())
        else:
            mfe = entry - float(future["low"].min())
            mae = float(future["high"].max()) - entry
        mfe = max(0.0, mfe)
        mae = max(0.0, mae)

    m5 = None if p5 is None else _directional_move(direction, entry, p5)
    m15 = None if p15 is None else _directional_move(direction, entry, p15)
    m30 = None if p30 is None else _directional_move(direction, entry, p30)

    return ShadowDirectionalOutcome(
        signal_timestamp=signal_ts,
        direction=direction,
        entry_price=entry,
        price_after_5m=p5,
        price_after_15m=p15,
        price_after_30m=p30,
        move_after_5m=m5,
        move_after_15m=m15,
        move_after_30m=m30,
        maximum_favorable_excursion=mfe,
        maximum_adverse_excursion=mae,
        direction_correct_5m=_correct(m5),
        direction_correct_15m=_correct(m15),
        direction_correct_30m=_correct(m30),
        fully_resolved=p30 is not None,
    )
