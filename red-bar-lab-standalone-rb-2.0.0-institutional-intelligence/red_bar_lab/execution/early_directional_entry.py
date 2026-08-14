from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import json

import pandas as pd

IST = "Asia/Kolkata"


def _ema(series: pd.Series, length: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float).ewm(
        span=length,
        adjust=False,
    ).mean()


def _confirmed_pivots(
    frame: pd.DataFrame,
    left: int = 2,
    right: int = 2,
):
    highs = pd.to_numeric(frame["high"], errors="coerce").reset_index(drop=True)
    lows = pd.to_numeric(frame["low"], errors="coerce").reset_index(drop=True)
    timestamps = frame["timestamp"].reset_index(drop=True)

    pivot_highs = []
    pivot_lows = []

    for index in range(left, len(frame) - right):
        high_window = highs.iloc[index - left:index + right + 1]
        low_window = lows.iloc[index - left:index + right + 1]
        current_high = float(highs.iloc[index])
        current_low = float(lows.iloc[index])

        if (
            current_high == float(high_window.max())
            and int((high_window == current_high).sum()) == 1
        ):
            pivot_highs.append(
                (pd.Timestamp(timestamps.iloc[index]), current_high)
            )

        if (
            current_low == float(low_window.min())
            and int((low_window == current_low).sum()) == 1
        ):
            pivot_lows.append(
                (pd.Timestamp(timestamps.iloc[index]), current_low)
            )

    return pivot_highs, pivot_lows


@dataclass(frozen=True)
class EarlyDirectionalDecision:
    status: str
    reason: str
    direction: str | None = None
    bundle: dict[str, object] | None = None


class EarlyOneMinuteDirectionalEntryEngine:
    """Generate a short-lived early DRI bundle from completed 1-minute candles."""

    def __init__(
        self,
        *,
        freshness_minutes: int = 4,
        minimum_body_ratio: float = 0.55,
    ):
        self.freshness_minutes = max(1, int(freshness_minutes))
        self.minimum_body_ratio = float(minimum_body_ratio)

    def evaluate(
        self,
        one_minute: pd.DataFrame,
        *,
        five_minute_regime: str,
        instrument_key: str,
    ) -> EarlyDirectionalDecision:
        if one_minute is None or len(one_minute) < 35:
            return EarlyDirectionalDecision(
                "NO_SIGNAL",
                "INSUFFICIENT_1M_CANDLES",
            )

        frame = (
            one_minute.copy()
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        close = pd.to_numeric(frame["close"], errors="coerce").astype(float)
        open_ = pd.to_numeric(frame["open"], errors="coerce").astype(float)
        high = pd.to_numeric(frame["high"], errors="coerce").astype(float)
        low = pd.to_numeric(frame["low"], errors="coerce").astype(float)

        ema10 = _ema(close, 10)
        ema30 = _ema(close, 30)
        pivot_highs, pivot_lows = _confirmed_pivots(frame)

        if not pivot_highs or not pivot_lows:
            return EarlyDirectionalDecision(
                "NO_SIGNAL",
                "CONFIRMED_SWING_UNAVAILABLE",
            )

        candle_range = max(
            1e-9,
            float(high.iloc[-1] - low.iloc[-1]),
        )
        body = abs(float(close.iloc[-1] - open_.iloc[-1]))
        body_ratio = body / candle_range

        timestamp = pd.Timestamp(frame.iloc[-1]["timestamp"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(IST)
        else:
            timestamp = timestamp.tz_convert(IST)

        last_high = float(pivot_highs[-1][1])
        last_low = float(pivot_lows[-1][1])

        bullish = (
            float(close.iloc[-1]) > last_high
            and float(close.iloc[-2]) <= last_high
            and float(close.iloc[-1]) > float(open_.iloc[-1])
            and float(ema10.iloc[-1]) > float(ema30.iloc[-1])
            and float(ema10.iloc[-1]) > float(ema10.iloc[-3])
            and float(close.iloc[-1]) > float(close.iloc[-4])
            and body_ratio >= self.minimum_body_ratio
        )

        bearish = (
            float(close.iloc[-1]) < last_low
            and float(close.iloc[-2]) >= last_low
            and float(close.iloc[-1]) < float(open_.iloc[-1])
            and float(ema10.iloc[-1]) < float(ema30.iloc[-1])
            and float(ema10.iloc[-1]) < float(ema10.iloc[-3])
            and float(close.iloc[-1]) < float(close.iloc[-4])
            and body_ratio >= self.minimum_body_ratio
        )

        five = str(five_minute_regime or "SIDEWAYS").upper()

        if bullish and five == "BEARISH":
            return EarlyDirectionalDecision(
                "BLOCKED",
                "OPPOSITE_5M_BEARISH",
            )

        if bearish and five == "BULLISH":
            return EarlyDirectionalDecision(
                "BLOCKED",
                "OPPOSITE_5M_BULLISH",
            )

        if not bullish and not bearish:
            return EarlyDirectionalDecision(
                "NO_SIGNAL",
                "NO_FRESH_1M_STRUCTURE_BREAK",
            )

        direction = "BULLISH" if bullish else "BEARISH"
        trigger = last_high if bullish else last_low
        invalidation = last_low if bullish else last_high
        compact = timestamp.strftime("%Y%m%dT%H%M%S%z")

        bundle = {
            "bundle_id": f"BND-EARLY-1M-{direction}-{compact}",
            "direction": direction,
            "detected_at": timestamp.isoformat(),
            "fresh_until": (
                timestamp + timedelta(minutes=self.freshness_minutes)
            ).isoformat(),
            "primary_signal_id": (
                f"SIG-EARLY-1M-{direction}-{compact}"
            ),
            "primary_setup_type": (
                f"EARLY_1M_{direction}_STRUCTURE_BREAK"
            ),
            "supporting_signal_ids": [],
            "supporting_setup_types": [
                "1M_EMA_ALIGNMENT",
                "1M_MOMENTUM_DISPLACEMENT",
                f"5M_{five}_NON_OPPOSING",
            ],
            "trigger_level": trigger,
            "invalidation_level": invalidation,
            "red_bar_alignment": "NOT_REQUIRED",
            "current_regime": f"EARLY_{direction}",
            "entry_stage": "EARLY_1M",
            "five_minute_confirmation": five,
            "candidate_limit": 1,
            "source": "PAPER_TRADING_BACKGROUND_EARLY_1M",
            "instrument_key": instrument_key,
            "execution_allowed": False,
        }

        return EarlyDirectionalDecision(
            "READY",
            "EARLY_1M_DIRECTIONAL_BUNDLE_READY",
            direction,
            bundle,
        )


def append_bundle_once(
    path: str | Path,
    bundle: dict[str, object],
) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    bundle_id = str(bundle.get("bundle_id") or "")

    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            try:
                existing = json.loads(line)
            except Exception:
                continue
            if str(existing.get("bundle_id") or "") == bundle_id:
                return False

    with target.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                bundle,
                separators=(",", ":"),
                default=str,
            )
            + "\n"
        )
    return True
