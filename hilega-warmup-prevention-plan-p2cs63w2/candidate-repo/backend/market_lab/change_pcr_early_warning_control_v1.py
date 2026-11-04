from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

MODEL = "CHANGE_PCR_EARLY_WARNING_CONTROL_V1"
HORIZONS = ("5m", "10m", "15m")
LOOKAHEAD_STEPS = (1, 2, 3)  # 5m, 10m, 15m


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


def mechanics_direction(mech: str | None) -> str:
    if mech in {
        "CE_UNWIND_PE_BUILD",
        "BOTH_BUILD_PE_DOMINANT",
        "BOTH_UNWIND_CE_DOMINANT",
    }:
        return "BULLISH"
    if mech in {
        "CE_BUILD_PE_UNWIND",
        "BOTH_BUILD_CE_DOMINANT",
        "BOTH_UNWIND_PE_DOMINANT",
    }:
        return "BEARISH"
    return "NEUTRAL"


def directional_target(state: str) -> str | None:
    if state == "BULLISH_ALL_3":
        return "BEARISH"
    if state == "BEARISH_ALL_3":
        return "BULLISH"
    return None


def transition_target_state(direction: str) -> str:
    return f"{direction}_ALL_3"


def build_candle_table(rows: list[dict[str, Any]]):
    by_session = group_rows(rows)
    table = {}

    for session, candles in by_session.items():
        enriched = []
        prev_dom_5 = None
        prev_cpcr_5 = None

        for idx, (ts, hrows) in enumerate(candles):
            state = all3_state(hrows)
            r5 = hrows.get("5m", {})
            dom5 = normalized_oi_dominance(r5.get("ce_delta"), r5.get("pe_delta"))
            cpcr5 = r5.get("change_pcr")

            dom5_change = None if dom5 is None or prev_dom_5 is None else dom5 - prev_dom_5
            cpcr5_change = None if cpcr5 is None or prev_cpcr_5 is None else cpcr5 - prev_cpcr_5

            enriched.append({
                "session_date": session,
                "timestamp": ts,
                "index": idx,
                "all3_state": state,
                "hrows": hrows,
                "normalized_dominance_5m": dom5,
                "normalized_dominance_change_5m": dom5_change,
                "change_pcr_5m": cpcr5,
                "change_pcr_change_5m": cpcr5_change,
                "mechanics_direction_5m": mechanics_direction(r5.get("change_pcr_mechanics")),
            })

            prev_dom_5 = dom5
            prev_cpcr_5 = cpcr5

        table[session] = enriched

    return table


def directional_runs(candles: list[dict[str, Any]]):
    runs = []
    i = 0
    while i < len(candles):
        state = candles[i]["all3_state"]
        if state not in ("BULLISH_ALL_3", "BEARISH_ALL_3"):
            i += 1
            continue

        start = i
        j = i + 1
        while j < len(candles) and candles[j]["all3_state"] == state:
            j += 1
        runs.append({
            "state": state,
            "start_index": start,
            "end_index": j - 1,
            "length": j - start,
            "start_timestamp": candles[start]["timestamp"],
            "end_timestamp": candles[j - 1]["timestamp"],
        })
        i = j
    return runs


def detect_transitions_with_persistence(table):
    events = []
    event_id = 0

    for session, candles in table.items():
        runs = directional_runs(candles)
        for prev_run, next_run in zip(runs, runs[1:]):
            if prev_run["state"] == next_run["state"]:
                continue

            # Ignore intervening mixed/incomplete gap length for state direction,
            # but transition occurs at next directional run start.
            event_id += 1
            events.append({
                "event_id": event_id,
                "session_date": session,
                "from_state": prev_run["state"],
                "to_state": next_run["state"],
                "transition_timestamp": next_run["start_timestamp"],
                "transition_index": next_run["start_index"],
                "resulting_run_length": next_run["length"],
                "resulting_run_bucket": (
                    "1" if next_run["length"] == 1
                    else "2" if next_run["length"] == 2
                    else "3+"
                ),
            })
    return events


def candidate_warning(candle: dict[str, Any]) -> dict[str, Any] | None:
    current_state = candle["all3_state"]
    target = directional_target(current_state)
    if target is None:
        return None

    hrows = candle["hrows"]
    r5 = hrows.get("5m", {})
    mech_dir = candle["mechanics_direction_5m"]
    dom = candle["normalized_dominance_5m"]
    dom_change = candle["normalized_dominance_change_5m"]
    cpcr_change = candle["change_pcr_change_5m"]

    # V1 warning logic is descriptive and intentionally conservative:
    # warn if either:
    # A) 5m mechanics already point opposite the current all-3 state, OR
    # B) normalized 5m dominance is moving in the opposite direction vs prior candle.
    # No optimized numeric threshold beyond sign.
    mech_support = mech_dir == target

    dominance_support = False
    if dom_change is not None:
        if target == "BULLISH" and dom_change > 0:
            dominance_support = True
        elif target == "BEARISH" and dom_change < 0:
            dominance_support = True

    if not (mech_support or dominance_support):
        return None

    return {
        "target_direction": target,
        "target_state": transition_target_state(target),
        "warning_type": (
            "MECHANICS_AND_DOMINANCE"
            if mech_support and dominance_support
            else "MECHANICS"
            if mech_support
            else "DOMINANCE_DETERIORATION"
        ),
        "mechanics_support": mech_support,
        "dominance_support": dominance_support,
        "mechanics_direction_5m": mech_dir,
        "normalized_dominance_5m": dom,
        "normalized_dominance_change_5m": dom_change,
        "change_pcr_5m": candle["change_pcr_5m"],
        "change_pcr_change_5m": cpcr_change,
        "delta_pattern_5m": r5.get("delta_pattern"),
        "change_pcr_mechanics_5m": r5.get("change_pcr_mechanics"),
        "oi_imbalance_5m": r5.get("oi_imbalance"),
        "regular_pcr_change_5m": r5.get("regular_pcr_change"),
        "futures_oi_direction": r5.get("futures_oi_direction"),
        "vwap_side": r5.get("vwap_side"),
    }


def evaluate_warnings(table):
    rows = []
    warning_id = 0

    for session, candles in table.items():
        for i, candle in enumerate(candles):
            warning = candidate_warning(candle)
            if not warning:
                continue

            warning_id += 1
            hit_minutes = None
            hit_state = None
            resulting_run_length = None

            for step in LOOKAHEAD_STEPS:
                j = i + step
                if j >= len(candles):
                    continue
                future_state = candles[j]["all3_state"]
                if future_state == warning["target_state"]:
                    hit_minutes = step * 5
                    hit_state = future_state
                    # determine immediate run length from hit point
                    k = j
                    while k < len(candles) and candles[k]["all3_state"] == future_state:
                        k += 1
                    resulting_run_length = k - j
                    break

            rows.append({
                "warning_id": warning_id,
                "session_date": session,
                "timestamp": candle["timestamp"],
                "current_all3_state": candle["all3_state"],
                **warning,
                "transition_within_5m": hit_minutes == 5,
                "transition_within_10m": hit_minutes in (5, 10),
                "transition_within_15m": hit_minutes in (5, 10, 15),
                "first_transition_minutes": hit_minutes,
                "hit_state": hit_state,
                "resulting_run_length_from_hit": resulting_run_length,
                "resulting_run_bucket_from_hit": (
                    None
                    if resulting_run_length is None
                    else "1"
                    if resulting_run_length == 1
                    else "2"
                    if resulting_run_length == 2
                    else "3+"
                ),
                "false_warning_15m": hit_minutes is None,
            })
    return rows


def summary(events, warnings):
    transition_count = len(events)
    persistent_events = [e for e in events if e["resulting_run_length"] >= 3]
    whipsaw_events = [e for e in events if e["resulting_run_length"] == 1]

    warning_count = len(warnings)
    hits5 = sum(1 for w in warnings if w["transition_within_5m"])
    hits10 = sum(1 for w in warnings if w["transition_within_10m"])
    hits15 = sum(1 for w in warnings if w["transition_within_15m"])
    false15 = sum(1 for w in warnings if w["false_warning_15m"])
    persistent_hits15 = sum(
        1 for w in warnings
        if w["transition_within_15m"]
        and (w["resulting_run_length_from_hit"] or 0) >= 3
    )

    def rate(n, d):
        return None if d == 0 else n / d

    by_type = {}
    for w in warnings:
        t = w["warning_type"]
        b = by_type.setdefault(t, {"warnings": 0, "hits_15m": 0, "false_15m": 0})
        b["warnings"] += 1
        if w["transition_within_15m"]:
            b["hits_15m"] += 1
        if w["false_warning_15m"]:
            b["false_15m"] += 1

    for b in by_type.values():
        b["precision_15m"] = rate(b["hits_15m"], b["warnings"])
        b["false_warning_rate_15m"] = rate(b["false_15m"], b["warnings"])

    return {
        "status": "PASS",
        "model": MODEL,
        "definition": {
            "warning": (
                "while current all-3 is directional, opposite 5m mechanics OR "
                "opposite-signed change in normalized 5m OI dominance"
            ),
            "normalized_oi_dominance": "(PE_delta - CE_delta) / (abs(PE_delta)+abs(CE_delta))",
            "lookahead_minutes": [5, 10, 15],
            "strategy_logic_changed": False,
            "threshold_optimization": False,
        },
        "transition_count": transition_count,
        "transition_resulting_run_buckets": {
            "1": sum(1 for e in events if e["resulting_run_bucket"] == "1"),
            "2": sum(1 for e in events if e["resulting_run_bucket"] == "2"),
            "3+": sum(1 for e in events if e["resulting_run_bucket"] == "3+"),
        },
        "persistent_transition_count_3plus": len(persistent_events),
        "one_candle_whipsaw_transition_count": len(whipsaw_events),
        "warning_count": warning_count,
        "warnings_followed_by_transition_5m": hits5,
        "warnings_followed_by_transition_10m": hits10,
        "warnings_followed_by_transition_15m": hits15,
        "warning_precision_5m": rate(hits5, warning_count),
        "warning_precision_10m": rate(hits10, warning_count),
        "warning_precision_15m": rate(hits15, warning_count),
        "false_warning_count_15m": false15,
        "false_warning_rate_15m": rate(false15, warning_count),
        "warnings_followed_by_persistent_3plus_transition_15m": persistent_hits15,
        "persistent_transition_precision_15m": rate(persistent_hits15, warning_count),
        "by_warning_type": by_type,
    }


def write_csv(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Control study for Change-PCR early warnings and false-warning rate."
    )
    p.add_argument("--rows-csv", required=True)
    p.add_argument("--transitions-csv", required=True)
    p.add_argument("--warnings-csv", required=True)
    p.add_argument("--summary-json", required=True)
    args = p.parse_args(argv)

    rows = load_rows(Path(args.rows_csv))
    table = build_candle_table(rows)
    events = detect_transitions_with_persistence(table)
    warnings = evaluate_warnings(table)
    out = summary(events, warnings)

    write_csv(events, Path(args.transitions_csv))
    write_csv(warnings, Path(args.warnings_csv))
    sp = Path(args.summary_json)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(out, indent=2) + "\n")

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
