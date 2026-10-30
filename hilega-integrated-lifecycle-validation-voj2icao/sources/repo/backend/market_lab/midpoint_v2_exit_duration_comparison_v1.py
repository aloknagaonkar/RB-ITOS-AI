from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_EXIT_DURATION_COMPARISON_V1"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V2_NEW_ARM_EXACT_OPTION_ECONOMICS_V1"

ROUND_TRIP_COST_PCT_POINTS = 0.5
INITIAL_STOP_PCT = 5.0
BREAKEVEN_TRIGGER_PCT = 5.0
TRAIL_ACTIVATION_PCT = 10.0
TRAIL_DISTANCE_PCT = 3.0
TRAIL_ONLY_SAFETY_CAP_MINUTES = 60

POLICIES = {
    "E15": {"mode": "FIXED_TIME", "max_hold_minutes": 15},
    "HYBRID": {"mode": "HYBRID", "max_hold_minutes": 15},
    "E20": {"mode": "FIXED_TIME", "max_hold_minutes": 20},
    "E30": {"mode": "FIXED_TIME", "max_hold_minutes": 30},
    "TRAIL_ONLY": {
        "mode": "TRAIL_ONLY",
        "max_hold_minutes": TRAIL_ONLY_SAFETY_CAP_MINUTES,
    },
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_block_path(value: str) -> tuple[str, Path]:
    if "|" not in value:
        raise ValueError("expected BLOCK|path")
    block, path = value.split("|", 1)
    return block.strip(), Path(path.strip())


def first_existing(headers: list[str], candidates: tuple[str, ...]) -> str:
    lower = {h.lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    raise ValueError(
        f"none of columns {candidates!r} found; available={headers!r}"
    )


def optional_existing(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    lower = {h.lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_ohlc(path: Path) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        ts_col = first_existing(
            headers, ("timestamp", "datetime", "time", "ts", "candle_timestamp")
        )
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        key_col = first_existing(
            headers, ("instrument_key", "instrument", "instrument_token", "key")
        )
        open_col = first_existing(headers, ("open", "open_price", "o"))
        high_col = first_existing(headers, ("high", "high_price", "h"))
        low_col = first_existing(headers, ("low", "low_price", "l"))
        close_col = first_existing(headers, ("close", "close_price", "c"))

        for row in reader:
            raw_ts = row.get(ts_col)
            key = row.get(key_col)
            if not raw_ts or not key:
                continue
            try:
                ts = parse_dt(str(raw_ts))
            except ValueError:
                continue
            session_date = (
                str(row.get(date_col))
                if date_col and row.get(date_col)
                else ts.date().isoformat()
            )
            out.setdefault((session_date, str(key)), {})[ts.isoformat()] = {
                "timestamp": ts.isoformat(),
                "open": finite_float(row.get(open_col)),
                "high": finite_float(row.get(high_col)),
                "low": finite_float(row.get(low_col)),
                "close": finite_float(row.get(close_col)),
            }
    return out


def pct(entry: float, price: float) -> float:
    return (price / entry - 1.0) * 100.0


def replay_trade(
    trade: dict[str, Any],
    series: dict[str, dict[str, Any]],
    policy_id: str,
) -> dict[str, Any]:
    spec = POLICIES[policy_id]
    entry_ts = parse_dt(str(trade["entry_timestamp"]))
    entry = float(trade["entry_price"])

    active_stop = entry * (1.0 - INITIAL_STOP_PCT / 100.0)
    best_high = entry
    breakeven_activated = False
    trail_activated = False

    stop_history: list[dict[str, Any]] = []
    exit_ts: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    last_elapsed = None

    for elapsed in range(0, int(spec["max_hold_minutes"]) + 1):
        ts = entry_ts + timedelta(minutes=elapsed)
        candle = series.get(ts.isoformat())
        if candle is None:
            return {
                **trade,
                "policy_id": policy_id,
                "exit_available": False,
                "issue": "MISSING_OHLC_DURING_REPLAY",
                "missing_timestamp": ts.isoformat(),
            }

        o = candle.get("open")
        h = candle.get("high")
        l = candle.get("low")
        c = candle.get("close")
        if any(v is None for v in (o, h, l, c)):
            return {
                **trade,
                "policy_id": policy_id,
                "exit_available": False,
                "issue": "INCOMPLETE_OHLC_DURING_REPLAY",
                "missing_timestamp": ts.isoformat(),
            }

        o, h, l, c = float(o), float(h), float(l), float(c)
        last_elapsed = elapsed
        stop_history.append(
            {
                "timestamp": ts.isoformat(),
                "active_stop": active_stop,
                "breakeven_active": breakeven_activated,
                "trail_active": trail_activated,
            }
        )

        # Frozen long-option stop semantics: gap-through exits at OPEN,
        # otherwise intrabar touch exits at the active stop.
        if o <= active_stop:
            exit_ts = ts
            exit_price = o
            exit_reason = "STOP_GAP"
            break
        if l <= active_stop:
            exit_ts = ts
            exit_price = active_stop
            exit_reason = "STOP_TOUCH"
            break

        # Time rule is checked using the state active ENTERING this bar.
        if spec["mode"] == "FIXED_TIME" and elapsed == spec["max_hold_minutes"]:
            exit_ts = ts
            exit_price = c
            exit_reason = "TIME_EXIT"
            break

        if spec["mode"] == "HYBRID" and elapsed == spec["max_hold_minutes"]:
            # At 15m, continue only when trailing was already active before
            # this bar. A trail triggered by this bar activates next bar, so
            # it does not qualify.
            if not trail_activated:
                exit_ts = ts
                exit_price = c
                exit_reason = "TIME_EXIT_NO_ACTIVE_TRAIL"
                break
            # If trail is already active, continue. The practical upper bound
            # is supplied below by the safety-cap extension loop.

        # Update best high and schedule BE/trailing for NEXT bar only.
        best_high = max(best_high, h)
        next_stop = active_stop
        next_be = breakeven_activated
        next_trail = trail_activated

        if h >= entry * (1.0 + BREAKEVEN_TRIGGER_PCT / 100.0):
            next_be = True
            next_stop = max(next_stop, entry)

        if h >= entry * (1.0 + TRAIL_ACTIVATION_PCT / 100.0):
            next_trail = True

        if next_trail:
            next_stop = max(
                next_stop,
                best_high * (1.0 - TRAIL_DISTANCE_PCT / 100.0),
            )

        active_stop = next_stop
        breakeven_activated = next_be
        trail_activated = next_trail

    # HYBRID needs continuation beyond 15m only when trail is already active.
    if (
        exit_ts is None
        and spec["mode"] == "HYBRID"
        and trail_activated
        and last_elapsed == spec["max_hold_minutes"]
    ):
        for elapsed in range(int(spec["max_hold_minutes"]) + 1, TRAIL_ONLY_SAFETY_CAP_MINUTES + 1):
            ts = entry_ts + timedelta(minutes=elapsed)
            candle = series.get(ts.isoformat())
            if candle is None:
                return {
                    **trade,
                    "policy_id": policy_id,
                    "exit_available": False,
                    "issue": "MISSING_OHLC_DURING_HYBRID_EXTENSION",
                    "missing_timestamp": ts.isoformat(),
                }
            vals = [candle.get(k) for k in ("open", "high", "low", "close")]
            if any(v is None for v in vals):
                return {
                    **trade,
                    "policy_id": policy_id,
                    "exit_available": False,
                    "issue": "INCOMPLETE_OHLC_DURING_HYBRID_EXTENSION",
                    "missing_timestamp": ts.isoformat(),
                }
            o, h, l, c = map(float, vals)
            stop_history.append(
                {
                    "timestamp": ts.isoformat(),
                    "active_stop": active_stop,
                    "breakeven_active": breakeven_activated,
                    "trail_active": trail_activated,
                }
            )
            if o <= active_stop:
                exit_ts, exit_price, exit_reason = ts, o, "STOP_GAP"
                break
            if l <= active_stop:
                exit_ts, exit_price, exit_reason = ts, active_stop, "STOP_TOUCH"
                break

            best_high = max(best_high, h)
            active_stop = max(
                active_stop,
                best_high * (1.0 - TRAIL_DISTANCE_PCT / 100.0),
            )

            if elapsed == TRAIL_ONLY_SAFETY_CAP_MINUTES:
                exit_ts, exit_price, exit_reason = ts, c, "SAFETY_CAP_EXIT"
                break

    # TRAIL_ONLY reaches its research safety cap if no stop occurs.
    if exit_ts is None and spec["mode"] == "TRAIL_ONLY":
        ts = entry_ts + timedelta(minutes=TRAIL_ONLY_SAFETY_CAP_MINUTES)
        candle = series.get(ts.isoformat())
        if candle is None or candle.get("close") is None:
            return {
                **trade,
                "policy_id": policy_id,
                "exit_available": False,
                "issue": "MISSING_SAFETY_CAP_CLOSE",
                "missing_timestamp": ts.isoformat(),
            }
        exit_ts = ts
        exit_price = float(candle["close"])
        exit_reason = "SAFETY_CAP_EXIT"

    if exit_ts is None or exit_price is None or exit_reason is None:
        return {
            **trade,
            "policy_id": policy_id,
            "exit_available": False,
            "issue": "NO_EXIT_RESOLVED",
        }

    gross = pct(entry, exit_price)
    net = gross - ROUND_TRIP_COST_PCT_POINTS
    duration = int((exit_ts - entry_ts).total_seconds() // 60)

    return {
        **trade,
        "policy_id": policy_id,
        "exit_available": True,
        "issue": None,
        "exit_timestamp": exit_ts.isoformat(),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "duration_minutes": duration,
        "gross_return_pct": gross,
        "net_return_pct": net,
        "best_high_before_exit": best_high,
        "mfe_capture_ratio": (
            net / float(trade["mfe_pct_15m"])
            if trade.get("mfe_pct_15m") not in (None, 0)
            and net > 0
            else None
        ),
        "stop_history": stop_history,
    }


def max_consecutive_losses(values: list[float]) -> int:
    best = cur = 0
    for v in values:
        if v <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def max_drawdown_pct_points(values: list[float]) -> float:
    equity = peak = 0.0
    worst = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r.get("exit_available")]
    vals = [float(r["net_return_pct"]) for r in valid]
    winners = [v for v in vals if v > 0]
    losers = [v for v in vals if v <= 0]
    gross_profit = sum(winners)
    gross_loss = -sum(v for v in losers if v < 0)
    durations = [int(r["duration_minutes"]) for r in valid]
    capture = [
        float(r["mfe_capture_ratio"])
        for r in valid
        if r.get("mfe_capture_ratio") is not None
    ]
    return {
        "trade_count": len(rows),
        "exit_available_count": len(valid),
        "issue_counts": dict(
            sorted(Counter(str(r.get("issue")) for r in rows if r.get("issue")).items())
        ),
        "winner_count": len(winners),
        "win_rate_pct": (100.0 * len(winners) / len(vals)) if vals else None,
        "mean_net_pct": mean(vals) if vals else None,
        "median_net_pct": median(vals) if vals else None,
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else (float("inf") if gross_profit > 0 else None)
        ),
        "average_winner_pct": mean(winners) if winners else None,
        "average_loser_pct": mean(losers) if losers else None,
        "best_trade_pct": max(vals) if vals else None,
        "worst_trade_pct": min(vals) if vals else None,
        "sum_net_pct_points": sum(vals) if vals else None,
        "max_consecutive_losses": max_consecutive_losses(vals),
        "max_drawdown_pct_points": max_drawdown_pct_points(vals),
        "mean_duration_minutes": mean(durations) if durations else None,
        "median_duration_minutes": median(durations) if durations else None,
        "extended_beyond_15_count": sum(d > 15 for d in durations),
        "exit_reasons": dict(
            sorted(Counter(str(r.get("exit_reason")) for r in valid).items())
        ),
        "positive_mfe_capture_ratio_mean": mean(capture) if capture else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--economics", required=True)
    ap.add_argument("--ohlc", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    economics = load_json(Path(args.economics))
    if economics.get("research_version") != EXPECTED_ECONOMICS_VERSION:
        raise SystemExit(
            f"unexpected economics version={economics.get('research_version')!r}"
        )

    if economics.get("candidate_count") != 17:
        raise SystemExit("expected 17 new-arm economics candidates")
    if (economics.get("arm_counts") or {}) != {
        "BASE_THEN_GO": 8,
        "FAILED_BREAK_RECLAIM": 9,
    }:
        raise SystemExit("unexpected V2 arm counts")
    if (economics.get("integrity") or {}).get("oos_h_used"):
        raise SystemExit("OOS-H forbidden")

    specs = [parse_block_path(v) for v in args.ohlc]
    expected_blocks = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
    if {b for b, _ in specs} != expected_blocks:
        raise SystemExit("need OHLC for TRAIN + OOS_A/B/C/D exactly")
    ohlc_by_block = {b: load_ohlc(p) for b, p in specs}

    source_rows = economics.get("rows") or []
    replays: list[dict[str, Any]] = []

    for trade in source_rows:
        if trade.get("entry_arm") not in {"BASE_THEN_GO", "FAILED_BREAK_RECLAIM"}:
            raise SystemExit("unexpected immediate-continuation row")
        block = str(trade["block"])
        series = ohlc_by_block[block].get(
            (str(trade["session_date"]), str(trade["instrument_key"])),
            {},
        )
        for policy_id in POLICIES:
            replays.append(replay_trade(trade, series, policy_id))

    policy_summaries = {}
    policy_arm_summaries = {}
    for policy_id in POLICIES:
        prs = [r for r in replays if r["policy_id"] == policy_id]
        policy_summaries[policy_id] = summarize(prs)
        policy_arm_summaries[policy_id] = {
            arm: summarize([r for r in prs if r["entry_arm"] == arm])
            for arm in ("BASE_THEN_GO", "FAILED_BREAK_RECLAIM")
        }

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_economics_version": EXPECTED_ECONOMICS_VERSION,
        "candidate_count": 17,
        "policies": POLICIES,
        "frozen_exit_parameters": {
            "initial_stop_pct": INITIAL_STOP_PCT,
            "breakeven_trigger_pct": BREAKEVEN_TRIGGER_PCT,
            "trail_activation_pct": TRAIL_ACTIVATION_PCT,
            "trail_distance_pct": TRAIL_DISTANCE_PCT,
            "breakeven_and_trailing_activate_next_bar": True,
            "gap_through_stop_exits_at_open": True,
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        },
        "policy_summaries": policy_summaries,
        "policy_arm_summaries": policy_arm_summaries,
        "rows": replays,
        "integrity": {
            "entry_logic_modified": False,
            "exact_contract_modified": False,
            "initial_stop_modified": False,
            "breakeven_rule_modified": False,
            "trail_activation_modified": False,
            "trail_distance_modified": False,
            "only_time_exit_rule_varied": True,
            "next_bar_activation_preserved": True,
            "gap_through_semantics_preserved": True,
            "oos_h_used": False,
            "immediate_continuation_included": False,
        },
        "governance": {
            "development_research_only": True,
            "comparison_is_descriptive_not_promotion": True,
            "no_policy_selected_automatically": True,
            "paper_or_live_order_emission_allowed": False,
            "fresh_oos_required_before_any_v2_promotion": True,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
