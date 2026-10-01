"""Causal, observation-only T+5 entry-health calculations.

Only completed one-minute candles are consumed.  The candidate deliberately
returns UNAVAILABLE until every predeclared decision input is populated.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class _EMA:
    length: int
    value: float | None = None

    def update(self, value: float) -> float:
        alpha = 2.0 / (self.length + 1.0)
        self.value = value if self.value is None else self.value + alpha * (value - self.value)
        return self.value


@dataclass
class _Wilder:
    length: int
    seed: list[float] = field(default_factory=list)
    value: float | None = None

    def update(self, value: float) -> float | None:
        if self.value is None:
            self.seed.append(value)
            if len(self.seed) == self.length:
                self.value = statistics.mean(self.seed)
            return self.value
        self.value = ((self.length - 1) * self.value + value) / self.length
        return self.value


@dataclass
class _RSI:
    length: int
    previous: float | None = None
    gains: _Wilder = field(init=False)
    losses: _Wilder = field(init=False)

    def __post_init__(self) -> None:
        self.gains, self.losses = _Wilder(self.length), _Wilder(self.length)

    def update(self, close: float) -> float | None:
        if self.previous is None:
            self.previous = close
            return None
        change, self.previous = close - self.previous, close
        gain = self.gains.update(max(change, 0.0))
        loss = self.losses.update(max(-change, 0.0))
        if gain is None or loss is None:
            return None
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)


@dataclass
class MidpointEntryHealthLiveV1:
    """Sequential indicator state shared by all Midpoint trade families."""

    ema5: _EMA = field(default_factory=lambda: _EMA(5))
    ema9: _EMA = field(default_factory=lambda: _EMA(9))
    ema13: _EMA = field(default_factory=lambda: _EMA(13))
    ema21: _EMA = field(default_factory=lambda: _EMA(21))
    ema34: _EMA = field(default_factory=lambda: _EMA(34))
    ema50: _EMA = field(default_factory=lambda: _EMA(50))
    macd12: _EMA = field(default_factory=lambda: _EMA(12))
    macd26: _EMA = field(default_factory=lambda: _EMA(26))
    macd_signal: _EMA = field(default_factory=lambda: _EMA(9))
    rsi8: _RSI = field(default_factory=lambda: _RSI(8))
    rsi14: _RSI = field(default_factory=lambda: _RSI(14))
    tr14: _Wilder = field(default_factory=lambda: _Wilder(14))
    plus14: _Wilder = field(default_factory=lambda: _Wilder(14))
    minus14: _Wilder = field(default_factory=lambda: _Wilder(14))
    adx14: _Wilder = field(default_factory=lambda: _Wilder(14))
    volume20: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    previous_close: float | None = None
    previous_high: float | None = None
    previous_low: float | None = None
    previous_hist: float | None = None
    bars: int = 0
    five_rsi14: _RSI = field(default_factory=lambda: _RSI(14))
    five_ema9: _EMA = field(default_factory=lambda: _EMA(9))
    five_ema21: _EMA = field(default_factory=lambda: _EMA(21))
    five_bucket: tuple[str, int] | None = None
    five_bucket_close: float | None = None
    five_last_rsi: float | None = None
    five_last_ema9: float | None = None
    five_last_ema21: float | None = None

    def update(
        self, *, timestamp: datetime, open_: float, high: float, low: float, close: float,
        futures_open: float | None, futures_close: float | None,
        futures_vwap: float | None, futures_volume: float | None,
    ) -> dict:
        self.bars += 1
        e5, e9 = self.ema5.update(close), self.ema9.update(close)
        e13, e21 = self.ema13.update(close), self.ema21.update(close)
        e34, e50 = self.ema34.update(close), self.ema50.update(close)
        macd = self.macd12.update(close) - self.macd26.update(close)
        signal = self.macd_signal.update(macd)
        hist = macd - signal
        rsi8, rsi14 = self.rsi8.update(close), self.rsi14.update(close)

        if self.previous_close is None:
            tr, plus_move, minus_move = high - low, 0.0, 0.0
        else:
            tr = max(high - low, abs(high - self.previous_close), abs(low - self.previous_close))
            up = high - float(self.previous_high)
            down = float(self.previous_low) - low
            plus_move = up if up > down and up > 0 else 0.0
            minus_move = down if down > up and down > 0 else 0.0
        smoothed_tr = self.tr14.update(tr)
        smoothed_plus = self.plus14.update(plus_move)
        smoothed_minus = self.minus14.update(minus_move)
        plus_di = 100.0 * smoothed_plus / smoothed_tr if smoothed_tr and smoothed_plus is not None else None
        minus_di = 100.0 * smoothed_minus / smoothed_tr if smoothed_tr and smoothed_minus is not None else None
        dx = (
            100.0 * abs(plus_di - minus_di) / (plus_di + minus_di)
            if plus_di is not None and minus_di is not None and plus_di + minus_di else None
        )
        adx = self.adx14.update(dx) if dx is not None else None

        volume_ratio = None
        if futures_volume is not None:
            baseline = statistics.mean(self.volume20) if len(self.volume20) == 20 else None
            volume_ratio = futures_volume / baseline if baseline and baseline > 0 else None
            if futures_volume >= 0:
                self.volume20.append(futures_volume)

        five_key = (
            timestamp.date().isoformat(),
            timestamp.hour * 12 + timestamp.minute // 5,
        )
        if (
            self.five_bucket is not None
            and five_key != self.five_bucket
            and self.five_bucket_close is not None
        ):
            self.five_last_rsi = self.five_rsi14.update(self.five_bucket_close)
            self.five_last_ema9 = self.five_ema9.update(self.five_bucket_close)
            self.five_last_ema21 = self.five_ema21.update(self.five_bucket_close)
        self.five_bucket, self.five_bucket_close = five_key, close

        raw = {
            "open": open_, "high": high, "low": low, "close": close,
            "ema5": e5, "ema9": e9, "ema13": e13, "ema21": e21,
            "ema34": e34, "ema50": e50, "rsi8": rsi8, "rsi14": rsi14,
            "macd": macd, "macd_signal": signal, "macd_hist": hist,
            "macd_hist_change": None if self.previous_hist is None else hist - self.previous_hist,
            "plus_di": plus_di, "minus_di": minus_di, "adx": adx,
            "futures_open": futures_open, "futures_close": futures_close,
            "futures_vwap": futures_vwap, "futures_volume_ratio20": volume_ratio,
            "rsi5m_closed": self.five_last_rsi,
            "ema9_5m_closed": self.five_last_ema9,
            "ema21_5m_closed": self.five_last_ema21,
            "warmup_bars": self.bars,
        }
        self.previous_close, self.previous_high, self.previous_low = close, high, low
        self.previous_hist = hist
        return raw

    @staticmethod
    def directional_snapshot(raw: dict, direction: str) -> dict:
        bullish = direction == "BULLISH"
        close = raw["close"]
        plus_di, minus_di, adx = raw["plus_di"], raw["minus_di"], raw["adx"]
        f_close, f_open, f_vwap = raw["futures_close"], raw["futures_open"], raw["futures_vwap"]
        volume_ratio = raw["futures_volume_ratio20"]

        def side(bull: bool, bear: bool) -> bool:
            return bull if bullish else bear

        momentum = side(
            close > raw["ema5"] and close > raw["ema13"],
            close < raw["ema5"] and close < raw["ema13"],
        )
        di_spread = None if plus_di is None or minus_di is None else (
            plus_di - minus_di if bullish else minus_di - plus_di
        )

        def precision(for_bull: bool) -> float | None:
            rsi8, hist, hist_change = raw["rsi8"], raw["macd_hist"], raw["macd_hist_change"]
            terms = [
                (close > raw["ema34"] if for_bull else close < raw["ema34"], 1.0),
                (None if rsi8 is None else (50 < rsi8 < 75 if for_bull else 25 < rsi8 < 50), 1.0),
                (hist > 0 if for_bull else hist < 0, 1.0),
                (None if hist_change is None else (hist_change > 0 if for_bull else hist_change < 0), 1.0),
                (None if None in (adx, plus_di, minus_di) else adx >= 20 and (plus_di > minus_di if for_bull else minus_di > plus_di), 1.0),
                (None if volume_ratio is None else volume_ratio > 1.2, 1.0),
                (None if f_close is None or f_vwap is None else (f_close > f_vwap if for_bull else f_close < f_vwap), 1.0),
                (None if None in (raw["ema9_5m_closed"], raw["ema21_5m_closed"]) else (raw["ema9_5m_closed"] > raw["ema21_5m_closed"] if for_bull else raw["ema9_5m_closed"] < raw["ema21_5m_closed"]), 1.5),
            ]
            available = sum(weight for value, weight in terms if value is not None)
            score = sum(weight for value, weight in terms if value)
            return 100.0 * score / available if available else None

        def community(for_bull: bool) -> float | None:
            rsi14 = raw["rsi14"]
            terms = [
                None if f_close is None or f_vwap is None else (f_close > f_vwap if for_bull else f_close < f_vwap),
                None if rsi14 is None else (rsi14 > 50 if for_bull else rsi14 < 50),
                raw["macd"] > raw["macd_signal"] if for_bull else raw["macd"] < raw["macd_signal"],
                raw["ema9"] > raw["ema21"] if for_bull else raw["ema9"] < raw["ema21"],
                None if adx is None else adx > 25 and (close > raw["ema9"] if for_bull else close < raw["ema9"]),
                None if None in (volume_ratio, f_close, f_open) else volume_ratio > 1 and (f_close > f_open if for_bull else f_close < f_open),
                None if raw["rsi5m_closed"] is None else (raw["rsi5m_closed"] > 50 if for_bull else raw["rsi5m_closed"] < 50),
            ]
            present = [value for value in terms if value is not None]
            return 100.0 * sum(bool(value) for value in present) / len(present) if present else None

        pi, po = (precision(True), precision(False)) if bullish else (precision(False), precision(True))
        ci, co = (community(True), community(False)) if bullish else (community(False), community(True))
        combined_edge = None if None in (pi, po, ci, co) else statistics.mean((pi - po, ci - co))
        ready = raw["warmup_bars"] >= 28 and None not in (di_spread, combined_edge)
        return {
            "available": ready,
            "warmup_bars": raw["warmup_bars"],
            "directional_di_spread": di_spread,
            "combined_edge": combined_edge,
            "price_momentum_support": float(momentum),
            "di_failure": None if di_spread is None else di_spread <= 0,
            "combined_edge_failure": None if combined_edge is None else combined_edge <= 0,
            "price_momentum_failure": not momentum,
        }


def evaluate_t5_candidates(snapshot: dict) -> dict:
    """Return the two frozen candidate decisions without changing trade state."""
    if not snapshot.get("available"):
        return {"available": False, "two_of_three": False, "combined_edge": False}
    failures = sum(bool(snapshot[name]) for name in (
        "di_failure", "combined_edge_failure", "price_momentum_failure"
    ))
    return {
        "available": True,
        "failure_count": failures,
        "two_of_three": failures >= 2,
        "combined_edge": bool(snapshot["combined_edge_failure"]),
    }
