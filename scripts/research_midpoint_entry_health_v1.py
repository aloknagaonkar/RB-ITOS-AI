#!/usr/bin/env python3
"""Research-only causal entry-health study for Midpoint B/E and PM B/E.

The study independently reimplements timestamp-causal evidence inspired by two
user-supplied Pine indicators.  It does not import their signal, stop, target,
grade or UI logic.  Canonical Midpoint entries and outcomes remain unchanged.

Universe: 480 frozen sessions plus the latest 10 of 14 forward sessions.
Price indicators use NIFTY; volume and session-VWAP evidence use NIFTY futures.
All snapshots use completed candles.  Five-minute evidence is exposed only
after its complete five-minute bucket is available.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


GOOD_BAD = Path("scripts/research_midpoint_good_bad_features.py")
DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-good-bad-feature-study-490-v1/all-trade-features.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-entry-health-490-v1"
)

SNAPSHOTS = ("midpoint", "preboundary", "boundary", "entry", "t1", "t3", "t5")
METRICS = (
    "precision_intended_pct", "precision_opposite_pct", "precision_edge",
    "community_intended_pct", "community_opposite_pct", "community_edge",
    "combined_edge", "ema_5_13_support", "ema_9_21_support",
    "ema_9_21_50_stack", "price_momentum_support", "rsi8_support",
    "rsi14_support", "rsi14_extreme", "rsi5m_support",
    "macd_direction_support", "macd_acceleration_support", "adx",
    "adx20_di_support", "adx25_price_support", "directional_di_spread",
    "futures_volume_ratio20", "directional_volume_support",
    "futures_vwap_support", "closed_5m_ema_support", "ema9_extension_atr14",
    "atr10_mean42_ratio", "orderly_ema_retest",
)
PRIMARY_FEATURES = tuple(
    f"{snapshot}_{metric}"
    for snapshot in SNAPSHOTS
    for metric in METRICS
) + (
    "entry_precision_edge_change_from_midpoint",
    "entry_community_edge_change_from_midpoint",
    "entry_combined_edge_change_from_midpoint",
    "t3_combined_edge_change_from_entry",
    "t5_combined_edge_change_from_entry",
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finite(value) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def truth(value) -> float | None:
    return None if value is None else float(bool(value))


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class EMA:
    length: int
    value: float | None = None

    def update(self, current: float) -> float:
        alpha = 2.0 / (self.length + 1.0)
        self.value = current if self.value is None else self.value + alpha * (current - self.value)
        return self.value


@dataclass
class WilderAverage:
    length: int
    values: list[float] = field(default_factory=list)
    value: float | None = None

    def update(self, current: float) -> float | None:
        if self.value is None:
            self.values.append(current)
            if len(self.values) == self.length:
                self.value = statistics.mean(self.values)
            return self.value
        self.value = ((self.length - 1) * self.value + current) / self.length
        return self.value


@dataclass
class RSI:
    length: int
    previous: float | None = None
    gains: WilderAverage = field(init=False)
    losses: WilderAverage = field(init=False)

    def __post_init__(self) -> None:
        self.gains = WilderAverage(self.length)
        self.losses = WilderAverage(self.length)

    def update(self, close: float) -> float | None:
        if self.previous is None:
            self.previous = close
            return None
        change = close - self.previous
        self.previous = close
        gain = self.gains.update(max(change, 0.0))
        loss = self.losses.update(max(-change, 0.0))
        if gain is None or loss is None:
            return None
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)


@dataclass
class IndicatorState:
    ema5: EMA = field(default_factory=lambda: EMA(5))
    ema9: EMA = field(default_factory=lambda: EMA(9))
    ema13: EMA = field(default_factory=lambda: EMA(13))
    ema21: EMA = field(default_factory=lambda: EMA(21))
    ema34: EMA = field(default_factory=lambda: EMA(34))
    ema50: EMA = field(default_factory=lambda: EMA(50))
    macd12: EMA = field(default_factory=lambda: EMA(12))
    macd26: EMA = field(default_factory=lambda: EMA(26))
    macd_signal: EMA = field(default_factory=lambda: EMA(9))
    rsi8: RSI = field(default_factory=lambda: RSI(8))
    rsi14: RSI = field(default_factory=lambda: RSI(14))
    atr10: WilderAverage = field(default_factory=lambda: WilderAverage(10))
    atr14: WilderAverage = field(default_factory=lambda: WilderAverage(14))
    plus14: WilderAverage = field(default_factory=lambda: WilderAverage(14))
    minus14: WilderAverage = field(default_factory=lambda: WilderAverage(14))
    tr14: WilderAverage = field(default_factory=lambda: WilderAverage(14))
    adx14: WilderAverage = field(default_factory=lambda: WilderAverage(14))
    atr10_history: deque = field(default_factory=lambda: deque(maxlen=42))
    previous_close: float | None = None
    previous_high: float | None = None
    previous_low: float | None = None
    previous_hist: float | None = None

    def update(self, row: dict) -> dict:
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        e5, e9 = self.ema5.update(close), self.ema9.update(close)
        e13, e21 = self.ema13.update(close), self.ema21.update(close)
        e34, e50 = self.ema34.update(close), self.ema50.update(close)
        fast = self.macd12.update(close)
        slow = self.macd26.update(close)
        macd = fast - slow
        signal = self.macd_signal.update(macd)
        hist = macd - signal
        rsi8, rsi14 = self.rsi8.update(close), self.rsi14.update(close)

        if self.previous_close is None:
            tr = high - low
            plus_move = minus_move = 0.0
        else:
            tr = max(high - low, abs(high - self.previous_close), abs(low - self.previous_close))
            up = high - float(self.previous_high)
            down = float(self.previous_low) - low
            plus_move = up if up > down and up > 0 else 0.0
            minus_move = down if down > up and down > 0 else 0.0
        atr10 = self.atr10.update(tr)
        atr14 = self.atr14.update(tr)
        smoothed_tr = self.tr14.update(tr)
        smoothed_plus = self.plus14.update(plus_move)
        smoothed_minus = self.minus14.update(minus_move)
        plus_di = (
            100.0 * smoothed_plus / smoothed_tr
            if smoothed_tr not in (None, 0) and smoothed_plus is not None else None
        )
        minus_di = (
            100.0 * smoothed_minus / smoothed_tr
            if smoothed_tr not in (None, 0) and smoothed_minus is not None else None
        )
        dx = (
            100.0 * abs(plus_di - minus_di) / (plus_di + minus_di)
            if plus_di is not None and minus_di is not None and plus_di + minus_di else None
        )
        adx = self.adx14.update(dx) if dx is not None else None
        if atr10 is not None:
            self.atr10_history.append(atr10)
        atr_mean42 = (
            statistics.mean(self.atr10_history)
            if len(self.atr10_history) == 42 else None
        )
        output = {
            "ema5": e5, "ema9": e9, "ema13": e13, "ema21": e21,
            "ema34": e34, "ema50": e50, "rsi8": rsi8, "rsi14": rsi14,
            "macd": macd, "macd_signal": signal, "macd_hist": hist,
            "macd_hist_change": (
                hist - self.previous_hist if self.previous_hist is not None else None
            ),
            "atr10": atr10, "atr14": atr14, "atr10_mean42": atr_mean42,
            "plus_di": plus_di, "minus_di": minus_di, "adx": adx,
        }
        self.previous_close, self.previous_high, self.previous_low = close, high, low
        self.previous_hist = hist
        return output


@dataclass
class FiveMinuteState:
    rsi14: RSI = field(default_factory=lambda: RSI(14))
    ema9: EMA = field(default_factory=lambda: EMA(9))
    ema21: EMA = field(default_factory=lambda: EMA(21))
    bucket: tuple[str, int] | None = None
    bucket_close: float | None = None
    last_rsi: float | None = None
    last_ema9: float | None = None
    last_ema21: float | None = None

    def update(self, timestamp: str, close: float) -> dict:
        moment = iso(timestamp)
        key = (moment.date().isoformat(), moment.hour * 12 + moment.minute // 5)
        if self.bucket is not None and key != self.bucket and self.bucket_close is not None:
            self.last_rsi = self.rsi14.update(self.bucket_close)
            self.last_ema9 = self.ema9.update(self.bucket_close)
            self.last_ema21 = self.ema21.update(self.bucket_close)
        self.bucket = key
        self.bucket_close = close
        return {
            "rsi5m_closed": self.last_rsi,
            "ema9_5m_closed": self.last_ema9,
            "ema21_5m_closed": self.last_ema21,
        }


def rolling_volume_ratio(history: deque, volume: float) -> float | None:
    baseline = statistics.mean(history) if len(history) == history.maxlen else None
    return volume / baseline if baseline and baseline > 0 else None


def build_indicator_series(sessions: dict[str, dict]) -> dict[str, dict[str, dict]]:
    """Calculate sequential evidence; only current/past rows affect each result."""
    state = IndicatorState()
    five = FiveMinuteState()
    volume_history: deque = deque(maxlen=20)
    output: dict[str, dict[str, dict]] = {}
    for day in sorted(sessions):
        day_output: dict[str, dict] = {}
        underlying = sessions[day]["underlying"]
        futures = sessions[day]["futures"]
        for timestamp, spot in sorted(underlying.items(), key=lambda item: iso(item[0])):
            future = futures.get(timestamp)
            raw = state.update(spot)
            raw.update(five.update(timestamp, float(spot["close"])))
            if future is not None:
                volume = float(future.get("volume", 0.0) or 0.0)
                raw["futures_volume_ratio20"] = rolling_volume_ratio(volume_history, volume)
                raw["futures_open"] = float(future.get("open", future["close"]))
                raw["futures_close"] = float(future["close"])
                raw["futures_vwap"] = finite(future.get("vwap"))
                if volume >= 0:
                    volume_history.append(volume)
            else:
                raw.update({
                    "futures_volume_ratio20": None, "futures_open": None,
                    "futures_close": None, "futures_vwap": None,
                })
            raw.update({
                "open": float(spot.get("open", spot["close"])),
                "high": float(spot["high"]), "low": float(spot["low"]),
                "close": float(spot["close"]),
            })
            day_output[timestamp] = raw
        output[day] = day_output
    return output


def directional_health(raw: dict | None, direction: str) -> dict:
    if raw is None:
        return {metric: None for metric in METRICS}
    bullish = direction == "BULLISH"
    close = raw["close"]
    rsi8, rsi14 = raw.get("rsi8"), raw.get("rsi14")
    hist, hist_change = raw.get("macd_hist"), raw.get("macd_hist_change")
    macd, signal = raw.get("macd"), raw.get("macd_signal")
    adx, plus_di, minus_di = raw.get("adx"), raw.get("plus_di"), raw.get("minus_di")
    future_close, future_open = raw.get("futures_close"), raw.get("futures_open")
    futures_vwap = raw.get("futures_vwap")
    volume_ratio = raw.get("futures_volume_ratio20")
    rsi5 = raw.get("rsi5m_closed")

    def above(left, right) -> bool | None:
        return None if left is None or right is None else left > right

    def side(condition_bull: bool | None, condition_bear: bool | None) -> bool | None:
        return condition_bull if bullish else condition_bear

    ema_5_13 = side(above(raw["ema5"], raw["ema13"]), above(raw["ema13"], raw["ema5"]))
    ema_9_21 = side(above(raw["ema9"], raw["ema21"]), above(raw["ema21"], raw["ema9"]))
    full_stack = side(
        raw["ema9"] > raw["ema21"] > raw["ema50"],
        raw["ema9"] < raw["ema21"] < raw["ema50"],
    )
    momentum = side(close > raw["ema5"] and close > raw["ema13"], close < raw["ema5"] and close < raw["ema13"])
    rsi8_support = None if rsi8 is None else (50 < rsi8 < 75 if bullish else 25 < rsi8 < 50)
    rsi14_support = None if rsi14 is None else (rsi14 > 50 if bullish else rsi14 < 50)
    rsi14_extreme = None if rsi14 is None else (rsi14 >= 75 if bullish else rsi14 <= 25)
    rsi5_support = None if rsi5 is None else (rsi5 > 50 if bullish else rsi5 < 50)
    macd_direction = side(hist is not None and hist > 0, hist is not None and hist < 0)
    macd_acceleration = side(hist_change is not None and hist_change > 0, hist_change is not None and hist_change < 0)
    adx20_di = None if None in (adx, plus_di, minus_di) else adx >= 20 and (plus_di > minus_di if bullish else minus_di > plus_di)
    adx25_price = None if adx is None else adx > 25 and (close > raw["ema9"] if bullish else close < raw["ema9"])
    di_spread = None if plus_di is None or minus_di is None else (plus_di - minus_di if bullish else minus_di - plus_di)
    directional_volume = None if None in (volume_ratio, future_close, future_open) else volume_ratio > 1 and (future_close > future_open if bullish else future_close < future_open)
    vwap_support = None if future_close is None or futures_vwap is None else (future_close > futures_vwap if bullish else future_close < futures_vwap)
    htf_support = None if None in (raw.get("ema9_5m_closed"), raw.get("ema21_5m_closed")) else (raw["ema9_5m_closed"] > raw["ema21_5m_closed"] if bullish else raw["ema9_5m_closed"] < raw["ema21_5m_closed"])
    orderly_retest = (
        raw["low"] <= raw["ema9"] and raw["low"] > raw["ema21"]
        if bullish else raw["high"] >= raw["ema9"] and raw["high"] < raw["ema21"]
    )
    extension = abs(close - raw["ema9"]) / raw["atr14"] if raw.get("atr14") else None
    atr_ratio = raw["atr10"] / raw["atr10_mean42"] if raw.get("atr10_mean42") else None

    # Precision model: optional evidence normalized only over available terms.
    def precision_score(for_bull: bool) -> tuple[float | None, float]:
        terms = [
            (close > raw["ema34"] if for_bull else close < raw["ema34"], 1.0),
            (None if rsi8 is None else (50 < rsi8 < 75 if for_bull else 25 < rsi8 < 50), 1.0),
            (None if hist is None else (hist > 0 if for_bull else hist < 0), 1.0),
            (None if hist_change is None else (hist_change > 0 if for_bull else hist_change < 0), 1.0),
            (None if None in (adx, plus_di, minus_di) else adx >= 20 and (plus_di > minus_di if for_bull else minus_di > plus_di), 1.0),
            (None if volume_ratio is None else volume_ratio > 1.2, 1.0),
            (None if future_close is None or futures_vwap is None else (future_close > futures_vwap if for_bull else future_close < futures_vwap), 1.0),
            (None if None in (raw.get("ema9_5m_closed"), raw.get("ema21_5m_closed")) else (raw["ema9_5m_closed"] > raw["ema21_5m_closed"] if for_bull else raw["ema9_5m_closed"] < raw["ema21_5m_closed"]), 1.5),
        ]
        available = sum(weight for value, weight in terms if value is not None)
        score = sum(weight for value, weight in terms if value)
        return (100.0 * score / available if available else None), available

    def community_score(for_bull: bool) -> float | None:
        terms = [
            None if future_close is None or futures_vwap is None else (future_close > futures_vwap if for_bull else future_close < futures_vwap),
            None if rsi14 is None else (rsi14 > 50 if for_bull else rsi14 < 50),
            None if macd is None or signal is None else (macd > signal if for_bull else macd < signal),
            raw["ema9"] > raw["ema21"] if for_bull else raw["ema9"] < raw["ema21"],
            None if adx is None else adx > 25 and (close > raw["ema9"] if for_bull else close < raw["ema9"]),
            None if None in (volume_ratio, future_close, future_open) else volume_ratio > 1 and (future_close > future_open if for_bull else future_close < future_open),
            None if rsi5 is None else (rsi5 > 50 if for_bull else rsi5 < 50),
        ]
        present = [value for value in terms if value is not None]
        return 100.0 * sum(bool(value) for value in present) / len(present) if present else None

    precision_bull, _ = precision_score(True)
    precision_bear, _ = precision_score(False)
    community_bull, community_bear = community_score(True), community_score(False)
    precision_intended = precision_bull if bullish else precision_bear
    precision_opposite = precision_bear if bullish else precision_bull
    community_intended = community_bull if bullish else community_bear
    community_opposite = community_bear if bullish else community_bull
    precision_edge = None if None in (precision_intended, precision_opposite) else precision_intended - precision_opposite
    community_edge = None if None in (community_intended, community_opposite) else community_intended - community_opposite
    combined_edge = statistics.mean([precision_edge, community_edge]) if None not in (precision_edge, community_edge) else None
    return {
        "precision_intended_pct": precision_intended,
        "precision_opposite_pct": precision_opposite,
        "precision_edge": precision_edge,
        "community_intended_pct": community_intended,
        "community_opposite_pct": community_opposite,
        "community_edge": community_edge,
        "combined_edge": combined_edge,
        "ema_5_13_support": truth(ema_5_13),
        "ema_9_21_support": truth(ema_9_21),
        "ema_9_21_50_stack": truth(full_stack),
        "price_momentum_support": truth(momentum),
        "rsi8_support": truth(rsi8_support),
        "rsi14_support": truth(rsi14_support),
        "rsi14_extreme": truth(rsi14_extreme),
        "rsi5m_support": truth(rsi5_support),
        "macd_direction_support": truth(macd_direction),
        "macd_acceleration_support": truth(macd_acceleration),
        "adx": adx,
        "adx20_di_support": truth(adx20_di),
        "adx25_price_support": truth(adx25_price),
        "directional_di_spread": di_spread,
        "futures_volume_ratio20": volume_ratio,
        "directional_volume_support": truth(directional_volume),
        "futures_vwap_support": truth(vwap_support),
        "closed_5m_ema_support": truth(htf_support),
        "ema9_extension_atr14": extension,
        "atr10_mean42_ratio": atr_ratio,
        "orderly_ema_retest": truth(orderly_retest),
    }


def flatten_snapshot(prefix: str, raw: dict | None, direction: str) -> dict:
    health = directional_health(raw, direction)
    return {f"{prefix}_{key}": value for key, value in health.items()}


def event_before(rows: list[dict], entry_at: datetime, event_types: set[str], direction: str) -> dict | None:
    matches = [
        row for row in rows
        if row.get("event_type") in event_types
        and row.get("direction") == direction
        and iso(row["event_timestamp"]) <= entry_at
    ]
    return max(matches, key=lambda row: iso(row["event_timestamp"])) if matches else None


def trade_health_row(
    trade: dict, segment: str, audit: list[dict], indicators: dict[str, dict], split: str,
) -> dict:
    day = str(trade["session_date"])
    entry_at = iso(str(trade["entry_timestamp"]))
    direction = str(trade["direction"])
    if segment == "PM":
        midpoint_text = str(trade.get("midpoint_timestamp") or "")
        boundary_text = str(trade.get("boundary_timestamp") or "")
    else:
        boundary_event = event_before(audit, entry_at, {"BOUNDARY_CLASSIFIED"}, direction)
        boundary_text = boundary_event["event_timestamp"] if boundary_event else ""
        boundary_at = iso(boundary_text) if boundary_text else entry_at
        midpoint_event = event_before(audit, boundary_at, {"MIDPOINT_BREAK"}, direction)
        midpoint_text = midpoint_event["event_timestamp"] if midpoint_event else ""
    boundary_at = iso(boundary_text) if boundary_text else entry_at
    moments = {
        "midpoint": iso(midpoint_text) if midpoint_text else None,
        "preboundary": boundary_at - timedelta(minutes=1),
        "boundary": boundary_at,
        "entry": entry_at,
        "t1": entry_at + timedelta(minutes=1),
        "t3": entry_at + timedelta(minutes=3),
        "t5": entry_at + timedelta(minutes=5),
    }
    exit_at = iso(trade["selected_exit_timestamp"]) if trade.get("selected_exit_timestamp") else None
    output = {
        "split": split, "segment": segment, "session_date": day,
        "family": trade["family"], "direction": direction,
        "cohort": "GOOD_PLUS20_PROVED" if bool(trade.get("plus20")) else (
            "BAD_UNPROVED_STRUCTURAL_LOSS"
            if trade.get("selected_exit_policy") == "STRUCTURAL_BASELINE"
            and finite(trade.get("selected_exit_points")) is not None
            and float(trade["selected_exit_points"]) < 0 else "UNRESOLVED_OR_OTHER"
        ),
        "entry_timestamp": trade["entry_timestamp"],
        "midpoint_timestamp": midpoint_text, "boundary_timestamp": boundary_text,
        "selected_exit_policy": trade.get("selected_exit_policy"),
        "selected_exit_timestamp": trade.get("selected_exit_timestamp"),
        "selected_exit_points": finite(trade.get("selected_exit_points")),
    }
    for name, moment in moments.items():
        allowed = moment is not None and (name not in {"t1", "t3", "t5"} or exit_at is None or moment <= exit_at)
        raw = indicators.get(day, {}).get(moment.isoformat()) if allowed else None
        output[f"{name}_timestamp"] = moment.isoformat() if moment else ""
        output[f"{name}_available"] = raw is not None
        output.update(flatten_snapshot(name, raw, direction))
    for model in ("precision", "community", "combined"):
        entry = finite(output.get(f"entry_{model}_edge"))
        midpoint = finite(output.get(f"midpoint_{model}_edge"))
        output[f"entry_{model}_edge_change_from_midpoint"] = (
            entry - midpoint if entry is not None and midpoint is not None else None
        )
    for checkpoint in ("t3", "t5"):
        current = finite(output.get(f"{checkpoint}_combined_edge"))
        entry = finite(output.get("entry_combined_edge"))
        output[f"{checkpoint}_combined_edge_change_from_entry"] = (
            current - entry if current is not None and entry is not None else None
        )
    return output


def cliffs_delta(good: list[float], bad: list[float]) -> float | None:
    if not good or not bad:
        return None
    greater = sum(left > right for left in good for right in bad)
    lower = sum(left < right for left in good for right in bad)
    return (greater - lower) / (len(good) * len(bad))


def statistics_rows(rows: list[dict], split: str) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["split"] == split:
            groups[(row["segment"], row["family"], row["direction"])].append(row)
    output = []
    for (segment, family, direction), members in sorted(groups.items()):
        for feature in PRIMARY_FEATURES:
            good = [float(row[feature]) for row in members if row["cohort"] == "GOOD_PLUS20_PROVED" and finite(row.get(feature)) is not None]
            bad = [float(row[feature]) for row in members if row["cohort"] == "BAD_UNPROVED_STRUCTURAL_LOSS" and finite(row.get(feature)) is not None]
            if not good or not bad:
                continue
            delta = cliffs_delta(good, bad)
            output.append({
                "split": split, "segment": segment, "family": family,
                "direction": direction, "feature": feature,
                "good_n": len(good), "bad_n": len(bad),
                "good_mean": statistics.mean(good), "bad_mean": statistics.mean(bad),
                "mean_difference": statistics.mean(good) - statistics.mean(bad),
                "cliffs_delta": delta,
                "single_feature_auc": (delta + 1.0) / 2.0 if delta is not None else None,
                "separation_auc": max((delta + 1.0) / 2.0, 1.0 - (delta + 1.0) / 2.0) if delta is not None else None,
            })
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    base = load_module(GOOD_BAD, "good_bad_for_entry_health_v1")
    current = load_module(base.CURRENT, "current_for_entry_health_v1")
    pm = load_module(base.PM, "pm_for_entry_health_v1")
    v55 = current.import_module(current.V55, "v55_for_entry_health_v1")
    v52 = current.import_module(current.V52, "v52_for_entry_health_v1")
    canon = current.import_module(current.CANON, "canon_for_entry_health_v1")
    forward_root = arguments.forward_root or base.DEFAULT_FORWARD_ROOT

    sessions: dict[str, dict] = {}
    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for day in sorted(set(underlying).intersection(futures)):
            sessions[day] = {"block": block["name"], "underlying": underlying[day], "futures": futures[day]}
    frozen_dates = sorted(sessions)
    if len(frozen_dates) != 480:
        raise SystemExit(f"STOP: expected 480 frozen sessions, found {len(frozen_dates)}")
    forward = pm.load_forward_sessions(forward_root)
    if len(forward) != 14:
        raise SystemExit(f"STOP: expected 14 forward sessions, found {len(forward)}")
    for day, (underlying, futures) in forward.items():
        sessions[day] = {"block": "FORWARD_OOS_2026-09", "underlying": underlying, "futures": futures}
    selected_forward = sorted(forward)[-10:]
    analysis_dates = frozen_dates + selected_forward
    is_dates, oos_dates = set(frozen_dates[:336]), set(frozen_dates[336:])
    indicator_series = build_indicator_series(sessions)
    rows: list[dict] = []
    for count, day in enumerate(analysis_dates, start=1):
        market = sessions[day]
        split = "IS_FROZEN_FIRST_70" if day in is_dates else "OOS_FROZEN_LAST_30" if day in oos_dates else "FORWARD_LATEST_10"
        morning_audit = current.replay_session(day, market["underlying"], market["futures"])
        morning_trades = current.reconstruct_session(block=market["block"], session_date=day, rows=morning_audit, underlying=market["underlying"])
        for trade in morning_trades:
            if trade["family"] in {"B", "E"}:
                rows.append(trade_health_row(trade, "MORNING", morning_audit, indicator_series, split))
        pm_audit = pm.replay_session(day, market["underlying"], market["futures"])
        pm_trades = pm.reconstruct_pm_trades(block=market["block"], session_date=day, rows=pm_audit, underlying=market["underlying"])
        for trade in pm_trades:
            rows.append(trade_health_row(trade, "PM", pm_audit, indicator_series, split))
        if count % 50 == 0:
            print(f"Processed {count}/490 sessions", flush=True)

    stats = []
    for split in ("IS_FROZEN_FIRST_70", "OOS_FROZEN_LAST_30", "FORWARD_LATEST_10"):
        stats.extend(statistics_rows(rows, split))
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "trade-health-features.csv", rows)
    write_csv(arguments.output_dir / "feature-statistics.csv", stats)
    for segment in ("MORNING", "PM"):
        write_csv(arguments.output_dir / f"{segment.lower()}-trade-health.csv", [row for row in rows if row["segment"] == segment])
    is_ranked = sorted(
        [row for row in stats if row["split"] == "IS_FROZEN_FIRST_70" and row["good_n"] >= 10 and row["bad_n"] >= 10],
        key=lambda row: row["separation_auc"], reverse=True,
    )
    write_csv(arguments.output_dir / "is-ranked-features.csv", is_ranked)
    cohorts: dict[str, int] = defaultdict(int)
    for row in rows:
        cohorts[row["cohort"]] += 1
    report = {
        "model": "MIDPOINT_ENTRY_HEALTH_V1",
        "sessions": {"analysis": 490, "frozen": 480, "is": 336, "oos": 144, "forward": 10, "selected_forward": selected_forward},
        "trades": len(rows), "cohorts": dict(sorted(cohorts.items())),
        "rules_used": [
            "EMA 5/13/34 and EMA 9/21/50 directional structure",
            "RSI 8 non-extreme, RSI 14 direction, last completed 5-minute RSI 14",
            "MACD histogram direction and acceleration",
            "ADX 20/25, directional DI spread",
            "NIFTY-futures volume ratio and directional-volume confirmation",
            "NIFTY-futures price versus canonical session VWAP",
            "last completed 5-minute EMA direction",
            "ATR regime, EMA extension, orderly EMA9/EMA21 retest",
            "intended score, opposite score, directional edge and edge decay",
        ],
        "rules_not_used": [
            "indicator EMA-crossover entry", "indicator BUY/SELL labels",
            "indicator stops or targets", "hard 40-percent bias threshold",
            "unvalidated A+/A/B/C or raw score entry filters",
        ],
        "interpretation": [
            "Outcomes label research cohorts; no outcome is used in feature calculation.",
            "Five-minute features use only a previously completed five-minute bucket.",
            "IS ranks features; do not select a rule from OOS or forward results.",
            "This run creates no threshold, entry veto, exit, live event or order.",
        ],
        "safety": {"research_only": True, "observation_only": True, "execution_enabled": False, "paper_order_enabled": False, "quantity": None, "order_sent": False, "live_modified": False},
    }
    (arguments.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Sessions: 490 (480 frozen + latest 10 forward)")
    print("Trade health rows:", len(rows), "cohorts:", dict(cohorts))
    print("Output:", arguments.output_dir / "report.json")
    print("Research only: no live gate, service, audit, entry, exit, order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
