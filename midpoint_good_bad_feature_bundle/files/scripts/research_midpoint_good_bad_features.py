#!/usr/bin/env python3
"""Causal good-vs-bad feature study for Morning and PM Midpoint B/E.

Analysis universe (fixed before outcomes are inspected):
* all 480 frozen historical sessions;
* the 10 most recent sessions from the 14-session forward manifest.

The four earlier forward sessions are context-only so ATR/previous-session
features for the selected forward dates use the real immediately prior market
history.  Their trades never enter cohort statistics.

GOOD means +20 proof was observed. BAD means no +20 proof and a completed,
negative STRUCTURAL_BASELINE exit. Other and unresolved trades remain in the
feature matrix but are excluded from the primary GOOD/BAD statistics.

No live files, gates, services, audits, orders, paper orders or quantities are
read or modified.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


CURRENT = Path("scripts/backtest_midpoint_current_strategy.py")
PM = Path("scripts/backtest_midpoint_pm_be.py")
DEFAULT_FORWARD_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-forward-oos-2026-09-09-to-29-v2"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-good-bad-feature-study-490-v1"
)
CHECKPOINTS = (1, 3, 5, 10, 12)
PRIMARY_FEATURES = (
    "boundary_clearance_points",
    "boundary_clearance_reference_ratio",
    "entry_candle_directional_body",
    "entry_candle_body_efficiency",
    "reference_width_points",
    "reference_width_atr10_ratio",
    "opening_range_directional_clearance",
    "opening_range_width",
    "entry_directional_futures_vwap",
    "entry_futures_volume_ratio_5",
    "entry_futures_volume_ratio_10",
    "entry_minutes_since_0915",
    "midpoint_to_boundary_minutes",
    "confirmation_delay_minutes",
    "nearest_adverse_htf_level_points",
    "adverse_htf_levels_within_20",
    "adverse_htf_levels_within_40",
    "t1_close_progress",
    "t1_mfe",
    "t1_mae",
    "t1_directional_vwap_change",
    "t3_close_progress",
    "t3_mfe",
    "t3_mae",
    "t3_directional_vwap_change",
    "t3_futures_vwap_directional_move",
    "t5_close_progress",
    "t5_mfe",
    "t5_mae",
    "t5_directional_vwap_change",
    "t5_futures_vwap_directional_move",
    "t10_close_progress",
    "t10_mfe",
    "t10_mae",
    "t12_close_progress",
    "t12_mfe",
    "t12_mae",
    "time_to_plus10_minutes",
    "first_boundary_reclaim_minutes",
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parsed(value: str) -> datetime:
    return datetime.fromisoformat(value)


def finite(value) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def directional(direction: str, entry: float, current: float) -> float:
    return current - entry if direction == "BULLISH" else entry - current


def directional_vwap(direction: str, row: dict | None) -> float | None:
    if row is None:
        return None
    close = finite(row.get("close"))
    vwap = finite(row.get("vwap"))
    if close is None or vwap is None:
        return None
    return close - vwap if direction == "BULLISH" else vwap - close


def mean_or_none(values) -> float | None:
    items = [float(value) for value in values if value is not None]
    return statistics.mean(items) if items else None


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def daily_bar(rows: dict[str, dict]) -> dict:
    ordered = sorted(rows.items(), key=lambda item: parsed(item[0]))
    return {
        "open": float(ordered[0][1].get("open", ordered[0][1]["close"])),
        "high": max(float(row["high"]) for _, row in ordered),
        "low": min(float(row["low"]) for _, row in ordered),
        "close": float(ordered[-1][1]["close"]),
    }


def build_daily_context(sessions: dict[str, dict]) -> dict[str, dict]:
    dates = sorted(sessions)
    bars = {day: daily_bar(sessions[day]["underlying"]) for day in dates}
    output: dict[str, dict] = {}
    for index, day in enumerate(dates):
        prior = dates[:index]
        previous_day = bars[prior[-1]] if prior else None
        true_ranges = []
        for position in range(1, index):
            current = bars[dates[position]]
            prior_close = bars[dates[position - 1]]["close"]
            true_ranges.append(max(
                current["high"] - current["low"],
                abs(current["high"] - prior_close),
                abs(current["low"] - prior_close),
            ))
        atr10 = (
            statistics.mean(true_ranges[-10:])
            if len(true_ranges) >= 10 else None
        )
        current_week = date.fromisoformat(day).isocalendar()[:2]
        prior_week_keys = sorted({
            date.fromisoformat(item).isocalendar()[:2]
            for item in prior
            if date.fromisoformat(item).isocalendar()[:2] < current_week
        })
        prior_week = None
        if prior_week_keys:
            key = prior_week_keys[-1]
            week_days = [
                item for item in prior
                if date.fromisoformat(item).isocalendar()[:2] == key
            ]
            prior_week = {
                "high": max(bars[item]["high"] for item in week_days),
                "low": min(bars[item]["low"] for item in week_days),
                "close": bars[week_days[-1]]["close"],
            }
        output[day] = {
            "atr10_prior_sessions": atr10,
            "previous_day": previous_day,
            "previous_week": prior_week,
        }
    return output


def market_at(rows: dict[str, dict], moment: datetime) -> dict | None:
    return rows.get(moment.isoformat())


def window_rows(
    rows: dict[str, dict], start: datetime, end: datetime
) -> list[dict]:
    return [
        row for timestamp, row in sorted(rows.items(), key=lambda item: parsed(item[0]))
        if start < parsed(timestamp) <= end
    ]


def volume_ratio(
    futures: dict[str, dict], entry_at: datetime, periods: int
) -> float | None:
    prior = [
        float(row.get("volume", 0.0) or 0.0)
        for timestamp, row in sorted(futures.items(), key=lambda item: parsed(item[0]))
        if parsed(timestamp) < entry_at
    ][-periods:]
    current = market_at(futures, entry_at)
    current_volume = finite((current or {}).get("volume"))
    baseline = mean_or_none(prior)
    return safe_ratio(current_volume, baseline)


def first_threshold_minutes(
    underlying: dict[str, dict], entry_at: datetime, exit_at: datetime | None,
    entry_price: float, direction: str, threshold: float,
) -> float | None:
    for timestamp, row in sorted(underlying.items(), key=lambda item: parsed(item[0])):
        moment = parsed(timestamp)
        if moment <= entry_at or (exit_at is not None and moment > exit_at):
            continue
        favourable = (
            float(row["high"]) - entry_price if direction == "BULLISH"
            else entry_price - float(row["low"])
        )
        if favourable >= threshold:
            return (moment - entry_at).total_seconds() / 60.0
    return None


def first_reclaim_minutes(
    underlying: dict[str, dict], entry_at: datetime, exit_at: datetime | None,
    boundary: float, direction: str,
) -> float | None:
    for timestamp, row in sorted(underlying.items(), key=lambda item: parsed(item[0])):
        moment = parsed(timestamp)
        if moment <= entry_at or (exit_at is not None and moment > exit_at):
            continue
        close = float(row["close"])
        reclaimed = close <= boundary if direction == "BULLISH" else close >= boundary
        if reclaimed:
            return (moment - entry_at).total_seconds() / 60.0
    return None


def htf_air_pocket(
    direction: str, entry_price: float, context: dict
) -> tuple[float | None, int, int]:
    levels = []
    for period in (context.get("previous_day"), context.get("previous_week")):
        if period:
            levels.extend(float(period[key]) for key in ("high", "low", "close"))
    if direction == "BULLISH":
        distances = [level - entry_price for level in levels if level > entry_price]
    else:
        distances = [entry_price - level for level in levels if level < entry_price]
    return (
        min(distances) if distances else None,
        sum(distance <= 20 for distance in distances),
        sum(distance <= 40 for distance in distances),
    )


def label_trade(trade: dict) -> str:
    if bool(trade.get("plus20")):
        return "GOOD_PLUS20_PROVED"
    points = finite(trade.get("selected_exit_points"))
    if (
        trade.get("selected_exit_policy") == "STRUCTURAL_BASELINE"
        and points is not None and points < 0
    ):
        return "BAD_UNPROVED_STRUCTURAL_LOSS"
    if points is None:
        return "UNRESOLVED"
    return "OTHER"


def feature_row(
    *, trade: dict, segment: str, underlying: dict[str, dict],
    futures: dict[str, dict], context: dict, split: str,
) -> dict:
    entry_at = parsed(str(trade["entry_timestamp"]))
    exit_at = (
        parsed(str(trade["selected_exit_timestamp"]))
        if trade.get("selected_exit_timestamp") else None
    )
    entry_price = float(trade["entry_price"])
    direction = str(trade["direction"])
    high = finite(trade.get("reference_high"))
    low = finite(trade.get("reference_low"))
    midpoint = finite(trade.get("midpoint", trade.get("reference_midpoint")))
    boundary = finite(trade.get("original_boundary"))
    if boundary is None and high is not None and low is not None:
        boundary = high if direction == "BULLISH" else low
    width = high - low if high is not None and low is not None else None
    clearance = (
        directional(direction, boundary, entry_price)
        if boundary is not None else None
    )
    entry_future = market_at(futures, entry_at)
    entry_spot = market_at(underlying, entry_at)
    entry_dvwap = directional_vwap(direction, entry_future)
    entry_body = (
        directional(
            direction, float(entry_spot.get("open", entry_spot["close"])),
            float(entry_spot["close"]),
        ) if entry_spot else None
    )
    entry_range = (
        float(entry_spot["high"]) - float(entry_spot["low"])
        if entry_spot else None
    )
    opening_rows = [
        row for timestamp, row in underlying.items()
        if "09:15" <= parsed(timestamp).strftime("%H:%M") <= "09:30"
    ]
    opening_high = max(float(row["high"]) for row in opening_rows)
    opening_low = min(float(row["low"]) for row in opening_rows)
    opening_width = opening_high - opening_low
    opening_clearance = (
        entry_price - opening_high if direction == "BULLISH"
        else opening_low - entry_price
    )
    nearest, levels20, levels40 = htf_air_pocket(direction, entry_price, context)
    output = {
        "split": split,
        "segment": segment,
        "block": trade.get("block"),
        "session_date": trade["session_date"],
        "family": trade["family"],
        "direction": direction,
        "cohort": label_trade(trade),
        "entry_timestamp": trade["entry_timestamp"],
        "entry_price": entry_price,
        "selected_exit_policy": trade.get("selected_exit_policy"),
        "selected_exit_timestamp": trade.get("selected_exit_timestamp"),
        "selected_exit_points": finite(trade.get("selected_exit_points")),
        "plus20_timestamp": trade.get("plus20_timestamp"),
        "reference_high": high,
        "reference_low": low,
        "reference_midpoint": midpoint,
        "boundary": boundary,
        "reference_width_points": width,
        "boundary_clearance_points": clearance,
        "boundary_clearance_reference_ratio": safe_ratio(clearance, width),
        "entry_candle_directional_body": entry_body,
        "entry_candle_body_efficiency": safe_ratio(entry_body, entry_range),
        "atr10_prior_sessions": context.get("atr10_prior_sessions"),
        "reference_width_atr10_ratio": safe_ratio(
            width, context.get("atr10_prior_sessions")
        ),
        "opening_range_high": opening_high,
        "opening_range_low": opening_low,
        "opening_range_width": opening_width,
        "opening_range_directional_clearance": opening_clearance,
        "entry_directional_futures_vwap": entry_dvwap,
        "entry_futures_volume_ratio_5": volume_ratio(futures, entry_at, 5),
        "entry_futures_volume_ratio_10": volume_ratio(futures, entry_at, 10),
        "entry_minutes_since_0915": (
            entry_at - parsed(trade["session_date"] + "T09:15:00+05:30")
        ).total_seconds() / 60.0,
        "midpoint_to_boundary_minutes": finite(
            trade.get("midpoint_to_boundary_minutes")
        ),
        "confirmation_delay_minutes": finite(
            trade.get("confirmation_delay_minutes")
        ) or 0.0,
        "nearest_adverse_htf_level_points": nearest,
        "adverse_htf_levels_within_20": levels20,
        "adverse_htf_levels_within_40": levels40,
        "time_to_plus10_minutes": first_threshold_minutes(
            underlying, entry_at, exit_at, entry_price, direction, 10.0
        ),
        "time_to_plus20_minutes": first_threshold_minutes(
            underlying, entry_at, exit_at, entry_price, direction, 20.0
        ),
        "first_boundary_reclaim_minutes": (
            first_reclaim_minutes(
                underlying, entry_at, exit_at, boundary, direction
            ) if boundary is not None else None
        ),
    }
    for minutes in CHECKPOINTS:
        prefix = f"t{minutes}"
        checkpoint = entry_at + timedelta(minutes=minutes)
        alive = exit_at is None or checkpoint <= exit_at
        spot = market_at(underlying, checkpoint) if alive else None
        future = market_at(futures, checkpoint) if alive else None
        observed = window_rows(underlying, entry_at, checkpoint) if spot else []
        output[f"{prefix}_available"] = bool(spot and future)
        output[f"{prefix}_terminal_before"] = bool(exit_at and exit_at < checkpoint)
        output[f"{prefix}_close_progress"] = (
            directional(direction, entry_price, float(spot["close"]))
            if spot else None
        )
        output[f"{prefix}_mfe"] = (
            max(
                float(row["high"]) - entry_price if direction == "BULLISH"
                else entry_price - float(row["low"])
                for row in observed
            ) if observed else None
        )
        output[f"{prefix}_mae"] = (
            min(
                float(row["low"]) - entry_price if direction == "BULLISH"
                else entry_price - float(row["high"])
                for row in observed
            ) if observed else None
        )
        checkpoint_dvwap = directional_vwap(direction, future)
        output[f"{prefix}_directional_futures_vwap"] = checkpoint_dvwap
        output[f"{prefix}_directional_vwap_change"] = (
            checkpoint_dvwap - entry_dvwap
            if checkpoint_dvwap is not None and entry_dvwap is not None else None
        )
        entry_future_vwap = finite((entry_future or {}).get("vwap"))
        checkpoint_future_vwap = finite((future or {}).get("vwap"))
        output[f"{prefix}_futures_vwap_directional_move"] = (
            directional(direction, entry_future_vwap, checkpoint_future_vwap)
            if entry_future_vwap is not None and checkpoint_future_vwap is not None
            else None
        )
        output[f"{prefix}_closed_back_inside_boundary"] = (
            (float(spot["close"]) <= boundary if direction == "BULLISH"
             else float(spot["close"]) >= boundary)
            if spot and boundary is not None else None
        )
    return output


def cohort_values(rows: list[dict], feature: str, cohort: str) -> list[float]:
    return [
        float(row[feature]) for row in rows
        if row["cohort"] == cohort and finite(row.get(feature)) is not None
    ]


def cliffs_delta(good: list[float], bad: list[float]) -> float | None:
    if not good or not bad:
        return None
    greater = sum(left > right for left in good for right in bad)
    lower = sum(left < right for left in good for right in bad)
    return (greater - lower) / (len(good) * len(bad))


def welch_t(good: list[float], bad: list[float]) -> float | None:
    if len(good) < 2 or len(bad) < 2:
        return None
    denominator = math.sqrt(
        statistics.variance(good) / len(good)
        + statistics.variance(bad) / len(bad)
    )
    return (statistics.mean(good) - statistics.mean(bad)) / denominator if denominator else 0.0


def session_bootstrap_ci(
    rows: list[dict], feature: str, *, seed: int = 490, samples: int = 2000
) -> tuple[float | None, float | None]:
    sessions: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sessions[row["session_date"]].append(row)
    keys = sorted(sessions)
    if len(keys) < 2:
        return None, None
    rng = random.Random(seed)
    differences = []
    for _ in range(samples):
        sample = [item for _ in keys for item in sessions[rng.choice(keys)]]
        good = cohort_values(sample, feature, "GOOD_PLUS20_PROVED")
        bad = cohort_values(sample, feature, "BAD_UNPROVED_STRUCTURAL_LOSS")
        if good and bad:
            differences.append(statistics.mean(good) - statistics.mean(bad))
    if len(differences) < 20:
        return None, None
    differences.sort()
    return (
        differences[int(0.025 * (len(differences) - 1))],
        differences[int(0.975 * (len(differences) - 1))],
    )


def feature_statistics(rows: list[dict], split: str) -> list[dict]:
    output = []
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["split"] == split:
            groups[(row["segment"], row["family"], row["direction"])].append(row)
    for key, members in sorted(groups.items()):
        for feature in PRIMARY_FEATURES:
            good = cohort_values(members, feature, "GOOD_PLUS20_PROVED")
            bad = cohort_values(members, feature, "BAD_UNPROVED_STRUCTURAL_LOSS")
            if not good or not bad:
                continue
            delta = cliffs_delta(good, bad)
            low, high = session_bootstrap_ci(members, feature)
            output.append({
                "split": split,
                "segment": key[0],
                "family": key[1],
                "direction": key[2],
                "feature": feature,
                "good_n": len(good),
                "bad_n": len(bad),
                "good_mean": statistics.mean(good),
                "bad_mean": statistics.mean(bad),
                "good_median": statistics.median(good),
                "bad_median": statistics.median(bad),
                "mean_difference": statistics.mean(good) - statistics.mean(bad),
                "welch_t_score": welch_t(good, bad),
                "cliffs_delta": delta,
                "single_feature_auc": (delta + 1.0) / 2.0 if delta is not None else None,
                "separation_auc": max(
                    (delta + 1.0) / 2.0, 1.0 - (delta + 1.0) / 2.0
                ) if delta is not None else None,
                "session_bootstrap_mean_diff_ci_low": low,
                "session_bootstrap_mean_diff_ci_high": high,
            })
    return output


def match_pairs(rows: list[dict]) -> list[dict]:
    features = (
        "entry_minutes_since_0915", "reference_width_points",
        "entry_directional_futures_vwap", "boundary_clearance_reference_ratio",
    )
    output = []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["split"], row["segment"], row["family"], row["direction"])].append(row)
    for key, members in sorted(groups.items()):
        good = [row for row in members if row["cohort"] == "GOOD_PLUS20_PROVED"]
        bad = [row for row in members if row["cohort"] == "BAD_UNPROVED_STRUCTURAL_LOSS"]
        scales = {}
        for feature in features:
            values = [finite(row.get(feature)) for row in members]
            clean = [value for value in values if value is not None]
            scales[feature] = statistics.pstdev(clean) if len(clean) > 1 else 1.0
            if not scales[feature]:
                scales[feature] = 1.0
        for bad_row in bad:
            candidates = []
            for good_row in good:
                distance = 0.0
                used = 0
                for feature in features:
                    left, right = finite(bad_row.get(feature)), finite(good_row.get(feature))
                    if left is not None and right is not None:
                        distance += ((left - right) / scales[feature]) ** 2
                        used += 1
                if used:
                    candidates.append((math.sqrt(distance), good_row))
            if not candidates:
                continue
            distance, good_row = min(candidates, key=lambda item: item[0])
            output.append({
                "split": key[0], "segment": key[1], "family": key[2],
                "direction": key[3], "match_distance": distance,
                "bad_session": bad_row["session_date"],
                "bad_entry": bad_row["entry_timestamp"],
                "bad_exit_points": bad_row["selected_exit_points"],
                "good_session": good_row["session_date"],
                "good_entry": good_row["entry_timestamp"],
                "good_exit_points": good_row["selected_exit_points"],
                **{
                    f"bad_{feature}": bad_row.get(feature) for feature in (
                        *features, "t3_close_progress", "t3_directional_vwap_change",
                        "t5_close_progress", "t5_directional_vwap_change",
                        "time_to_plus10_minutes", "first_boundary_reclaim_minutes",
                    )
                },
                **{
                    f"good_{feature}": good_row.get(feature) for feature in (
                        *features, "t3_close_progress", "t3_directional_vwap_change",
                        "t5_close_progress", "t5_directional_vwap_change",
                        "time_to_plus10_minutes", "first_boundary_reclaim_minutes",
                    )
                },
            })
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward-root", type=Path, default=DEFAULT_FORWARD_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    current = load_module(CURRENT, "current_for_good_bad_490")
    pm = load_module(PM, "pm_for_good_bad_490")
    v55 = current.import_module(current.V55, "v55_for_good_bad_490")
    v52 = current.import_module(current.V52, "v52_for_good_bad_490")
    canon = current.import_module(current.CANON, "canon_for_good_bad_490")

    sessions: dict[str, dict] = {}
    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for day in sorted(set(underlying).intersection(futures)):
            if day in sessions:
                raise SystemExit(f"STOP: duplicate frozen session {day}")
            sessions[day] = {
                "block": block["name"], "source": "FROZEN_480",
                "underlying": underlying[day], "futures": futures[day],
            }
    frozen_dates = sorted(sessions)
    if len(frozen_dates) != 480:
        raise SystemExit(f"STOP: expected 480 frozen sessions, found {len(frozen_dates)}")

    forward = pm.load_forward_sessions(arguments.forward_root)
    forward_dates = sorted(forward)
    if len(forward_dates) != 14:
        raise SystemExit(f"STOP: expected 14 forward sessions, found {len(forward_dates)}")
    for day, (underlying, futures) in forward.items():
        if day in sessions:
            raise SystemExit(f"STOP: forward overlaps frozen session {day}")
        sessions[day] = {
            "block": "FORWARD_OOS_2026-09", "source": "FORWARD_CONTEXT",
            "underlying": underlying, "futures": futures,
        }
    selected_forward = forward_dates[-10:]
    analysis_dates = frozen_dates + selected_forward
    if len(set(analysis_dates)) != 490:
        raise SystemExit("STOP: fixed analysis universe is not exactly 490 sessions")

    is_dates = set(frozen_dates[:336])
    oos_dates = set(frozen_dates[336:])
    forward_set = set(selected_forward)
    daily_context = build_daily_context(sessions)
    all_features = []

    for count, day in enumerate(analysis_dates, start=1):
        market = sessions[day]
        split = (
            "IS_FROZEN_FIRST_70" if day in is_dates
            else "OOS_FROZEN_LAST_30" if day in oos_dates
            else "FORWARD_LATEST_10"
        )
        morning_audit = current.replay_session(
            day, market["underlying"], market["futures"]
        )
        morning_trades = current.reconstruct_session(
            block=market["block"], session_date=day, rows=morning_audit,
            underlying=market["underlying"],
        )
        for trade in morning_trades:
            if trade["family"] not in {"B", "E"}:
                continue
            all_features.append(feature_row(
                trade=trade, segment="MORNING", underlying=market["underlying"],
                futures=market["futures"], context=daily_context[day], split=split,
            ))

        pm_audit = pm.replay_session(day, market["underlying"], market["futures"])
        pm_trades = pm.reconstruct_pm_trades(
            block=market["block"], session_date=day, rows=pm_audit,
            underlying=market["underlying"],
        )
        for trade in pm_trades:
            all_features.append(feature_row(
                trade=trade, segment="PM", underlying=market["underlying"],
                futures=market["futures"], context=daily_context[day], split=split,
            ))
        if count % 50 == 0:
            print(f"Processed {count}/490 sessions", flush=True)

    is_stats = feature_statistics(all_features, "IS_FROZEN_FIRST_70")
    oos_stats = feature_statistics(all_features, "OOS_FROZEN_LAST_30")
    forward_stats = feature_statistics(all_features, "FORWARD_LATEST_10")
    pairs = match_pairs(all_features)
    cohort_counts: dict[str, int] = defaultdict(int)
    for row in all_features:
        cohort_counts[row["cohort"]] += 1

    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "all-trade-features.csv", all_features)
    write_csv(
        arguments.output_dir / "morning-be-features.csv",
        [row for row in all_features if row["segment"] == "MORNING"],
    )
    write_csv(
        arguments.output_dir / "pm-be-features.csv",
        [row for row in all_features if row["segment"] == "PM"],
    )
    for family in ("B", "E", "PM_B", "PM_E"):
        write_csv(
            arguments.output_dir / f"{family.lower().replace('_', '-')}-features.csv",
            [row for row in all_features if row["family"] == family],
        )
    write_csv(arguments.output_dir / "is-feature-statistics.csv", is_stats)
    write_csv(arguments.output_dir / "oos-feature-statistics.csv", oos_stats)
    write_csv(arguments.output_dir / "forward-feature-statistics.csv", forward_stats)
    write_csv(
        arguments.output_dir / "family-direction-statistics.csv",
        is_stats + oos_stats + forward_stats,
    )
    write_csv(arguments.output_dir / "matched-good-bad-pairs.csv", pairs)
    missing = [{
        "feature": feature,
        "available": sum(finite(row.get(feature)) is not None for row in all_features),
        "missing": sum(finite(row.get(feature)) is None for row in all_features),
    } for feature in PRIMARY_FEATURES]
    write_csv(arguments.output_dir / "missing-data-report.csv", missing)

    report = {
        "model": "MIDPOINT_GOOD_BAD_CAUSAL_FEATURE_STUDY_490_V1",
        "session_universe": {
            "analysis_sessions": 490,
            "frozen_sessions": 480,
            "selected_forward_sessions": selected_forward,
            "excluded_forward_trade_sessions_context_only": forward_dates[:-10],
            "context_sessions_for_lagged_features": len(sessions),
            "is_frozen_sessions": len(is_dates),
            "oos_frozen_sessions": len(oos_dates),
            "forward_confirmation_sessions": len(forward_set),
        },
        "trade_rows": len(all_features),
        "cohort_counts": dict(sorted(cohort_counts.items())),
        "primary_feature_count": len(PRIMARY_FEATURES),
        "matched_pairs": len(pairs),
        "interpretation": [
            "GOOD/BAD labels are outcomes; only timestamp-valid features may become rules.",
            "IS is for discovery; OOS and forward are descriptive until one rule is locked.",
            "T+ checkpoint features after a selected exit are missing, never forward-filled.",
            "ATR10 and HTF levels use only sessions completed before the trade date.",
            "Bootstrap confidence intervals resample whole sessions, not individual trades.",
            "No threshold or live decision is created by this run.",
        ],
        "safety": {
            "research_only": True, "observation_only": True,
            "execution_enabled": False, "paper_order_enabled": False,
            "quantity": None, "order_sent": False, "live_modified": False,
        },
    }
    (arguments.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print("Sessions: 490 (480 frozen + latest 10 forward)")
    print("Trade rows:", len(all_features), "cohorts:", dict(cohort_counts))
    print("Matched pairs:", len(pairs))
    print("Output:", arguments.output_dir / "report.json")
    print("Research only: live gates, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
