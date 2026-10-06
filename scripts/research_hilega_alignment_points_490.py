#!/usr/bin/env python3
"""Attribute canonical Hilega trade points to RSI/EMA3/WMA21 alignments.

The program replays the unchanged directional V1 coordinator from cached
one-minute NIFTY data.  It measures real canonical entry-to-exit NIFTY points,
MFE, MAE, giveback and indicator health at entry and on every held candle.
No candidate controls a strategy decision in this research run.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from market_lab.hilega_directional_coordinator_v1 import (
    BEARISH_ENTRY_EVENTS,
    BEARISH_EXIT_EVENTS,
    BULLISH_ENTRY_EVENTS,
    BULLISH_EXIT_EVENTS,
    HilegaDirectionalCoordinatorV1,
)
from market_lab.hilega_milega_historical_replay_v1 import (
    UNDERLYING,
    _read_cache,
    aggregate_exact_5m,
)


DEFAULT_CACHE = Path(
    "data/historical-evidence/hilega-milega-underlying-cache-v1"
)
DEFAULT_FEATURES = Path(
    "data/historical-evidence/hilega-indicator-dataset-audit-v2/"
    "indicator-feature-matrix.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1"
)
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ActiveTrade:
    trade_id: str
    session_date: str
    direction: str
    route: str
    entry_event: str
    entry_timestamp: datetime
    entry_price: float
    entry_features: dict[str, Any]
    mfe_points: float = 0.0
    mae_points: float = 0.0
    bars_held: int = 0


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_features(path: Path) -> tuple[list[str], dict[tuple[str, str], dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    sessions: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            session = raw["session_date"]
            timestamp = datetime.fromisoformat(raw["timestamp"])
            key = (session, timestamp.strftime("%H:%M"))
            raw["time"] = key[1]
            for name in (
                "open", "high", "low", "close", "rsi9", "ema3_rsi",
                "wma21_rsi", "ema_minus_wma", "atr14",
                "rsi9_slope_3", "ema3_rsi_slope_3", "wma21_rsi_slope_3",
                "ema_minus_wma_slope_3",
            ):
                if name in raw:
                    raw[name] = number(raw[name])
            lookup[key] = raw
            sessions.add(session)
    return sorted(sessions), lookup


def directional_state(value: float | None, epsilon: float) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value > epsilon:
        return "UP"
    if value < -epsilon:
        return "DOWN"
    return "FLAT"


def health_components(
    feature: dict[str, Any], direction: str, *, epsilon: float
) -> dict[str, Any]:
    sign = 1.0 if direction == "BULLISH" else -1.0
    rsi = number(feature.get("rsi9"))
    gap = number(feature.get("ema_minus_wma"))
    rsi_slope = number(feature.get("rsi9_slope_3"))
    ema_slope = number(feature.get("ema3_rsi_slope_3"))
    wma_slope = number(feature.get("wma21_rsi_slope_3"))
    gap_slope = number(feature.get("ema_minus_wma_slope_3"))

    values = (rsi, gap, rsi_slope, ema_slope, wma_slope, gap_slope)
    if any(value is None for value in values):
        return {
            "health": "UNAVAILABLE",
            "support_count": None,
            "wma_state": directional_state(wma_slope, epsilon),
        }

    components = {
        "wma_direction_support": sign * wma_slope > epsilon,
        "ema_direction_support": sign * ema_slope > epsilon,
        "rsi_side_support": sign * (rsi - 50.0) > 0,
        "rsi_slope_support": sign * rsi_slope > epsilon,
        "ema_wma_gap_support": sign * gap > 0,
    }
    support_count = sum(components.values())
    wma_state = directional_state(wma_slope, epsilon)
    gap_state = (
        "DIRECTIONAL_WIDENING" if sign * gap_slope > epsilon
        else "ADVERSE_NARROWING" if sign * gap_slope < -epsilon
        else "STABLE"
    )
    adverse_rsi = sign * rsi_slope < -epsilon
    adverse_ema = sign * ema_slope < -epsilon
    adverse_wma = sign * wma_slope <= epsilon
    reversal_risk = adverse_wma and adverse_ema and adverse_rsi and gap_state == "ADVERSE_NARROWING"

    if reversal_risk:
        health = "REVERSAL_RISK"
    elif wma_state == "FLAT" and support_count >= 2:
        health = "WMA_FLAT_WAIT"
    elif support_count >= 4:
        health = "HEALTHY_ALIGNED"
    elif support_count >= 2:
        health = "MIXED"
    else:
        health = "OPPOSING"

    rsi_bin = (
        "LT30" if rsi < 30 else "30_40" if rsi < 40 else
        "40_50" if rsi < 50 else "50_60" if rsi < 60 else
        "60_70" if rsi < 70 else "GE70"
    )
    result = {
        **components,
        "health": health,
        "support_count": support_count,
        "wma_state": wma_state,
        "ema_state": directional_state(ema_slope, epsilon),
        "rsi_slope_state": directional_state(rsi_slope, epsilon),
        "gap_state": gap_state,
        "rsi_bin": rsi_bin,
        "reversal_risk": reversal_risk,
    }
    result["alignment_signature"] = "|".join((
        f"WMA_{result['wma_state']}",
        f"EMA_{result['ema_state']}",
        f"RSI_{rsi_bin}",
        f"RSISLOPE_{result['rsi_slope_state']}",
        f"GAP_{'PASS' if components['ema_wma_gap_support'] else 'FAIL'}",
        gap_state,
    ))
    return result


def route_name(event_type: str) -> str:
    if "OPENING" in event_type:
        return "OPENING"
    if "ROUTE_A" in event_type:
        return "ROUTE_A"
    if "ROUTE_B" in event_type:
        return "ROUTE_B"
    return "OTHER"


def update_excursion(active: ActiveTrade, high: float, low: float) -> None:
    if active.direction == "BULLISH":
        favourable = high - active.entry_price
        adverse = low - active.entry_price
    else:
        favourable = active.entry_price - low
        adverse = active.entry_price - high
    active.mfe_points = max(active.mfe_points, favourable)
    active.mae_points = min(active.mae_points, adverse)
    active.bars_held += 1


def directional_points(direction: str, entry: float, exit_price: float) -> float:
    return exit_price - entry if direction == "BULLISH" else entry - exit_price


def accepted_entry(decision: Any) -> tuple[str, Any] | None:
    for event in decision.accepted_events:
        if event.event_type in BULLISH_ENTRY_EVENTS:
            return "BULLISH", event
        if event.event_type in BEARISH_ENTRY_EVENTS:
            return "BEARISH", event
    return None


def accepted_exit(decision: Any, direction: str) -> Any | None:
    allowed = BULLISH_EXIT_EVENTS if direction == "BULLISH" else BEARISH_EXIT_EVENTS
    return next(
        (event for event in decision.accepted_events if event.event_type in allowed),
        None,
    )


def split_name(session: str, is_sessions: set[str]) -> str:
    return "IS" if session in is_sessions else "OOS"


def replay(
    *,
    cache_root: Path,
    all_sessions: list[str],
    analysis_sessions: list[str],
    feature_lookup: dict[tuple[str, str], dict[str, Any]],
    flat_epsilon: float,
    strategy_cutoff_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = set(analysis_sessions)
    split_at = int(len(analysis_sessions) * 0.70)
    is_sessions = set(analysis_sessions[:split_at])
    coordinator = HilegaDirectionalCoordinatorV1()
    trades: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    active: ActiveTrade | None = None
    sequence = 0

    for session in all_sessions:
        day = date.fromisoformat(session)
        path = cache_root / f"{session}.json"
        candles = _read_cache(path, UNDERLYING, day)
        if not candles:
            continue
        if strategy_cutoff_only:
            # Validate only evidence consumed by the strategy. A missing minute
            # in the post-cutoff 15:25 bar must not invalidate the complete
            # 09:15-14:59 decision window, and no candle is synthesized.
            candles = [
                candle for candle in candles
                if candle.timestamp.astimezone(IST).strftime("%H:%M") <= "14:59"
            ]
        bars = aggregate_exact_5m(candles, day, require_full_session=not strategy_cutoff_only)
        if strategy_cutoff_only:
            bars = [bar for bar in bars if bar.ts.strftime("%H:%M") <= "14:55"]
            if len(bars) != 69:
                raise ValueError(f"{session}: incomplete strategy window through 14:55")
        elif len(bars) != 75:
            raise ValueError(f"{session}: expected 75 five-minute bars, got {len(bars)}")

        for bar in bars:
            key = (session, bar.ts.strftime("%H:%M"))
            feature = feature_lookup.get(key, {})
            active_before = active
            decision = coordinator.on_bar(bar)

            exit_event = None
            if active_before is not None:
                exit_event = accepted_exit(decision, active_before.direction)
                # A 14:55 cutoff is valued at bar open; subsequent intrabar range
                # must not leak into MFE/MAE. Structural exits use completed bars.
                if exit_event is None or "CUTOFF" not in exit_event.event_type:
                    update_excursion(active_before, float(bar.high), float(bar.low))
                health = health_components(
                    feature, active_before.direction, epsilon=flat_epsilon
                )
                timeline.append({
                    "trade_id": active_before.trade_id,
                    "session_date": session,
                    "timestamp": bar.ts.isoformat(),
                    "minutes_from_entry": int(
                        (bar.ts - active_before.entry_timestamp).total_seconds() // 60
                    ),
                    "direction": active_before.direction,
                    "close": float(bar.close),
                    "directional_points_close": directional_points(
                        active_before.direction,
                        active_before.entry_price,
                        float(bar.close),
                    ),
                    "mfe_points": active_before.mfe_points,
                    "mae_points": active_before.mae_points,
                    **{name: feature.get(name) for name in (
                        "rsi9", "ema3_rsi", "wma21_rsi", "ema_minus_wma",
                        "rsi9_slope_3", "ema3_rsi_slope_3",
                        "wma21_rsi_slope_3", "ema_minus_wma_slope_3",
                    )},
                    **health,
                    "is_exit_candle": exit_event is not None,
                })

            if active_before is not None and exit_event is not None:
                exit_price = float(exit_event.price)
                points = directional_points(
                    active_before.direction, active_before.entry_price, exit_price
                )
                entry_health = health_components(
                    active_before.entry_features,
                    active_before.direction,
                    epsilon=flat_epsilon,
                )
                trades.append({
                    "trade_id": active_before.trade_id,
                    "session_date": session,
                    "split": split_name(session, is_sessions),
                    "direction": active_before.direction,
                    "route": active_before.route,
                    "entry_timestamp": active_before.entry_timestamp.isoformat(),
                    "entry_event": active_before.entry_event,
                    "entry_price": active_before.entry_price,
                    "exit_timestamp": exit_event.event_time.isoformat(),
                    "exit_event": exit_event.event_type,
                    "exit_price": exit_price,
                    "captured_points": points,
                    "outcome": "POSITIVE" if points > 0 else (
                        "NEGATIVE" if points < 0 else "FLAT"
                    ),
                    "mfe_points": active_before.mfe_points,
                    "mae_points": active_before.mae_points,
                    "giveback_points": active_before.mfe_points - points,
                    "exit_efficiency_pct": (
                        100.0 * points / active_before.mfe_points
                        if active_before.mfe_points > 0 else None
                    ),
                    "reached_plus10": active_before.mfe_points >= 10.0,
                    "reached_plus20": active_before.mfe_points >= 20.0,
                    "bars_held": active_before.bars_held,
                    **{f"entry_{name}": active_before.entry_features.get(name) for name in (
                        "rsi9", "ema3_rsi", "wma21_rsi", "ema_minus_wma",
                        "rsi9_slope_3", "ema3_rsi_slope_3",
                        "wma21_rsi_slope_3", "ema_minus_wma_slope_3",
                    )},
                    **{f"entry_{key}": value for key, value in entry_health.items()},
                })
                active = None

            entry = accepted_entry(decision)
            if entry is not None:
                if active is not None:
                    raise RuntimeError(
                        f"new entry while active at {bar.ts.isoformat()}"
                    )
                direction, event = entry
                if session not in selected:
                    # Context sessions warm canonical indicators/states only.
                    continue
                sequence += 1
                entry_price = float(
                    event.price if event.price is not None else event.entry_price
                )
                active = ActiveTrade(
                    trade_id=f"{session}-{sequence:04d}",
                    session_date=session,
                    direction=direction,
                    route=route_name(event.event_type),
                    entry_event=event.event_type,
                    entry_timestamp=event.event_time,
                    entry_price=entry_price,
                    entry_features=feature,
                )
                entry_health = health_components(
                    feature, direction, epsilon=flat_epsilon
                )
                timeline.append({
                    "trade_id": active.trade_id,
                    "session_date": session,
                    "timestamp": bar.ts.isoformat(),
                    "minutes_from_entry": 0,
                    "direction": direction,
                    "close": float(bar.close),
                    "directional_points_close": directional_points(
                        direction, entry_price, float(bar.close)
                    ),
                    "mfe_points": 0.0,
                    "mae_points": 0.0,
                    **{name: feature.get(name) for name in (
                        "rsi9", "ema3_rsi", "wma21_rsi", "ema_minus_wma",
                        "rsi9_slope_3", "ema3_rsi_slope_3",
                        "wma21_rsi_slope_3", "ema_minus_wma_slope_3",
                    )},
                    **entry_health,
                    "is_entry_candle": True,
                    "is_exit_candle": False,
                })

        if active is not None and active.session_date == session:
            raise RuntimeError(f"canonical trade unresolved after session {session}")

    return trades, timeline


def maximum_drawdown(points: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0, "total_points": 0.0, "mean_points": None,
            "median_points": None, "positive": 0, "negative": 0,
            "win_rate_pct": None, "profit_factor": None,
            "max_drawdown_points": 0.0,
        }
    points = [float(row["captured_points"]) for row in rows]
    gains = sum(value for value in points if value > 0)
    losses = -sum(value for value in points if value < 0)
    positive = sum(value > 0 for value in points)
    return {
        "trades": len(rows),
        "total_points": sum(points),
        "mean_points": fmean(points),
        "median_points": median(points),
        "positive": positive,
        "negative": sum(value < 0 for value in points),
        "flat": sum(value == 0 for value in points),
        "win_rate_pct": 100.0 * positive / len(rows),
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_points": maximum_drawdown(points),
        "mean_mfe_points": fmean(float(row["mfe_points"]) for row in rows),
        "mean_mae_points": fmean(float(row["mae_points"]) for row in rows),
        "mean_giveback_points": fmean(float(row["giveback_points"]) for row in rows),
        "plus10_rate_pct": 100.0 * sum(bool(row["reached_plus10"]) for row in rows) / len(rows),
        "plus20_rate_pct": 100.0 * sum(bool(row["reached_plus20"]) for row in rows) / len(rows),
        "best_points": max(points),
        "worst_points": min(points),
    }


def group_summary(
    rows: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(field) for field in fields)].append(row)
    result = []
    for key, values in sorted(groups.items(), key=lambda item: tuple(str(x) for x in item[0])):
        result.append({**dict(zip(fields, key)), **metrics(values)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--analysis-sessions", type=int, default=490)
    parser.add_argument("--context-sessions", type=int, default=10)
    parser.add_argument("--flat-epsilon", type=float, default=0.10)
    args = parser.parse_args()

    sessions, features = load_features(args.features)
    required = args.analysis_sessions + args.context_sessions
    if len(sessions) < required:
        raise SystemExit(
            f"STOP: need {required} valid feature sessions "
            f"({args.analysis_sessions} analysis + {args.context_sessions} context); "
            f"found {len(sessions)}. Run materialization and audit first."
        )
    selected_all = sessions[-required:]
    analysis = selected_all[-args.analysis_sessions:]
    context = selected_all[:args.context_sessions]

    trades, timeline = replay(
        cache_root=args.cache_root,
        all_sessions=selected_all,
        analysis_sessions=analysis,
        feature_lookup=features,
        flat_epsilon=args.flat_epsilon,
    )
    if not trades:
        raise SystemExit("STOP: canonical replay produced no completed trades")

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "trade-alignment-points.csv", trades)
    write_csv(args.output_root / "trade-health-timeline.csv", timeline)
    write_csv(
        args.output_root / "alignment-summary.csv",
        group_summary(trades, (
            "split", "direction", "route", "entry_health",
            "entry_wma_state", "entry_gap_state",
        )),
    )
    write_csv(
        args.output_root / "wma-state-summary.csv",
        group_summary(trades, ("split", "direction", "entry_wma_state")),
    )
    write_csv(
        args.output_root / "daily-points.csv",
        group_summary(trades, ("session_date",)),
    )
    write_csv(
        args.output_root / "component-summary.csv",
        group_summary(trades, (
            "split", "direction", "entry_wma_direction_support",
            "entry_ema_direction_support", "entry_rsi_side_support",
            "entry_rsi_slope_support", "entry_ema_wma_gap_support",
        )),
    )

    report = {
        "model": "HILEGA_ALIGNMENT_POINTS_490_V1",
        "purpose": "EXPLAIN_EXISTING_STRATEGY_POINTS_BY_ENTRY_ALIGNMENT",
        "sessions": {
            "analysis": len(analysis),
            "context": len(context),
            "analysis_first": analysis[0],
            "analysis_last": analysis[-1],
            "is": int(len(analysis) * 0.70),
            "oos": len(analysis) - int(len(analysis) * 0.70),
        },
        "overall": metrics(trades),
        "by_split_direction": group_summary(trades, ("split", "direction")),
        "by_entry_health": group_summary(
            trades, ("split", "direction", "entry_health")
        ),
        "by_wma_state": group_summary(
            trades, ("split", "direction", "entry_wma_state")
        ),
        "definitions": {
            "indicator_chain": "RSI9 -> EMA3(RSI9) and WMA21(RSI9)",
            "flat": f"absolute OLS 3-bar slope <= {args.flat_epsilon}",
            "wma_flat": "WAIT evidence; never treated as reversal by itself",
            "reversal_risk": (
                "WMA not directionally supportive AND EMA slope adverse AND "
                "RSI slope adverse AND EMA-WMA gap narrowing adversely"
            ),
            "mfe_mae": "post-entry bars only; cutoff exits exclude cutoff-bar range",
            "points": "bull exit-entry; bear entry-exit",
        },
        "limitations": [
            "Underlying NIFTY points only; option premium, spread, charges and quantity excluded.",
            "Alignment states explain the unchanged canonical V1 lifecycle; they do not veto entries.",
            "Threshold selection must use IS only before one-time OOS confirmation.",
        ],
        "safety": {
            "research_only": True,
            "observation_only": True,
            "live_strategy_modified": False,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print("HILEGA ALIGNMENT POINTS", len(analysis), "sessions", len(trades), "trades")
    print("OVERALL", report["overall"])
    for row in report["by_entry_health"]:
        print("HEALTH", row)
    print("Output:", args.output_root / "report.json")
    print("Read only: strategy, live audit, services, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
