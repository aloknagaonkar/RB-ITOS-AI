from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

MODEL = "CHANGE_PCR_PERSISTENT_DETERIORATION_V1"
HORIZONS = ("5m", "10m", "15m")
LOOKAHEAD_STEPS = (1, 2, 3)  # 5m / 10m / 15m


def _to_float(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out = dict(row)
            for key in (
                "spot", "moving_atm", "ce_delta", "pe_delta", "change_pcr",
                "oi_imbalance", "regular_pcr_change", "session_pcr_change"
            ):
                out[key] = _to_float(out.get(key))
            rows.append(out)
    return rows


def group_rows(rows: list[dict[str, Any]]):
    grouped = {}
    for row in rows:
        key = (row["session_date"], row["timestamp"])
        grouped.setdefault(key, {})[row["horizon"]] = row

    by_session = {}
    for (session, ts), hrows in grouped.items():
        by_session.setdefault(session, []).append((ts, hrows))

    for session in by_session:
        by_session[session].sort(key=lambda x: x[0])

    return by_session


def all3_state(hrows: dict[str, dict[str, Any]]) -> str:
    states = [hrows.get(h, {}).get("existing_horizon_state") for h in HORIZONS]
    if any(s in (None, "", "NA") for s in states):
        return "INCOMPLETE"
    if all(s == "BULLISH" for s in states):
        return "BULLISH_ALL_3"
    if all(s == "BEARISH" for s in states):
        return "BEARISH_ALL_3"
    return "MIXED"


def normalized_oi_dominance(ce_delta, pe_delta):
    if ce_delta is None or pe_delta is None:
        return None
    denom = abs(ce_delta) + abs(pe_delta)
    if denom == 0:
        return 0.0
    return (pe_delta - ce_delta) / denom


def opposite_direction(state: str) -> str | None:
    if state == "BULLISH_ALL_3":
        return "BEARISH"
    if state == "BEARISH_ALL_3":
        return "BULLISH"
    return None


def target_state(direction: str) -> str:
    return f"{direction}_ALL_3"


def directional_move(value_change: float | None, target: str) -> bool:
    if value_change is None:
        return False
    if target == "BULLISH":
        return value_change > 0
    if target == "BEARISH":
        return value_change < 0
    return False


def enrich_sessions(rows: list[dict[str, Any]]):
    grouped = group_rows(rows)
    out = {}

    for session, candles in grouped.items():
        enriched = []
        previous_dom = {h: None for h in HORIZONS}
        previous_cpcr = {h: None for h in HORIZONS}

        for idx, (ts, hrows) in enumerate(candles):
            candle = {
                "session_date": session,
                "timestamp": ts,
                "index": idx,
                "all3_state": all3_state(hrows),
                "hrows": hrows,
            }

            for h in HORIZONS:
                r = hrows.get(h, {})
                dom = normalized_oi_dominance(r.get("ce_delta"), r.get("pe_delta"))
                cpcr = r.get("change_pcr")

                candle[f"dominance_{h}"] = dom
                candle[f"change_pcr_{h}"] = cpcr
                candle[f"dominance_change_{h}"] = (
                    None
                    if dom is None or previous_dom[h] is None
                    else dom - previous_dom[h]
                )
                candle[f"change_pcr_change_{h}"] = (
                    None
                    if cpcr is None or previous_cpcr[h] is None
                    else cpcr - previous_cpcr[h]
                )

                previous_dom[h] = dom
                previous_cpcr[h] = cpcr

            enriched.append(candle)

        out[session] = enriched
    return out


def directional_run_length(candles, start_idx, state):
    if start_idx >= len(candles) or candles[start_idx]["all3_state"] != state:
        return 0
    j = start_idx
    while j < len(candles) and candles[j]["all3_state"] == state:
        j += 1
    return j - start_idx


def opposite_transition_within(candles, idx, target, max_steps=3):
    wanted = target_state(target)
    for step in range(1, max_steps + 1):
        j = idx + step
        if j >= len(candles):
            break
        if candles[j]["all3_state"] == wanted:
            run = directional_run_length(candles, j, wanted)
            return {
                "minutes": step * 5,
                "index": j,
                "state": wanted,
                "run_length": run,
                "run_bucket": "1" if run == 1 else "2" if run == 2 else "3+",
            }
    return None


def consecutive_deterioration(candles, idx, horizon, target, max_len=3):
    """Number of consecutive candles ending at idx whose dominance change moves toward target."""
    count = 0
    j = idx
    while j >= 0 and count < max_len:
        ch = candles[j].get(f"dominance_change_{horizon}")
        if directional_move(ch, target):
            count += 1
            j -= 1
        else:
            break
    return count


def propagation_pattern(candle, target):
    d5 = directional_move(candle.get("dominance_change_5m"), target)
    d10 = directional_move(candle.get("dominance_change_10m"), target)
    d15 = directional_move(candle.get("dominance_change_15m"), target)

    if d5 and d10 and d15:
        return "5M_10M_15M"
    if d5 and d10:
        return "5M_10M"
    if d5:
        return "5M_ONLY"
    return "NONE"


def build_candidates(table):
    candidates = []
    cid = 0

    for session, candles in table.items():
        for idx, candle in enumerate(candles):
            current = candle["all3_state"]
            target = opposite_direction(current)
            if target is None:
                continue

            d1 = consecutive_deterioration(candles, idx, "5m", target, 3)
            prop = propagation_pattern(candle, target)

            if d1 == 0 and prop == "NONE":
                continue

            cid += 1
            hit = opposite_transition_within(candles, idx, target, 3)

            candidates.append({
                "candidate_id": cid,
                "session_date": session,
                "timestamp": candle["timestamp"],
                "current_all3_state": current,
                "target_direction": target,
                "one_step": d1 >= 1,
                "two_step": d1 >= 2,
                "three_step": d1 >= 3,
                "consecutive_deterioration_5m": d1,
                "propagation": prop,
                "dominance_5m": candle.get("dominance_5m"),
                "dominance_change_5m": candle.get("dominance_change_5m"),
                "dominance_10m": candle.get("dominance_10m"),
                "dominance_change_10m": candle.get("dominance_change_10m"),
                "dominance_15m": candle.get("dominance_15m"),
                "dominance_change_15m": candle.get("dominance_change_15m"),
                "change_pcr_5m": candle.get("change_pcr_5m"),
                "change_pcr_change_5m": candle.get("change_pcr_change_5m"),
                "transition_within_5m": hit is not None and hit["minutes"] == 5,
                "transition_within_10m": hit is not None and hit["minutes"] <= 10,
                "transition_within_15m": hit is not None and hit["minutes"] <= 15,
                "first_transition_minutes": None if hit is None else hit["minutes"],
                "resulting_run_length": None if hit is None else hit["run_length"],
                "resulting_run_bucket": None if hit is None else hit["run_bucket"],
                "persistent_3plus_hit_15m": (
                    hit is not None and hit["minutes"] <= 15 and hit["run_length"] >= 3
                ),
                "false_warning_15m": hit is None,
            })

    return candidates


def _rate(n, d):
    return None if d == 0 else n / d


def summarize_bucket(rows):
    n = len(rows)
    h5 = sum(1 for r in rows if r["transition_within_5m"])
    h10 = sum(1 for r in rows if r["transition_within_10m"])
    h15 = sum(1 for r in rows if r["transition_within_15m"])
    p3 = sum(1 for r in rows if r["persistent_3plus_hit_15m"])
    false = sum(1 for r in rows if r["false_warning_15m"])
    return {
        "candidates": n,
        "hits_5m": h5,
        "hits_10m": h10,
        "hits_15m": h15,
        "precision_5m": _rate(h5, n),
        "precision_10m": _rate(h10, n),
        "precision_15m": _rate(h15, n),
        "persistent_3plus_hits_15m": p3,
        "persistent_3plus_precision_15m": _rate(p3, n),
        "false_15m": false,
        "false_warning_rate_15m": _rate(false, n),
    }


def summary(candidates):
    buckets = {
        "ONE_STEP": [r for r in candidates if r["one_step"]],
        "TWO_STEP": [r for r in candidates if r["two_step"]],
        "THREE_STEP": [r for r in candidates if r["three_step"]],
        "PROP_5M_ONLY": [r for r in candidates if r["propagation"] == "5M_ONLY"],
        "PROP_5M_10M": [r for r in candidates if r["propagation"] == "5M_10M"],
        "PROP_5M_10M_15M": [r for r in candidates if r["propagation"] == "5M_10M_15M"],
    }

    return {
        "status": "PASS",
        "model": MODEL,
        "definition": {
            "deterioration": "normalized OI dominance moves toward the direction opposite the current all-3 state",
            "normalized_oi_dominance": "(PE_delta - CE_delta)/(abs(PE_delta)+abs(CE_delta))",
            "persistence": "1/2/3 consecutive 5m deterioration candles ending at candidate candle",
            "propagation": "same-direction deterioration concurrently visible across 5m/10m/15m",
            "lookahead_minutes": [5, 10, 15],
            "persistent_outcome": "opposite all-3 transition with resulting run length >= 3 candles",
            "strategy_logic_changed": False,
            "numeric_threshold_optimization": False,
        },
        "candidate_count": len(candidates),
        "overall": summarize_bucket(candidates),
        "by_pattern": {name: summarize_bucket(rows) for name, rows in buckets.items()},
    }


def write_csv(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Persistent Change-PCR/normalized-dominance deterioration research study."
    )
    p.add_argument("--rows-csv", required=True)
    p.add_argument("--candidates-csv", required=True)
    p.add_argument("--summary-json", required=True)
    args = p.parse_args(argv)

    rows = load_rows(Path(args.rows_csv))
    table = enrich_sessions(rows)
    candidates = build_candidates(table)
    out = summary(candidates)

    write_csv(candidates, Path(args.candidates_csv))
    sp = Path(args.summary_json)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(out, indent=2) + "\n")

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
