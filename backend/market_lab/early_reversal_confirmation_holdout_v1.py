from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

MODEL = "EARLY_REVERSAL_CONFIRMATION_HOLDOUT_V1"
HORIZONS = ("5m", "10m", "15m")
BULL = "BULLISH_ALL_3"
BEAR = "BEARISH_ALL_3"
DIRS = {BULL, BEAR}


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _all3(hrows):
    states = [hrows.get(h, {}).get("existing_horizon_state") for h in HORIZONS]
    if any(s in (None, "", "NA") for s in states):
        return "INCOMPLETE"
    if all(s == "BULLISH" for s in states):
        return BULL
    if all(s == "BEARISH" for s in states):
        return BEAR
    return "MIXED"


def load_states(path):
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    grouped = {}
    for r in rows:
        grouped.setdefault((r["session_date"], r["timestamp"]), {})[r["horizon"]] = r
    by = defaultdict(list)
    for (d, ts), hrows in grouped.items():
        by[d].append({"timestamp": ts, "state": _all3(hrows)})
    for d in by:
        by[d].sort(key=lambda x: x["timestamp"])
    return dict(by)


def load_audits(paths):
    out = {}
    for p in paths:
        data = json.loads(Path(p).read_text())
        out[data["session_date"]] = {r["timestamp"]: r for r in data.get("rows", [])}
    return out


def direction_name(state):
    return "BULLISH" if state == BULL else "BEARISH"


def contiguous_run_len(states, idx):
    st = states[idx]["state"]
    n = 0
    while idx + n < len(states) and states[idx + n]["state"] == st:
        n += 1
    return n


def futures_support(audit, target):
    v = audit.get("futures_oi_direction")
    if v in (None, "", "NA"):
        return None
    return str(v).upper() == direction_name(target)


def vwap_support(audit, target):
    v = audit.get("vwap_side")
    if v in (None, "", "NA"):
        return None
    desired = "ABOVE" if target == BULL else "BELOW"
    return str(v).upper() == desired


def signed_move(start, end, target):
    a, b = _num(start), _num(end)
    if a is None or b is None:
        return None
    return (b - a) if target == BULL else (a - b)


def pct_move(points, start):
    s = _num(start)
    if points is None or s in (None, 0):
        return None
    return points / s * 100.0


def event_rows(states_by_session, audits):
    events = []
    event_id = 0

    for d in sorted(states_by_session):
        states = states_by_session[d]
        i = 0
        while i < len(states):
            st = states[i]["state"]
            if st not in DIRS:
                i += 1
                continue
            if i > 0 and states[i - 1]["state"] == st:
                i += 1
                continue

            j = i - 1
            while j >= 0 and states[j]["state"] not in DIRS:
                j -= 1
            if j < 0 or states[j]["state"] == st:
                i += contiguous_run_len(states, i)
                continue

            final_len = contiguous_run_len(states, i)
            event_id += 1
            a1 = audits.get(d, {}).get(states[i]["timestamp"], {})
            has_c2 = final_len >= 2
            a2 = audits.get(d, {}).get(states[i+1]["timestamp"], {}) if has_c2 else {}

            f1 = futures_support(a1, st)
            v1 = vwap_support(a1, st)
            f2 = futures_support(a2, st) if has_c2 else None
            v2 = vwap_support(a2, st) if has_c2 else None

            c2_index = i + 1 if has_c2 else None
            c2_spot = a2.get("spot") if has_c2 else None

            # Future evaluation from candle 2 only; never used as a feature.
            future_points = {}
            for mins, step in ((5,1),(10,2),(15,3),(30,6)):
                idx = None if c2_index is None else c2_index + step
                fut_spot = None
                if idx is not None and idx < len(states):
                    fut_spot = audits.get(d, {}).get(states[idx]["timestamp"], {}).get("spot")
                pts = signed_move(c2_spot, fut_spot, st) if has_c2 else None
                future_points[f"signed_spot_move_plus_{mins}m"] = pts
                future_points[f"signed_spot_move_plus_{mins}m_pct"] = pct_move(pts, c2_spot)

            run_end_idx = i + final_len - 1
            run_end_audit = audits.get(d, {}).get(states[run_end_idx]["timestamp"], {})
            run_end_spot = run_end_audit.get("spot")
            run_end_points = signed_move(c2_spot, run_end_spot, st) if has_c2 else None

            mfe = mae = None
            if has_c2 and _num(c2_spot) is not None:
                path = []
                for k in range(c2_index, run_end_idx + 1):
                    s = audits.get(d, {}).get(states[k]["timestamp"], {}).get("spot")
                    mv = signed_move(c2_spot, s, st)
                    if mv is not None:
                        path.append(mv)
                if path:
                    mfe = max(path)
                    mae = min(path)

            maintained = None
            if has_c2 and f1 is not None and f2 is not None:
                maintained = bool(f1 and f2)
            flipped = None
            if has_c2 and f1 is not None and f2 is not None:
                flipped = (f1 is False and f2 is True)
            c2_joint = None
            if has_c2 and f2 is not None and v2 is not None:
                c2_joint = bool(f2 and v2)

            row = {
                "event_id": event_id,
                "session_date": d,
                "from_state": states[j]["state"],
                "to_state": st,
                "candle1_timestamp": states[i]["timestamp"],
                "candle2_timestamp": states[i+1]["timestamp"] if has_c2 else None,
                "final_run_length": final_len,
                "outcome_three_plus": final_len >= 3,
                "c1_futures_support": f1,
                "c1_vwap_support": v1,
                "has_candle2": has_c2,
                "c2_futures_support": f2,
                "c2_vwap_support": v2,
                "c2_futures_and_vwap_support": c2_joint,
                "futures_support_maintained_c1_c2": maintained,
                "futures_flipped_into_alignment_c2": flipped,
                "c2_spot": c2_spot,
                "remaining_all3_candles_after_c2": max(0, final_len - 2) if has_c2 else None,
                "run_end_timestamp": states[run_end_idx]["timestamp"],
                "run_end_spot": run_end_spot,
                "signed_spot_move_c2_to_run_end": run_end_points,
                "signed_spot_move_c2_to_run_end_pct": pct_move(run_end_points, c2_spot),
                "mfe_points_c2_to_run_end": mfe,
                "mae_points_c2_to_run_end": mae,
            }
            row.update(future_points)
            events.append(row)
            i += final_len
    return events


def rate(rows):
    if not rows:
        return None
    return sum(bool(r["outcome_three_plus"]) for r in rows) / len(rows)


def avg(rows, key):
    vals = [_num(r.get(key)) for r in rows]
    vals = [v for v in vals if v is not None]
    return None if not vals else mean(vals)


def med(rows, key):
    vals = [_num(r.get(key)) for r in rows]
    vals = [v for v in vals if v is not None]
    return None if not vals else median(vals)


def subset_summary(rows):
    return {
        "rows": len(rows),
        "three_plus_rate": rate(rows),
        "mean_remaining_all3_candles_after_c2": avg(rows, "remaining_all3_candles_after_c2"),
        "mean_signed_spot_move_c2_to_run_end": avg(rows, "signed_spot_move_c2_to_run_end"),
        "median_signed_spot_move_c2_to_run_end": med(rows, "signed_spot_move_c2_to_run_end"),
        "mean_signed_spot_move_plus_5m": avg(rows, "signed_spot_move_plus_5m"),
        "mean_signed_spot_move_plus_10m": avg(rows, "signed_spot_move_plus_10m"),
        "mean_signed_spot_move_plus_15m": avg(rows, "signed_spot_move_plus_15m"),
        "mean_signed_spot_move_plus_30m": avg(rows, "signed_spot_move_plus_30m"),
        "median_mfe_points_c2_to_run_end": med(rows, "mfe_points_c2_to_run_end"),
        "median_mae_points_c2_to_run_end": med(rows, "mae_points_c2_to_run_end"),
    }


def split(rows, key):
    yes = [r for r in rows if r.get(key) is True]
    no = [r for r in rows if r.get(key) is False]
    return {"true": subset_summary(yes), "false": subset_summary(no)}


def build_report(events):
    c2 = [e for e in events if e["has_candle2"]]
    return {
        "status": "PASS",
        "model": MODEL,
        "role": "HOLDOUT_VALIDATION_DESCRIPTIVE_ONLY",
        "strategy_logic_changed": False,
        "all3_state_definition_changed": False,
        "threshold_optimization": False,
        "research_question": (
            "Does the frozen candle-2 ALL3 + futures/VWAP confirmation structure generalize "
            "to holdout sessions, and is meaningful underlying movement still left after candle 2?"
        ),
        "frozen_features": [
            "opposite-direction ALL3 appears",
            "ALL3 survives to candle 2",
            "candle-2 futures OI direction support",
            "futures support maintained from candle 1 to candle 2",
            "futures flips into alignment on candle 2",
            "candle-2 VWAP support",
            "candle-2 futures + VWAP joint support",
        ],
        "evaluation_only": [
            "final run reaches 3+ candles",
            "remaining ALL3 candles after candle 2",
            "signed NIFTY spot movement after candle 2 at +5/+10/+15/+30m",
            "signed NIFTY spot movement from candle 2 to ALL3 run end",
            "MFE/MAE from candle 2 through ALL3 run end",
        ],
        "notes": [
            "Do not choose holdout dates based on these outcomes.",
            "Holdout rows must exclude the 54-session feature-development cohort.",
            "This measures underlying NIFTY movement, not option-premium PnL.",
            "No entry rule or minimum point threshold is created.",
        ],
        "event_count": len(events),
        "events_reaching_candle2": len(c2),
        "all_candle2_events": subset_summary(c2),
        "c2_futures_support": split(c2, "c2_futures_support"),
        "futures_support_maintained_c1_c2": split(c2, "futures_support_maintained_c1_c2"),
        "futures_flipped_into_alignment_c2": split(c2, "futures_flipped_into_alignment_c2"),
        "c2_vwap_support": split(c2, "c2_vwap_support"),
        "c2_futures_and_vwap_support": split(c2, "c2_futures_and_vwap_support"),
        "events": events,
    }


def write_csv(events, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        p.write_text("")
        return
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0].keys()))
        w.writeheader()
        w.writerows(events)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-csv", required=True)
    ap.add_argument("--audit-json", action="append", required=True)
    ap.add_argument("--events-csv", required=True)
    ap.add_argument("--summary-json", required=True)
    a = ap.parse_args(argv)

    states = load_states(a.rows_csv)
    audits = load_audits(a.audit_json)
    events = event_rows(states, audits)
    report = build_report(events)
    write_csv(events, a.events_csv)
    p = Path(a.summary_json)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
