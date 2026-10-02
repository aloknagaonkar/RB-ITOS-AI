from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

MODEL = "EARLY_REVERSAL_CONFIRMATION_V2"
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
    by_session = defaultdict(list)
    for (d, ts), hrows in grouped.items():
        by_session[d].append({"timestamp": ts, "state": _all3(hrows)})
    for d in by_session:
        by_session[d].sort(key=lambda x: x["timestamp"])
    return dict(by_session)


def load_audits(paths):
    out = {}
    for p in paths:
        data = json.loads(Path(p).read_text())
        out[data["session_date"]] = {r["timestamp"]: r for r in data.get("rows", [])}
    return out


def contiguous_run_len(states, idx):
    st = states[idx]["state"]
    n = 0
    while idx + n < len(states) and states[idx + n]["state"] == st:
        n += 1
    return n


def direction_name(state):
    return "BULLISH" if state == BULL else "BEARISH"


def futures_support(audit, target):
    v = audit.get("futures_oi_direction")
    if v in (None, "", "NA"):
        return None
    return str(v).upper() == direction_name(target)


def futures_streak(audit, target):
    key = "bullish_oi_status_streak" if target == BULL else "bearish_oi_status_streak"
    return _num(audit.get(key))


def vwap_support(audit, target):
    v = audit.get("vwap_side")
    if v in (None, "", "NA"):
        return None
    desired = "ABOVE" if target == BULL else "BELOW"
    return str(v).upper() == desired


def session_context_support(audit, target):
    imb = _num(audit.get("session_imbalance"))
    pcr = _num(audit.get("session_pcr_change_0920_to_now"))
    if imb is None or pcr is None or imb == 0 or pcr == 0:
        return None
    if target == BULL:
        a, b = imb > 0, pcr > 0
    else:
        a, b = imb < 0, pcr < 0
    if a and b:
        return True
    if (not a) and (not b):
        return False
    return None


def build_events(states_by_session, audits):
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

            # Start only at beginning of a directional run.
            if i > 0 and states[i - 1]["state"] == st:
                i += 1
                continue

            # Find most recent prior directional state.
            j = i - 1
            while j >= 0 and states[j]["state"] not in DIRS:
                j -= 1
            if j < 0 or states[j]["state"] == st:
                i += contiguous_run_len(states, i)
                continue

            event_id += 1
            final_len = contiguous_run_len(states, i)
            a1 = audits.get(d, {}).get(states[i]["timestamp"], {})

            has_c2 = final_len >= 2
            a2 = audits.get(d, {}).get(states[i+1]["timestamp"], {}) if has_c2 else {}

            f1 = futures_support(a1, st)
            f2 = futures_support(a2, st) if has_c2 else None
            fs1 = futures_streak(a1, st)
            fs2 = futures_streak(a2, st) if has_c2 else None
            vw1 = vwap_support(a1, st)
            vw2 = vwap_support(a2, st) if has_c2 else None

            streak_strengthened = None
            if has_c2 and fs1 is not None and fs2 is not None:
                streak_strengthened = fs2 > fs1

            futures_maintained = None
            if has_c2 and f1 is not None and f2 is not None:
                futures_maintained = bool(f1 and f2)

            futures_flipped_into_alignment = None
            if has_c2 and f1 is not None and f2 is not None:
                futures_flipped_into_alignment = (f1 is False and f2 is True)

            vwap_maintained = None
            if has_c2 and vw1 is not None and vw2 is not None:
                vwap_maintained = bool(vw1 and vw2)

            vwap_crossed_into_alignment = None
            if has_c2 and vw1 is not None and vw2 is not None:
                vwap_crossed_into_alignment = (vw1 is False and vw2 is True)

            c1_both = None if f1 is None or vw1 is None else bool(f1 and vw1)
            c2_both = None if not has_c2 or f2 is None or vw2 is None else bool(f2 and vw2)

            events.append({
                "event_id": event_id,
                "session_date": d,
                "from_state": states[j]["state"],
                "to_state": st,
                "candle1_timestamp": states[i]["timestamp"],
                "candle2_timestamp": states[i+1]["timestamp"] if has_c2 else None,
                "gap_candles": i - j - 1,
                "final_run_length": final_len,
                "outcome_three_plus": final_len >= 3,

                "c1_futures_direction": a1.get("futures_oi_direction"),
                "c1_futures_status": a1.get("futures_oi_status"),
                "c1_futures_support": f1,
                "c1_target_futures_streak": fs1,
                "c1_vwap_side": a1.get("vwap_side"),
                "c1_vwap_support": vw1,
                "c1_futures_and_vwap_support": c1_both,
                "c1_session_context_support": session_context_support(a1, st),

                "has_candle2": has_c2,
                "c2_futures_direction": a2.get("futures_oi_direction") if has_c2 else None,
                "c2_futures_status": a2.get("futures_oi_status") if has_c2 else None,
                "c2_futures_support": f2,
                "c2_target_futures_streak": fs2,
                "c2_vwap_side": a2.get("vwap_side") if has_c2 else None,
                "c2_vwap_support": vw2,
                "c2_futures_and_vwap_support": c2_both,
                "c2_session_context_support": session_context_support(a2, st) if has_c2 else None,

                "futures_support_maintained_c1_c2": futures_maintained,
                "futures_flipped_into_alignment_c2": futures_flipped_into_alignment,
                "futures_streak_strengthened_c2": streak_strengthened,
                "vwap_support_maintained_c1_c2": vwap_maintained,
                "vwap_crossed_into_alignment_c2": vwap_crossed_into_alignment,
            })

            i += final_len

    return events


def _three_plus_rate(rows):
    if not rows:
        return None
    return sum(bool(r["outcome_three_plus"]) for r in rows) / len(rows)


def _binary_split(rows, key):
    yes = [r for r in rows if r.get(key) is True]
    no = [r for r in rows if r.get(key) is False]
    return {
        "true_rows": len(yes),
        "true_three_plus_rate": _three_plus_rate(yes),
        "false_rows": len(no),
        "false_three_plus_rate": _three_plus_rate(no),
    }


def _summarize_candle1(events):
    return {
        "events": len(events),
        "three_plus_rate": _three_plus_rate(events),
        "futures_support": _binary_split(events, "c1_futures_support"),
        "vwap_support": _binary_split(events, "c1_vwap_support"),
        "futures_and_vwap_support": _binary_split(events, "c1_futures_and_vwap_support"),
        "session_context_support": _binary_split(events, "c1_session_context_support"),
    }


def _summarize_candle2(events):
    rows = [e for e in events if e["has_candle2"]]
    return {
        "events_reaching_candle2": len(rows),
        "three_plus_rate": _three_plus_rate(rows),
        "c2_futures_support": _binary_split(rows, "c2_futures_support"),
        "c2_vwap_support": _binary_split(rows, "c2_vwap_support"),
        "c2_futures_and_vwap_support": _binary_split(rows, "c2_futures_and_vwap_support"),
        "futures_support_maintained_c1_c2": _binary_split(rows, "futures_support_maintained_c1_c2"),
        "futures_flipped_into_alignment_c2": _binary_split(rows, "futures_flipped_into_alignment_c2"),
        "futures_streak_strengthened_c2": _binary_split(rows, "futures_streak_strengthened_c2"),
        "vwap_support_maintained_c1_c2": _binary_split(rows, "vwap_support_maintained_c1_c2"),
        "vwap_crossed_into_alignment_c2": _binary_split(rows, "vwap_crossed_into_alignment_c2"),
        "c2_session_context_support": _binary_split(rows, "c2_session_context_support"),
    }


def _joint_sequences(events):
    rows = [e for e in events if e["has_candle2"]]
    out = {}
    for f1 in (False, True):
        for f2 in (False, True):
            for v2 in (False, True):
                subset = [
                    e for e in rows
                    if e["c1_futures_support"] is f1
                    and e["c2_futures_support"] is f2
                    and e["c2_vwap_support"] is v2
                ]
                key = f"c1f_{str(f1).lower()}__c2f_{str(f2).lower()}__c2v_{str(v2).lower()}"
                out[key] = {
                    "rows": len(subset),
                    "three_plus_rate": _three_plus_rate(subset),
                }
    return out


def build_report(events):
    return {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_RESEARCH_ONLY",
        "strategy_logic_changed": False,
        "all3_state_definition_changed": False,
        "threshold_optimization": False,
        "research_question": (
            "For a new opposite-direction ALL3 run, how much early confirmation comes from "
            "futures OI alignment/streak behavior and VWAP at candle 1 and candle 2?"
        ),
        "event_definition": (
            "first candle of a new opposite-direction directional ALL3 run after the most recent "
            "opposite directional ALL3 observation; MIXED/INCOMPLETE gaps are retained"
        ),
        "outcome": "final contiguous run reaches 3+ candles; evaluation only",
        "notes": [
            "No trading threshold is created.",
            "Candle-2 analysis is conditional on the run surviving to a second ALL3 candle.",
            "Futures streak strengthening means target-direction futures OI streak at candle 2 exceeds candle 1.",
            "Futures maintained means target-direction futures support is true at both candle 1 and candle 2.",
            "VWAP maintained means VWAP supports target direction at both candle 1 and candle 2.",
            "Session OI/PCR is retained only as background context after weak discrimination in V1.",
            "Historical persistence asymmetry and directional-share majority are intentionally not promoted after weak V1 results.",
            "Change-PCR remains excluded after weak expansion validation.",
        ],
        "event_count": len(events),
        "candle1": _summarize_candle1(events),
        "candle2": _summarize_candle2(events),
        "joint_c1_c2_sequences": _joint_sequences(events),
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
    events = build_events(states, audits)
    report = build_report(events)

    write_csv(events, a.events_csv)
    p = Path(a.summary_json)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
