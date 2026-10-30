from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, Counter
from pathlib import Path
from statistics import mean, median

MODEL = "EARLY_PERSISTENCE_ASYMMETRY_VALIDATION_V1"
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
    s = [hrows.get(h, {}).get("existing_horizon_state") for h in HORIZONS]
    if any(x in (None, "", "NA") for x in s):
        return "INCOMPLETE"
    if all(x == "BULLISH" for x in s):
        return BULL
    if all(x == "BEARISH" for x in s):
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
        d = data["session_date"]
        out[d] = {r["timestamp"]: r for r in data.get("rows", [])}
    return out


def contiguous_run(states, start):
    state = states[start]["state"]
    j = start
    while j < len(states) and states[j]["state"] == state:
        j += 1
    return j - start


def historical_run_lengths(states, upto_exclusive):
    # completed directional runs strictly before upto_exclusive
    res = {BULL: [], BEAR: []}
    i = 0
    while i < upto_exclusive:
        st = states[i]["state"]
        if st not in DIRS:
            i += 1
            continue
        j = i + 1
        while j < upto_exclusive and states[j]["state"] == st:
            j += 1
        # only include the run if it fully ended before snapshot
        if j < upto_exclusive:
            res[st].append(j - i)
        i = j
    return res


def directional_counts(states, upto_inclusive):
    c = Counter()
    for r in states[:upto_inclusive + 1]:
        if r["state"] in DIRS:
            c[r["state"]] += 1
    return c


def mean_or_none(xs):
    return None if not xs else mean(xs)


def support_sign(v, target):
    x = _num(v)
    if x is None or x == 0:
        return None
    return (x > 0) if target == BULL else (x < 0)


def support_text(v, target):
    if v in (None, "", "NA"):
        return None
    desired = "BULLISH" if target == BULL else "BEARISH"
    return str(v).upper() == desired


def vwap_support(v, target):
    if v in (None, "", "NA"):
        return None
    desired = "ABOVE" if target == BULL else "BELOW"
    return str(v).upper() == desired


def build_snapshots(states_by_session, audits):
    rows = []
    event_id = 0

    for d in sorted(states_by_session):
        states = states_by_session[d]
        last_dir = None
        i = 0

        while i < len(states):
            st = states[i]["state"]
            if st not in DIRS:
                i += 1
                continue

            # identify start of directional run
            if i > 0 and states[i - 1]["state"] == st:
                i += 1
                continue

            # need previous opposite directional observation to call it a reversal candidate
            j = i - 1
            while j >= 0 and states[j]["state"] not in DIRS:
                j -= 1
            if j < 0 or states[j]["state"] == st:
                i += contiguous_run(states, i)
                continue

            event_id += 1
            final_len = contiguous_run(states, i)
            source = states[j]["state"]
            gap = i - j - 1

            for snap_run_len in (1, 2):
                snap_idx = i + snap_run_len - 1
                if snap_idx >= len(states):
                    continue
                if any(states[k]["state"] != st for k in range(i, snap_idx + 1)):
                    continue

                audit = audits.get(d, {}).get(states[snap_idx]["timestamp"], {})

                hist = historical_run_lengths(states, i)
                target_hist = hist[st]
                counter_state = BEAR if st == BULL else BULL
                counter_hist = hist[counter_state]

                target_hist_mean = mean_or_none(target_hist)
                counter_hist_mean = mean_or_none(counter_hist)

                # causal "effective" target mean includes the currently developing run
                target_effective = target_hist + [snap_run_len]
                target_effective_mean = mean_or_none(target_effective)

                asym = None
                if target_effective_mean is not None and counter_hist_mean is not None:
                    asym = target_effective_mean - counter_hist_mean

                counts = directional_counts(states, snap_idx)
                tcount = counts[st]
                ccount = counts[counter_state]
                share = None if (tcount + ccount) == 0 else tcount / (tcount + ccount)

                sess_imb = support_sign(audit.get("session_imbalance"), st)
                sess_pcr = support_sign(audit.get("session_pcr_change_0920_to_now"), st)
                if sess_imb is True and sess_pcr is True:
                    sess_ctx = True
                elif sess_imb is False and sess_pcr is False:
                    sess_ctx = False
                else:
                    sess_ctx = None

                fut = support_text(audit.get("futures_oi_direction"), st)
                vw = vwap_support(audit.get("vwap_side"), st)

                # descriptive causal indicators; no optimized numeric cutoff
                asym_positive = None if asym is None else asym > 0
                share_majority = None if share is None else share > 0.5

                supports = {
                    "futures_support": fut,
                    "vwap_support": vw,
                    "session_context_support": sess_ctx,
                    "persistence_asymmetry_positive": asym_positive,
                    "directional_share_majority": share_majority,
                }
                available = sum(v is not None for v in supports.values())
                positive = sum(v is True for v in supports.values())

                rows.append({
                    "event_id": event_id,
                    "session_date": d,
                    "snapshot_timestamp": states[snap_idx]["timestamp"],
                    "snapshot_run_length": snap_run_len,
                    "from_state": source,
                    "to_state": st,
                    "gap_candles": gap,
                    "final_run_length": final_len,
                    "outcome_three_plus": final_len >= 3,
                    "historical_target_run_count": len(target_hist),
                    "historical_counter_run_count": len(counter_hist),
                    "historical_target_mean_run": target_hist_mean,
                    "historical_counter_mean_run": counter_hist_mean,
                    "target_effective_mean_run": target_effective_mean,
                    "persistence_asymmetry": asym,
                    "persistence_asymmetry_positive": asym_positive,
                    "target_directional_candles_to_now": tcount,
                    "counter_directional_candles_to_now": ccount,
                    "target_directional_share_to_now": share,
                    "directional_share_majority": share_majority,
                    "futures_oi_direction": audit.get("futures_oi_direction"),
                    "futures_oi_status": audit.get("futures_oi_status"),
                    "futures_support": fut,
                    "vwap_side": audit.get("vwap_side"),
                    "vwap_support": vw,
                    "session_imbalance": audit.get("session_imbalance"),
                    "session_pcr_change": audit.get("session_pcr_change_0920_to_now"),
                    "session_context_support": sess_ctx,
                    "available_components": available,
                    "supportive_components": positive,
                })

            i += final_len
    return rows


def rate(rows, pred):
    xs = [r for r in rows if pred(r)]
    if not xs:
        return None
    return sum(bool(r["outcome_three_plus"]) for r in xs) / len(xs)


def _group(rows, key, value):
    return [r for r in rows if r.get(key) is value]


def summarize_snapshot(rows):
    out = {
        "rows": len(rows),
        "three_plus_count": sum(r["outcome_three_plus"] for r in rows),
        "three_plus_rate": None if not rows else sum(r["outcome_three_plus"] for r in rows) / len(rows),
        "mean_supportive_components": None if not rows else mean(r["supportive_components"] for r in rows),
        "median_supportive_components": None if not rows else median(r["supportive_components"] for r in rows),
    }
    for key in (
        "futures_support",
        "vwap_support",
        "session_context_support",
        "persistence_asymmetry_positive",
        "directional_share_majority",
    ):
        yes = _group(rows, key, True)
        no = _group(rows, key, False)
        out[key] = {
            "support_true_rows": len(yes),
            "support_true_three_plus_rate": None if not yes else sum(r["outcome_three_plus"] for r in yes) / len(yes),
            "support_false_rows": len(no),
            "support_false_three_plus_rate": None if not no else sum(r["outcome_three_plus"] for r in no) / len(no),
        }

    # especially important joint causal states
    combos = {}
    for fut in (False, True):
        for asym in (False, True):
            subset = [r for r in rows if r["futures_support"] is fut and r["persistence_asymmetry_positive"] is asym]
            combos[f"futures_{str(fut).lower()}__asym_{str(asym).lower()}"] = {
                "rows": len(subset),
                "three_plus_rate": None if not subset else sum(r["outcome_three_plus"] for r in subset) / len(subset),
            }
    out["futures_x_persistence_asymmetry"] = combos
    return out


def build_report(rows):
    snap1 = [r for r in rows if r["snapshot_run_length"] == 1]
    snap2 = [r for r in rows if r["snapshot_run_length"] == 2]
    return {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_RESEARCH_ONLY",
        "strategy_logic_changed": False,
        "all3_state_definition_changed": False,
        "threshold_optimization": False,
        "research_question": (
            "At candle 1 or candle 2 of a new opposite-direction ALL3 run, "
            "can causal persistence asymmetry plus independent context distinguish "
            "runs that later reach 3+ candles?"
        ),
        "causal_features": [
            "current ALL3 run length (1 or 2 only)",
            "prior completed same-direction run history",
            "prior completed opposite-direction run history",
            "target directional share up to snapshot",
            "futures OI direction",
            "VWAP side",
            "fixed-session OI/PCR context",
        ],
        "notes": [
            "Outcome is final contiguous ALL3 run length >= 3 and is never used in features.",
            "No fitted persistence threshold is introduced.",
            "Persistence asymmetry uses target effective mean minus counter completed-run mean.",
            "Directional share majority uses the natural 0.5 split only; it is not optimized.",
            "P1/P2 are excluded because they were unavailable across the 54-session confluence dataset.",
            "Change-PCR remains excluded after weak expansion validation.",
        ],
        "snapshot_1": summarize_snapshot(snap1),
        "snapshot_2": summarize_snapshot(snap2),
        "rows": rows,
    }


def write_csv(rows, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("")
        return
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-csv", required=True)
    ap.add_argument("--audit-json", action="append", required=True)
    ap.add_argument("--snapshots-csv", required=True)
    ap.add_argument("--summary-json", required=True)
    a = ap.parse_args(argv)

    states = load_states(a.rows_csv)
    audits = load_audits(a.audit_json)
    rows = build_snapshots(states, audits)
    report = build_report(rows)
    write_csv(rows, a.snapshots_csv)

    p = Path(a.summary_json)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
