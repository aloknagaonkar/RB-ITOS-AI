#!/usr/bin/env python3
"""Audit Hilega price/RSI/EMA/WMA history before V2 probability research.

Read only. This program never calls a broker, changes strategy configuration,
starts a worker, or writes into immutable source evidence. It converts cached
one-minute NIFTY candles into canonical five-minute bars, calculates the same
RSI(9) -> EMA(3) / WMA(21) chain as Hilega V1, and emits a research feature
matrix plus a data-readiness report.

Outcome labels are based only on backward/forward price movement normalized by
ATR. Indicators are features, never label inputs, avoiding circular validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from market_lab.hilega_milega_strategy_v1 import HilegaMilegaIndicatorEngineV1


IST = ZoneInfo("Asia/Kolkata")
DEFAULT_CACHE_ROOT = Path(
    "data/historical-evidence/hilega-milega-underlying-cache-v1"
)
DEFAULT_OUTPUT_ROOT = Path(
    "data/historical-evidence/hilega-indicator-dataset-audit-v2"
)
REQUIRED_SOURCE_COLUMNS = ("timestamp", "open", "high", "low", "close")
LABELS = (
    "BULLISH_CONTINUATION",
    "BEARISH_CONTINUATION",
    "BULLISH_TO_BEARISH_REVERSAL",
    "BEARISH_TO_BULLISH_REVERSAL",
    "CONSOLIDATION_OR_TRANSITION",
    "UNLABELED_EDGE",
)


@dataclass(frozen=True)
class Minute:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


def finite_number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numeric value")
    return result


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp is timezone-naive")
    return parsed.astimezone(IST).replace(second=0, microsecond=0)


def source_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        raise ValueError("cache must be a JSON object or list")
    for key in ("candles", "rows", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    raise ValueError("cache has no candles/rows/data list")


def load_minutes(path: Path) -> tuple[list[Minute], dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "path": str(path),
        "source_rows": 0,
        "valid_market_minutes": 0,
        "missing_required": Counter(),
        "corrupt_rows": 0,
        "invalid_ohlc_rows": 0,
        "duplicate_minutes": 0,
        "timezone_naive_rows": 0,
    }
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = source_rows(payload)
    diagnostics["source_rows"] = len(rows)
    by_time: dict[datetime, Minute] = {}

    for row in rows:
        missing = [key for key in REQUIRED_SOURCE_COLUMNS if row.get(key) in (None, "")]
        if missing:
            diagnostics["missing_required"].update(missing)
            diagnostics["corrupt_rows"] += 1
            continue
        try:
            ts = parse_timestamp(row["timestamp"])
            o, h, low, c = (
                finite_number(row["open"]),
                finite_number(row["high"]),
                finite_number(row["low"]),
                finite_number(row["close"]),
            )
            volume = None if row.get("volume") in (None, "") else finite_number(row["volume"])
        except ValueError as exc:
            diagnostics["corrupt_rows"] += 1
            if "timezone-naive" in str(exc):
                diagnostics["timezone_naive_rows"] += 1
            continue
        if h < max(o, low, c) or low > min(o, h, c) or low > h:
            diagnostics["invalid_ohlc_rows"] += 1
            continue
        if not (time(9, 15) <= ts.time() <= time(15, 29)):
            continue
        if ts in by_time:
            diagnostics["duplicate_minutes"] += 1
            continue
        by_time[ts] = Minute(ts, o, h, low, c, volume)

    minutes = [by_time[key] for key in sorted(by_time)]
    diagnostics["valid_market_minutes"] = len(minutes)
    diagnostics["missing_required"] = dict(diagnostics["missing_required"])
    return minutes, diagnostics


def aggregate_five_minute(
    minutes: Iterable[Minute], session_date: date
) -> tuple[list[Bar], list[str]]:
    by_time = {row.timestamp: row for row in minutes if row.timestamp.date() == session_date}
    bars: list[Bar] = []
    issues: list[str] = []
    start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
    # Hilega decision bars run 09:15 through 15:25. The 14:55 execution cutoff
    # is handled separately by the strategy; retaining later bars helps audit.
    for slot in range(75):
        stamp = start + timedelta(minutes=slot * 5)
        needed = [stamp + timedelta(minutes=offset) for offset in range(5)]
        rows = [by_time.get(ts) for ts in needed]
        if all(row is None for row in rows):
            issues.append(f"MISSING_5M:{stamp.isoformat()}")
            continue
        if any(row is None for row in rows):
            missing = ",".join(ts.strftime("%H:%M") for ts, row in zip(needed, rows) if row is None)
            issues.append(f"INCOMPLETE_5M:{stamp.isoformat()}:{missing}")
            continue
        complete = [row for row in rows if row is not None]
        volumes = [row.volume for row in complete]
        bars.append(Bar(
            timestamp=stamp,
            open=complete[0].open,
            high=max(row.high for row in complete),
            low=min(row.low for row in complete),
            close=complete[-1].close,
            volume=None if any(value is None for value in volumes) else sum(volumes),
        ))
    return bars, issues


def linear_slope(values: list[float | None]) -> float | None:
    if not values or any(value is None or not math.isfinite(value) for value in values):
        return None
    ys = [float(value) for value in values if value is not None]
    n = len(ys)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = fmean(ys)
    denominator = sum((x - x_mean) ** 2 for x in range(n))
    return sum((x - x_mean) * (y - y_mean) for x, y in enumerate(ys)) / denominator


def slope_state(value: float | None, epsilon: float) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value > epsilon:
        return "SLOPING_UP"
    if value < -epsilon:
        return "SLOPING_DOWN"
    return "FLAT"


def atr14(rows: list[dict[str, Any]]) -> None:
    true_ranges: list[float] = []
    previous_close: float | None = None
    for row in rows:
        high, low, close = row["high"], row["low"], row["close"]
        tr = high - low if previous_close is None else max(
            high - low, abs(high - previous_close), abs(low - previous_close)
        )
        true_ranges.append(tr)
        row["atr14"] = fmean(true_ranges[-14:]) if len(true_ranges) >= 14 else None
        previous_close = close


def label_rows(rows: list[dict[str, Any]], horizon: int, atr_multiple: float) -> None:
    for index, row in enumerate(rows):
        if index < horizon or index + horizon >= len(rows) or row.get("atr14") is None:
            row["market_state"] = "UNLABELED_EDGE"
            row["prior_move_points"] = None
            row["forward_move_points"] = None
            continue
        prior = row["close"] - rows[index - horizon]["close"]
        future = rows[index + horizon]["close"] - row["close"]
        threshold = atr_multiple * row["atr14"]
        row["prior_move_points"] = prior
        row["forward_move_points"] = future
        row["label_threshold_points"] = threshold
        if prior >= threshold and future >= threshold:
            label = "BULLISH_CONTINUATION"
        elif prior <= -threshold and future <= -threshold:
            label = "BEARISH_CONTINUATION"
        elif prior >= threshold and future <= -threshold:
            label = "BULLISH_TO_BEARISH_REVERSAL"
        elif prior <= -threshold and future >= threshold:
            label = "BEARISH_TO_BULLISH_REVERSAL"
        else:
            label = "CONSOLIDATION_OR_TRANSITION"
        row["market_state"] = label


def feature_rows(
    bars_by_day: dict[str, list[Bar]], *, slope_window: int, flat_epsilon: float,
    label_horizon: int, atr_multiple: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    engine = HilegaMilegaIndicatorEngineV1()
    rows: list[dict[str, Any]] = []
    first_ready_index: int | None = None
    internal_indicator_gaps = 0

    for day in sorted(bars_by_day):
        day_rows: list[dict[str, Any]] = []
        for bar in bars_by_day[day]:
            snapshot = engine.update(bar.close)
            row = {
                **asdict(bar),
                "timestamp": bar.timestamp.isoformat(),
                "session_date": day,
                "rsi9": snapshot.rsi9,
                "ema3_rsi": snapshot.ema3_rsi,
                "wma21_rsi": snapshot.wma21_rsi,
                "ema_minus_wma": (
                    None if snapshot.ema3_rsi is None or snapshot.wma21_rsi is None
                    else snapshot.ema3_rsi - snapshot.wma21_rsi
                ),
                "abs_ema_minus_wma": (
                    None if snapshot.ema3_rsi is None or snapshot.wma21_rsi is None
                    else abs(snapshot.ema3_rsi - snapshot.wma21_rsi)
                ),
            }
            if snapshot.ready and first_ready_index is None:
                first_ready_index = len(rows) + len(day_rows)
            if first_ready_index is not None and not snapshot.ready:
                internal_indicator_gaps += 1
            day_rows.append(row)

        atr14(day_rows)
        for index, row in enumerate(day_rows):
            for name in ("rsi9", "ema3_rsi", "wma21_rsi", "ema_minus_wma"):
                window = [x.get(name) for x in day_rows[max(0, index - slope_window + 1):index + 1]]
                slope = linear_slope(window) if len(window) == slope_window else None
                row[f"{name}_slope_{slope_window}"] = slope
                row[f"{name}_slope_state"] = slope_state(slope, flat_epsilon)
        label_rows(day_rows, label_horizon, atr_multiple)
        rows.extend(day_rows)

    return rows, {
        "first_indicator_ready_row": first_ready_index,
        "expected_warmup_rows": first_ready_index or 0,
        "internal_indicator_gaps_after_ready": internal_indicator_gaps,
    }


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": fmean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def build_report(
    *, files: list[Path], file_diagnostics: list[dict[str, Any]],
    issues: list[dict[str, str]], rows: list[dict[str, Any]],
    indicator_diagnostics: dict[str, Any], slope_window: int,
    flat_epsilon: float, label_horizon: int, atr_multiple: float,
) -> dict[str, Any]:
    sessions = sorted({row["session_date"] for row in rows})
    states = Counter(row["market_state"] for row in rows)
    ready = [row for row in rows if row.get("wma21_rsi") is not None]
    slopes = {
        name: dict(Counter(row[f"{name}_slope_state"] for row in ready))
        for name in ("rsi9", "ema3_rsi", "wma21_rsi", "ema_minus_wma")
    }
    missing = {
        name: sum(row.get(name) is None for row in rows)
        for name in ("open", "high", "low", "close", "rsi9", "ema3_rsi", "wma21_rsi")
    }
    split_at = int(len(sessions) * 0.70)
    continuation = states["BULLISH_CONTINUATION"] + states["BEARISH_CONTINUATION"]
    reversal = (
        states["BULLISH_TO_BEARISH_REVERSAL"]
        + states["BEARISH_TO_BULLISH_REVERSAL"]
    )
    quality_checks = {
        "at_least_100_sessions": len(sessions) >= 100,
        "at_least_5000_ready_rows": len(ready) >= 5000,
        "at_least_200_continuation_labels": continuation >= 200,
        "at_least_100_reversal_labels": reversal >= 100,
        "no_internal_indicator_gaps": indicator_diagnostics[
            "internal_indicator_gaps_after_ready"
        ] == 0,
        "no_duplicate_source_minutes": sum(
            item["duplicate_minutes"] for item in file_diagnostics
        ) == 0,
        "no_invalid_ohlc_rows": sum(
            item["invalid_ohlc_rows"] for item in file_diagnostics
        ) == 0,
    }
    return {
        "model": "HILEGA_INDICATOR_DATASET_AUDIT_V2",
        "purpose": "PRE_OPTIMIZATION_DATA_READINESS_ONLY",
        "source": {
            "cache_files": len(files),
            "sessions": len(sessions),
            "first_session": sessions[0] if sessions else None,
            "last_session": sessions[-1] if sessions else None,
            "source_rows": sum(item["source_rows"] for item in file_diagnostics),
            "valid_market_minutes": sum(
                item["valid_market_minutes"] for item in file_diagnostics
            ),
            "five_minute_rows": len(rows),
            "indicator_ready_rows": len(ready),
        },
        "schema": {
            "required_source_columns": list(REQUIRED_SOURCE_COLUMNS),
            "generated_indicator_columns": ["rsi9", "ema3_rsi", "wma21_rsi"],
            "missing_values": missing,
            "corrupt_source_rows": sum(
                item["corrupt_rows"] for item in file_diagnostics
            ),
            "invalid_ohlc_rows": sum(
                item["invalid_ohlc_rows"] for item in file_diagnostics
            ),
            "duplicate_source_minutes": sum(
                item["duplicate_minutes"] for item in file_diagnostics
            ),
            "five_minute_coverage_issues": len(issues),
            **indicator_diagnostics,
        },
        "feature_engineering": {
            "ema_wma_difference": "ema3_rsi - wma21_rsi",
            "slope_method": "OLS slope per completed 5-minute bar",
            "slope_window_bars": slope_window,
            "flat_epsilon_indicator_units_per_bar": flat_epsilon,
            "slope_state_distribution": slopes,
        },
        "labeling": {
            "method": (
                "Price-only prior and forward movement over the same horizon, "
                "compared with timestamp ATR(14); indicators are excluded from labels."
            ),
            "horizon_bars": label_horizon,
            "horizon_minutes": label_horizon * 5,
            "atr_multiple": atr_multiple,
            "state_distribution": {label: states[label] for label in LABELS},
        },
        "chronological_split": {
            "in_sample_sessions": split_at,
            "in_sample_first": sessions[0] if sessions else None,
            "in_sample_last": sessions[split_at - 1] if split_at else None,
            "out_of_sample_sessions": len(sessions) - split_at,
            "out_of_sample_first": sessions[split_at] if split_at < len(sessions) else None,
            "out_of_sample_last": sessions[-1] if sessions else None,
        },
        "descriptive_values": {
            "rsi9": numeric_summary([row["rsi9"] for row in ready]),
            "ema3_rsi": numeric_summary([row["ema3_rsi"] for row in ready]),
            "wma21_rsi": numeric_summary([row["wma21_rsi"] for row in ready]),
            "ema_minus_wma": numeric_summary([row["ema_minus_wma"] for row in ready]),
        },
        "readiness": {
            "checks": quality_checks,
            "probability_analysis_ready": all(quality_checks.values()),
            "recommendation": (
                "Proceed to locked IS discovery and one-time OOS validation."
                if all(quality_checks.values())
                else "Repair failed checks or limit claims to descriptive research."
            ),
        },
        "missing_data_policy": {
            "ohlc": "Do not forward-fill; exclude an incomplete five-minute bar.",
            "indicator_warmup": "Expected leading warmup is dropped from probability analysis.",
            "indicator_internal_gap": "Treat as corruption; do not forward-fill because it changes slopes.",
            "volume": "May remain unavailable; it is not required for this indicator-only audit.",
        },
        "safety": {
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "live_strategy_modified": False,
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(
    cache_root: Path, output_root: Path, *, slope_window: int = 3,
    flat_epsilon: float = 0.10, label_horizon: int = 6,
    atr_multiple: float = 0.50,
) -> dict[str, Any]:
    if slope_window < 2:
        raise ValueError("slope_window must be at least 2")
    if flat_epsilon < 0 or label_horizon < 1 or atr_multiple <= 0:
        raise ValueError("invalid slope/label configuration")
    files = sorted(cache_root.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No Hilega cache JSON files found: {cache_root}")

    bars_by_day: dict[str, list[Bar]] = {}
    diagnostics: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for path in files:
        try:
            minutes, diagnostic = load_minutes(path)
            diagnostics.append(diagnostic)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append({
                "path": str(path), "source_rows": 0, "valid_market_minutes": 0,
                "missing_required": {}, "corrupt_rows": 1, "invalid_ohlc_rows": 0,
                "duplicate_minutes": 0, "timezone_naive_rows": 0,
            })
            issues.append({"session_date": path.stem, "issue": f"UNREADABLE_CACHE:{type(exc).__name__}:{exc}"})
            continue
        days = sorted({minute.timestamp.date() for minute in minutes})
        if len(days) != 1:
            issues.append({"session_date": path.stem, "issue": f"CACHE_DAY_COUNT:{len(days)}"})
        for session in days:
            bars, coverage = aggregate_five_minute(minutes, session)
            key = session.isoformat()
            if key in bars_by_day:
                issues.append({"session_date": key, "issue": "DUPLICATE_SESSION_CACHE"})
                continue
            bars_by_day[key] = bars
            issues.extend({"session_date": key, "issue": value} for value in coverage)

    rows, indicator_diagnostics = feature_rows(
        bars_by_day,
        slope_window=slope_window,
        flat_epsilon=flat_epsilon,
        label_horizon=label_horizon,
        atr_multiple=atr_multiple,
    )
    report = build_report(
        files=files,
        file_diagnostics=diagnostics,
        issues=issues,
        rows=rows,
        indicator_diagnostics=indicator_diagnostics,
        slope_window=slope_window,
        flat_epsilon=flat_epsilon,
        label_horizon=label_horizon,
        atr_multiple=atr_multiple,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    write_csv(output_root / "indicator-feature-matrix.csv", rows)
    write_csv(output_root / "data-issues.csv", issues)
    write_csv(output_root / "source-file-diagnostics.csv", diagnostics)
    (output_root / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--slope-window", type=int, default=3)
    parser.add_argument("--flat-epsilon", type=float, default=0.10)
    parser.add_argument("--label-horizon", type=int, default=6)
    parser.add_argument("--atr-multiple", type=float, default=0.50)
    args = parser.parse_args()
    report = run(
        args.cache_root, args.output_root,
        slope_window=args.slope_window,
        flat_epsilon=args.flat_epsilon,
        label_horizon=args.label_horizon,
        atr_multiple=args.atr_multiple,
    )
    source = report["source"]
    print(
        "HILEGA DATASET AUDIT",
        "sessions", source["sessions"],
        "5m rows", source["five_minute_rows"],
        "ready rows", source["indicator_ready_rows"],
    )
    print("date range", source["first_session"], "to", source["last_session"])
    print("market states", report["labeling"]["state_distribution"])
    print("quality checks", report["readiness"]["checks"])
    print("probability analysis ready:", report["readiness"]["probability_analysis_ready"])
    print("output:", args.output_root / "report.json")
    print("features:", args.output_root / "indicator-feature-matrix.csv")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
