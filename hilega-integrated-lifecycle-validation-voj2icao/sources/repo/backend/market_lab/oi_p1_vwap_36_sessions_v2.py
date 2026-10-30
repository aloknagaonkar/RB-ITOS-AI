
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime
from pathlib import Path

VERSION = "OI_P1_VWAP_36_SESSIONS_V2"

TREND_CLASSES = {"BULLISH_TREND_DAY", "BEARISH_TREND_DAY"}

def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)

def first(d, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None

def num(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None

def truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().upper() in {"Y", "YES", "TRUE", "1"}

def parse_dt(v, session_date=None):
    if v is None:
        return None
    s = str(v)
    if "T" in s:
        return datetime.fromisoformat(s)
    if session_date and ":" in s:
        return datetime.fromisoformat(f"{session_date}T{s[:5]}:00+05:30")
    return None

def event_key(date, ts, direction):
    return (date, ts.strftime("%H:%M"), direction)

def extract_pattern_events(obj):
    """
    Extract rich P1 rows from OI_PATTERN_CONTROL_TIMING_V1.

    This is intentionally strict: we require the fields that were missing in V1
    (CE delta, PE delta, PCR delta / current PCR where present). We do not silently
    accept the stripped outcome-analysis representation as the primary source.
    """
    out = {}
    for d in walk(obj):
        direction = str(first(d, "direction", "candidate_direction", "signal_direction") or "").upper()
        date = str(first(d, "session_date", "date") or "")
        ts_raw = first(d, "timestamp", "event_timestamp", "signal_timestamp", "time")
        if direction not in {"BULLISH", "BEARISH"} or not date or ts_raw is None:
            continue
        ts = parse_dt(ts_raw, date)
        if ts is None:
            continue

        ce_delta = num(first(
            d,
            "ce_5m_delta", "ce_delta", "ce5m_delta",
            "ce_oi_change", "ce_oi_delta", "ce_change"
        ))
        pe_delta = num(first(
            d,
            "pe_5m_delta", "pe_delta", "pe5m_delta",
            "pe_oi_change", "pe_oi_delta", "pe_change"
        ))
        imbalance = num(first(
            d,
            "imbalance", "oi_imbalance", "five_minute_imbalance",
            "five_min_imbalance", "imbalance_5m"
        ))
        if imbalance is None and ce_delta is not None and pe_delta is not None:
            imbalance = pe_delta - ce_delta

        pcr_now = num(first(
            d, "pcr_now", "current_pcr", "pcr_ratio", "pcr"
        ))
        pcr_prev = num(first(
            d, "pcr_prev", "previous_pcr", "prior_pcr"
        ))
        pcr_delta = num(first(
            d, "pcr_5m_change", "pcr_change", "pcr_delta"
        ))
        if pcr_delta is None and pcr_now is not None and pcr_prev is not None:
            pcr_delta = pcr_now - pcr_prev

        # A transition row must at minimum expose imbalance or CE/PE deltas.
        if imbalance is None and ce_delta is None and pe_delta is None:
            continue

        k = event_key(date, ts, direction)
        row = {
            "session_date": date,
            "event_dt": ts,
            "event_time": ts.strftime("%H:%M"),
            "direction": direction,
            "day_class": first(d, "day_class"),
            "spot": num(first(d, "spot", "spot_price")),
            "atm": num(first(d, "moving_atm", "atm", "atm_strike")),
            "ce_5m_delta": ce_delta,
            "pe_5m_delta": pe_delta,
            "imbalance": imbalance,
            "activity": num(first(
                d, "activity", "oi_activity", "five_minute_activity",
                "five_min_activity", "activity_5m"
            )),
            "pcr_prev": pcr_prev,
            "pcr_now": pcr_now,
            "pcr_5m_change": pcr_delta,
            "session_imbalance": num(first(
                d, "session_imbalance", "sess_imbalance"
            )),
            "session_activity": num(first(
                d, "session_activity", "sess_activity"
            )),
            "pcr_session_change": num(first(
                d, "pcr_session_change", "session_pcr_change",
                "pcr_day_change", "pcr_day_delta"
            )),
            "p2": truthy(first(d, "p2", "p2_persistence", "persistence_2")),
            "p3": truthy(first(d, "p3", "p3_persistence", "persistence_3")),
            "p4": truthy(first(d, "p4", "p4_persistence", "persistence_4")),
        }
        # Prefer rows with richer CE/PE/PCR content if duplicates exist.
        score = sum(row[x] is not None for x in (
            "ce_5m_delta","pe_5m_delta","pcr_now","pcr_5m_change","session_imbalance"
        ))
        old = out.get(k)
        if old is None or score > old["_score"]:
            row["_score"] = score
            out[k] = row
    return out

def extract_outcomes(obj):
    out = {}
    for d in walk(obj):
        direction = str(first(d, "direction", "signal_direction") or "").upper()
        date = str(first(d, "session_date", "date") or "")
        ts_raw = first(d, "timestamp", "signal_timestamp", "time", "event_time")
        if direction not in {"BULLISH", "BEARISH"} or not date or ts_raw is None:
            continue
        ts = parse_dt(ts_raw, date)
        if ts is None:
            continue

        k = event_key(date, ts, direction)
        candidate = {
            "outcome_20m": first(d, "outcome_20m", "outcome20", "classification_20m"),
            "plus_5m": num(first(d, "directional_5m", "plus_5m", "points_5m")),
            "plus_10m": num(first(d, "directional_10m", "plus_10m", "points_10m")),
            "plus_15m": num(first(d, "directional_15m", "plus_15m", "points_15m")),
            "plus_20m": num(first(d, "directional_20m", "plus_20m", "points_20m")),
            "p2_outcome_source": truthy(first(d, "p2", "p2_persistence", "persistence_2")),
            "p3_outcome_source": truthy(first(d, "p3", "p3_persistence", "persistence_3")),
            "p4_outcome_source": truthy(first(d, "p4", "p4_persistence", "persistence_4")),
        }
        # Keep the richest candidate.
        score = sum(v is not None for v in candidate.values())
        old = out.get(k)
        if old is None or score > old["_score"]:
            candidate["_score"] = score
            out[k] = candidate
    return out

def load_vwap(path):
    obj = json.loads(Path(path).read_text())
    out = {}
    for s in obj.get("sessions", []):
        bars = []
        for b in s.get("candles", []):
            bb = dict(b)
            bb["_start"] = datetime.fromisoformat(bb["candle_start"])
            bb["_avail"] = datetime.fromisoformat(bb["decision_available_at"])
            bars.append(bb)
        out[s["session_date"]] = {"day_class": s["day_class"], "bars": bars}
    return out

def causal_bar(bars, event_dt):
    xs = [b for b in bars if b["_avail"] <= event_dt]
    return xs[-1] if xs else None

def same_label_bar(bars, event_dt):
    label = event_dt.strftime("%H:%M")
    for b in bars:
        if b["candle_label"] == label:
            return b
    return None

def aligned(direction, side):
    return (direction == "BULLISH" and side == "ABOVE") or (
        direction == "BEARISH" and side == "BELOW"
    )

def median(xs):
    ys = [x for x in xs if x is not None]
    return statistics.median(ys) if ys else None

def positive_rate(xs):
    ys = [x for x in xs if x is not None]
    return None if not ys else 100.0 * sum(x > 0 for x in ys) / len(ys)

def summarize(rows):
    out = {}
    for direction in ("BULLISH", "BEARISH"):
        ds = [r for r in rows if r["direction"] == direction]
        if not ds:
            continue
        for label, pred in (
            ("ALIGNED", lambda r: r["vwap_aligned_at_p1"]),
            ("NOT_ALIGNED", lambda r: not r["vwap_aligned_at_p1"]),
        ):
            xs = [r for r in ds if pred(r)]
            out[f"{direction}_{label}"] = {
                "events": len(xs),
                "median_abs_imbalance": median([abs(r["imbalance"]) for r in xs if r["imbalance"] is not None]),
                "p2_pct": None if not xs else 100.0 * sum(r["p2"] for r in xs) / len(xs),
                "p3_pct": None if not xs else 100.0 * sum(r["p3"] for r in xs) / len(xs),
                "p4_pct": None if not xs else 100.0 * sum(r["p4"] for r in xs) / len(xs),
                "plus10_positive_pct": positive_rate([r["plus_10m"] for r in xs]),
                "plus20_positive_pct": positive_rate([r["plus_20m"] for r in xs]),
                "median_plus10": median([r["plus_10m"] for r in xs]),
                "median_plus20": median([r["plus_20m"] for r in xs]),
            }
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern-events", required=True)
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--vwap-profile", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output", required=True)
    args = ap.parse_args()

    pattern_obj = json.loads(Path(args.pattern_events).read_text())
    outcome_obj = json.loads(Path(args.outcomes).read_text())
    p1 = extract_pattern_events(pattern_obj)
    outcomes = extract_outcomes(outcome_obj)
    vw = load_vwap(args.vwap_profile)

    trend_dates = {d for d,s in vw.items() if s["day_class"] in TREND_CLASSES}
    if len(trend_dates) != 36:
        raise RuntimeError(f"Expected exactly 36 trend dates in VWAP profile, got {len(trend_dates)}")

    rows = []
    missing_vwap = 0
    missing_outcome = 0
    for k,e in sorted(p1.items()):
        if e["session_date"] not in trend_dates:
            continue

        s = vw[e["session_date"]]
        day_class = e["day_class"] or s["day_class"]
        cb = causal_bar(s["bars"], e["event_dt"])
        sb = same_label_bar(s["bars"], e["event_dt"])
        if cb is None:
            missing_vwap += 1
            continue

        o = outcomes.get(k)
        if o is None:
            missing_outcome += 1
            o = {}

        row = {kk:vv for kk,vv in e.items() if kk not in {"event_dt","_score"}}
        # If pattern source lacks persistence but outcome source has it, fill from outcome source.
        row["p2"] = row["p2"] or bool(o.get("p2_outcome_source"))
        row["p3"] = row["p3"] or bool(o.get("p3_outcome_source"))
        row["p4"] = row["p4"] or bool(o.get("p4_outcome_source"))
        row.update({
            "outcome_20m": o.get("outcome_20m"),
            "plus_5m": o.get("plus_5m"),
            "plus_10m": o.get("plus_10m"),
            "plus_15m": o.get("plus_15m"),
            "plus_20m": o.get("plus_20m"),

            "causal_vwap_candle": cb["candle_label"],
            "causal_vwap_available": cb["decision_available_at"][11:16],
            "causal_fut_open": cb["open"],
            "causal_fut_high": cb["high"],
            "causal_fut_low": cb["low"],
            "causal_fut_close": cb["close"],
            "causal_vwap": cb["vwap"],
            "causal_vwap_distance": cb["distance_points"],
            "causal_vwap_side": cb["side"],
            "causal_vwap_cross": cb["cross"],
            "causal_vwap_slope": cb["vwap_slope"],
            "vwap_aligned_at_p1": aligned(e["direction"], cb["side"]),

            "same_label_candle": sb["candle_label"] if sb else None,
            "same_label_available": sb["decision_available_at"][11:16] if sb else None,
            "same_label_fut_close": sb["close"] if sb else None,
            "same_label_vwap": sb["vwap"] if sb else None,
            "same_label_distance": sb["distance_points"] if sb else None,
            "same_label_side": sb["side"] if sb else None,
        })
        rows.append(row)

    # Integrity gates. These are deliberate so we do not repeat V1's silent NA problem.
    if not rows:
        raise RuntimeError("No 36-session P1 rows produced")
    ce_present = sum(r["ce_5m_delta"] is not None for r in rows)
    pe_present = sum(r["pe_5m_delta"] is not None for r in rows)
    pcr_present = sum(r["pcr_5m_change"] is not None for r in rows)
    if ce_present == 0 or pe_present == 0:
        raise RuntimeError(
            "CE/PE 5m deltas were not found in pattern-events source. "
            "Do not use this report until source field mapping is fixed."
        )
    if pcr_present == 0:
        raise RuntimeError(
            "PCR 5m change was not found in pattern-events source. "
            "Do not use this report until source field mapping is fixed."
        )

    result = {
        "research_version": VERSION,
        "population": {
            "trend_session_count": 36,
            "trend_dates": sorted(trend_dates),
            "event_count": len(rows),
        },
        "integrity": {
            "missing_vwap": missing_vwap,
            "missing_outcome_match": missing_outcome,
            "ce_delta_present": ce_present,
            "pe_delta_present": pe_present,
            "pcr_5m_change_present": pcr_present,
        },
        "methodology": {
            "primary_p1_source": "OI_PATTERN_CONTROL_TIMING_V1 rich event rows",
            "outcome_source": "OI_TRANSITION_OUTCOME_ANALYSIS_V1",
            "vwap_source": "VWAP_TREND_DAY_PROFILE_V1",
            "scope": "exactly frozen 18 bullish + 18 bearish trend days",
            "causal_vwap": "latest completed 5m futures candle available at P1 timestamp",
            "same_label_candle": "chart validation only; not causal at P1",
            "research_only": True,
        },
        "summary": summarize(rows),
        "events": rows,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")

    fields = list(rows[0].keys())
    with Path(args.csv_output).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(json.dumps({
        "research_version": VERSION,
        "population": result["population"],
        "integrity": result["integrity"],
        "summary": result["summary"],
        "output": args.output,
        "csv_output": args.csv_output,
    }, indent=2, allow_nan=False))

if __name__ == "__main__":
    main()
