from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "CANONICAL_90_NINE_LEG_FIXED10_TRAIL3_SL5_V1"
POLICY_ID = "SL5_TRAIL3_AFTER_PLUS10PTS_TIME15"

INITIAL_STOP_PCT = 5.0
TRAIL_ARM_POINTS = 10.0
TRAIL_DISTANCE_POINTS = 3.0
MAX_HOLD_MINUTES = 15
ROUND_TRIP_COST_PCT_POINTS = 0.5

DEFAULT_COVERAGE = Path(
    "data/historical-evidence/canonical-90-nine-leg-option-coverage-v1.json"
)
DEFAULT_EVIDENCE_ROOT = Path("data/historical-evidence")
DEFAULT_OUTPUT_JSON = Path(
    "data/historical-evidence/canonical-90-nine-leg-fixed10-trail3-sl5-v1.json"
)
DEFAULT_OUTPUT_CSV = Path(
    "data/historical-evidence/canonical-90-nine-leg-fixed10-trail3-sl5-v1.csv"
)

LEG_ORDER = ("ITM4","ITM3","ITM2","ITM1","ATM","OTM1","OTM2","OTM3","OTM4")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_minute(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).isoformat()


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [r for r in rows if r.get("available") is True]
    vals = [float(r["net_return_pct"]) for r in available]
    winners = [v for v in vals if v > 0]
    losers = [v for v in vals if v <= 0]

    return {
        "candidate_count": len(rows),
        "available_count": len(available),
        "unavailable_count": len(rows) - len(available),
        "winner_count": len(winners),
        "loser_or_flat_count": len(losers),
        "win_rate_pct": (100.0 * len(winners) / len(vals)) if vals else None,
        "mean_net_pct": statistics.fmean(vals) if vals else None,
        "median_net_pct": statistics.median(vals) if vals else None,
        "sum_net_pct_points": sum(vals) if vals else None,
        "profit_factor": _profit_factor(vals),
        "average_winner_pct": statistics.fmean(winners) if winners else None,
        "average_loser_pct": statistics.fmean(losers) if losers else None,
        "best_trade_pct": max(vals) if vals else None,
        "worst_trade_pct": min(vals) if vals else None,
        "exit_reason_counts": dict(Counter(r.get("exit_reason") for r in available)),
        "trail_armed_count": sum(r.get("trail_armed") is True for r in available),
    }


def load_coverage(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc.get("legs"), list):
        raise ValueError("nine-leg coverage artifact missing top-level legs list")
    return doc


def _option_file_for_block(root: Path, block: str) -> Path:
    if block == "TRAIN":
        p = root / "option-ohlc-train.csv"
    else:
        suffix = block.lower().replace("_", "-")
        p = root / f"option-ohlc-{suffix}.csv"
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(f"option OHLC file missing/empty for {block}: {p}")
    return p


def load_needed_ohlc(
    ready_legs: list[dict[str, Any]],
    evidence_root: str | Path,
) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    root = Path(evidence_root)
    need: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for leg in ready_legs:
        block = str(leg["block"])
        instrument = str(leg["instrument_key"])
        start = _dt(leg["entry_timestamp"])
        for minute in range(1, MAX_HOLD_MINUTES + 1):
            need[block][instrument].add(
                _iso_minute(start + timedelta(minutes=minute))
            )

    out: dict[str, dict[str, dict[str, dict[str, str]]]] = {}

    for block, by_instrument in sorted(need.items()):
        p = _option_file_for_block(root, block)
        block_idx: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            required = {
                "session_date","instrument_key","timestamp","open","high","low","close"
            }
            missing = required - set(rd.fieldnames or [])
            if missing:
                raise ValueError(f"{p}: missing columns {sorted(missing)}")

            for raw in rd:
                instrument = str(raw.get("instrument_key") or "")
                wanted = by_instrument.get(instrument)
                if not wanted:
                    continue
                ts = str(raw.get("timestamp") or "")
                if ts in wanted:
                    block_idx[instrument][ts] = raw

        out[block] = dict(block_idx)

    return out


def replay_fixed_points_policy(
    *,
    entry_timestamp: str,
    entry_price: float,
    instrument_key: str,
    bars_by_instrument: dict[str, dict[str, dict[str, str]]],
) -> dict[str, Any] | None:
    if entry_price <= 0:
        return None

    bars = bars_by_instrument.get(instrument_key, {})
    entry_dt = _dt(entry_timestamp)

    initial_stop = entry_price * (1.0 - INITIAL_STOP_PCT / 100.0)
    active_stop = initial_stop
    best_price = entry_price
    trail_armed = False
    trail_arm_timestamp = None
    exit_timestamp = None
    exit_price = None
    exit_reason = None
    bars_seen = 0

    for minute in range(1, MAX_HOLD_MINUTES + 1):
        ts = _iso_minute(entry_dt + timedelta(minutes=minute))
        raw = bars.get(ts)
        if raw is None:
            return None

        o = _float(raw.get("open"))
        h = _float(raw.get("high"))
        l = _float(raw.get("low"))
        c = _float(raw.get("close"))
        if None in (o, h, l, c):
            return None
        if min(o, h, l, c) <= 0 or h < max(o, l, c) or l > min(o, h, c):
            return None

        bars_seen += 1

        # Current active stop is evaluated before using current-bar high.
        if o <= active_stop:
            exit_timestamp = ts
            exit_price = o
            exit_reason = "STOP_GAP"
            break

        if l <= active_stop:
            exit_timestamp = ts
            exit_price = active_stop
            exit_reason = "STOP_TOUCH"
            break

        # Current-bar high may arm/ratchet the trail, but that updated stop
        # is active from the NEXT 1-minute bar only.
        if h > best_price:
            best_price = h

        if not trail_armed and best_price >= entry_price + TRAIL_ARM_POINTS:
            trail_armed = True
            trail_arm_timestamp = ts

        next_stop = active_stop
        if trail_armed:
            next_stop = max(initial_stop, best_price - TRAIL_DISTANCE_POINTS)

        active_stop = next_stop

        if minute == MAX_HOLD_MINUTES:
            exit_timestamp = ts
            exit_price = c
            exit_reason = "TIME_EXIT"
            break

    if exit_price is None or exit_timestamp is None or exit_reason is None:
        return None

    gross = ((exit_price / entry_price) - 1.0) * 100.0
    net = gross - ROUND_TRIP_COST_PCT_POINTS

    return {
        "policy_id": POLICY_ID,
        "available": True,
        "issue": None,
        "entry_price": entry_price,
        "initial_stop_price": initial_stop,
        "trail_arm_points": TRAIL_ARM_POINTS,
        "trail_distance_points": TRAIL_DISTANCE_POINTS,
        "trail_armed": trail_armed,
        "trail_arm_timestamp": trail_arm_timestamp,
        "best_price_seen": best_price,
        "final_active_stop_price": active_stop,
        "exit_timestamp": exit_timestamp,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_return_pct": gross,
        "net_return_pct": net,
        "bars_seen": bars_seen,
    }


def replay_ready_legs(
    legs: list[dict[str, Any]],
    idx_by_block: dict[str, dict[str, dict[str, dict[str, str]]]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for src in legs:
        if src.get("coverage_status") != "READY":
            continue

        block = str(src["block"])
        replay = replay_fixed_points_policy(
            entry_timestamp=str(src["entry_timestamp"]),
            entry_price=float(src["entry_open"]),
            instrument_key=str(src["instrument_key"]),
            bars_by_instrument=idx_by_block.get(block, {}),
        )

        base = {
            "event_id": src["event_id"],
            "session_date": src["session_date"],
            "block": block,
            "direction": src["direction"],
            "leg": src["leg"],
            "strike_offset": int(src["strike_offset"]),
            "c1_timestamp": src.get("c1_timestamp"),
            "c2_timestamp": src.get("c2_expected_timestamp"),
            "option_side": src["option_side"],
            "moving_atm": src.get("moving_atm"),
            "strike": src["strike"],
            "instrument_key": src["instrument_key"],
            "entry_timestamp": src["entry_timestamp"],
            "entry_open": src["entry_open"],
            "coverage_status": src["coverage_status"],
        }

        if replay is None:
            base.update({
                "policy_id": POLICY_ID,
                "available": False,
                "issue": "REPLAY_FAILED_OR_INCOMPLETE_PATH",
            })
        else:
            base.update(replay)

        results.append(base)

    results.sort(
        key=lambda r: (
            r["session_date"],
            r["entry_timestamp"],
            str(r["event_id"]),
            LEG_ORDER.index(r["leg"]),
        )
    )
    return results


def _common_complete_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_event[str(row["event_id"])].append(row)

    complete_ids = {
        event_id
        for event_id, group in by_event.items()
        if len(group) == 9
        and {r["leg"] for r in group} == set(LEG_ORDER)
        and all(r.get("available") is True for r in group)
    }
    return [r for r in rows if str(r["event_id"]) in complete_ids]


def write_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "event_id","session_date","block","direction","leg","strike_offset",
        "c1_timestamp","c2_timestamp","option_side","moving_atm","strike",
        "instrument_key","entry_timestamp","entry_open","policy_id","available","issue",
        "entry_price","initial_stop_price","trail_arm_points","trail_distance_points",
        "trail_armed","trail_arm_timestamp","best_price_seen","final_active_stop_price",
        "exit_timestamp","exit_price","exit_reason","gross_return_pct","net_return_pct",
        "bars_seen",
    ]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run(
    *,
    coverage_path: str | Path = DEFAULT_COVERAGE,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_csv: str | Path = DEFAULT_OUTPUT_CSV,
) -> dict[str, Any]:
    coverage = load_coverage(coverage_path)
    ready = [r for r in coverage["legs"] if r.get("coverage_status") == "READY"]
    censored = [
        r for r in coverage["legs"]
        if r.get("coverage_status") == "SESSION_END_CENSORED"
    ]

    idx = load_needed_ohlc(ready, evidence_root)
    trades = replay_ready_legs(ready, idx)
    common = _common_complete_event_rows(trades)
    common_signal_count = len({str(r["event_id"]) for r in common}) if common else 0

    result = {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_EXIT_POLICY_EXPERIMENT_ON_EXPOSED_CANONICAL_90_POPULATION",
        "strategy_logic_changed": False,
        "entry_logic_changed": False,
        "strike_selection_changed": False,
        "exit_policy_changed_for_this_experiment": True,
        "threshold_optimization": False,
        "signal_count": coverage.get("signal_count"),
        "expected_leg_count": coverage.get("expected_leg_count"),
        "replayable_ready_leg_count": len(ready),
        "session_end_censored_leg_count": len(censored),
        "replayed_leg_count": len(trades),
        "complete_nine_leg_signal_count": common_signal_count,
        "policy_id": POLICY_ID,
        "policy": {
            "initial_stop_pct": INITIAL_STOP_PCT,
            "trail_arm_points": TRAIL_ARM_POINTS,
            "trail_distance_points": TRAIL_DISTANCE_POINTS,
            "breakeven": "OFF",
            "trail_activation": "NEXT_BAR_ONLY",
            "max_hold_minutes": MAX_HOLD_MINUTES,
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        },
        "execution_semantics": {
            "entry": "EXACT_NEXT_MINUTE_OPEN_AFTER_C2",
            "nearest_strike_fallback": False,
            "nearest_time_fallback": False,
            "stop_resolution": "OPEN_GAP_THEN_LOW_TOUCH",
            "trail_update": "CURRENT_BAR_HIGH_OBSERVED_ONLY_AFTER_STOP_CHECK; NEW_STOP_ACTIVE_NEXT_BAR",
            "time_exit": "EXACT_ENTRY_PLUS_15_MINUTE_CLOSE",
        },
        "summary_all_legs": _summary(trades),
        "by_leg": {
            leg: _summary([r for r in trades if r["leg"] == leg])
            for leg in LEG_ORDER
        },
        "by_direction_all_legs": {
            d: _summary([r for r in trades if r["direction"] == d])
            for d in ("BULLISH","BEARISH")
        },
        "common_complete_signal_comparison": {
            "signal_count": common_signal_count,
            "leg_count": len(common),
            "by_leg": {
                leg: _summary([r for r in common if r["leg"] == leg])
                for leg in LEG_ORDER
            },
            "note": "Comparison uses only signals where all nine legs replay successfully.",
        },
        "trades": trades,
        "governance": {
            "population_is_fresh_oos": False,
            "population_previously_exposed": True,
            "result_is_strategy_validation": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(trades, output_csv)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", default=str(DEFAULT_COVERAGE))
    ap.add_argument("--evidence-root", default=str(DEFAULT_EVIDENCE_ROOT))
    ap.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    ap.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    args = ap.parse_args()

    r = run(
        coverage_path=args.coverage,
        evidence_root=args.evidence_root,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )

    print(json.dumps({
        "status": r["status"],
        "model": r["model"],
        "signal_count": r["signal_count"],
        "expected_leg_count": r["expected_leg_count"],
        "replayable_ready_leg_count": r["replayable_ready_leg_count"],
        "session_end_censored_leg_count": r["session_end_censored_leg_count"],
        "replayed_leg_count": r["replayed_leg_count"],
        "complete_nine_leg_signal_count": r["complete_nine_leg_signal_count"],
        "policy_id": r["policy_id"],
        "policy": r["policy"],
        "summary_all_legs": r["summary_all_legs"],
        "by_leg": r["by_leg"],
        "common_complete_signal_comparison": r["common_complete_signal_comparison"],
        "output_json": args.output_json,
        "output_csv": args.output_csv,
    }, indent=2))


if __name__ == "__main__":
    main()
