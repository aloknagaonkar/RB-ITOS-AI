
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime
from pathlib import Path

VERSION = "OI_P1_VWAP_36_SESSIONS_V3"
TREND_CLASSES = {"BULLISH_TREND_DAY", "BEARISH_TREND_DAY"}

def dt(v: str) -> datetime:
    return datetime.fromisoformat(v)

def causal_bar(bars: list[dict], event_dt: datetime) -> dict | None:
    done = [b for b in bars if dt(b["decision_available_at"]) <= event_dt]
    return done[-1] if done else None

def same_label_bar(bars: list[dict], event_dt: datetime) -> dict | None:
    label = event_dt.strftime("%H:%M")
    for b in bars:
        if b["candle_label"] == label:
            return b
    return None

def aligned(direction: str, side: str) -> bool:
    return (
        (direction == "BULLISH" and side == "ABOVE")
        or (direction == "BEARISH" and side == "BELOW")
    )

def slope_aligned(direction: str, slope: str) -> bool:
    return (
        (direction == "BULLISH" and slope == "RISING")
        or (direction == "BEARISH" and slope == "FALLING")
    )

def median(vals):
    xs = [x for x in vals if x is not None]
    return statistics.median(xs) if xs else None

def positive_pct(vals):
    xs = [x for x in vals if x is not None]
    return None if not xs else 100.0 * sum(x > 0 for x in xs) / len(xs)

def pct_true(rows, key):
    return None if not rows else 100.0 * sum(bool(r[key]) for r in rows) / len(rows)

def load_vwap(path: Path):
    obj = json.loads(path.read_text())
    out = {}
    for s in obj["sessions"]:
        out[s["session_date"]] = s
    return out

def build_rows(pattern_path: Path, vwap_path: Path):
    p = json.loads(pattern_path.read_text())
    vw = load_vwap(vwap_path)

    trend_dates = {
        d for d, s in vw.items()
        if s["day_class"] in TREND_CLASSES
    }
    if len(trend_dates) != 36:
        raise RuntimeError(f"Expected exactly 36 trend dates, got {len(trend_dates)}")

    rows = []
    missing_vwap = 0

    for e in p["events"]:
        if e["session_date"] not in trend_dates:
            continue
        if e["day_class"] not in TREND_CLASSES:
            continue

        event_dt = dt(e["timestamp"])
        bars = vw[e["session_date"]]["candles"]
        cb = causal_bar(bars, event_dt)
        sb = same_label_bar(bars, event_dt)

        if cb is None:
            missing_vwap += 1
            continue

        # Exact schema from OI_PATTERN_CONTROL_TIMING_V1.
        row = {
            "session_date": e["session_date"],
            "day_class": e["day_class"],
            "block": e["block"],
            "p1_time": e["candle_time"],
            "p1_timestamp": e["timestamp"],
            "direction": e["direction"],
            "occurrence_number": e["occurrence_number"],
            "spot_close": e["spot_close"],
            "moving_atm": e["moving_atm"],

            "moving_ce_oi": e["moving_ce_oi"],
            "moving_pe_oi": e["moving_pe_oi"],
            "ce_delta_5m": e["ce_delta_5m"],
            "pe_delta_5m": e["pe_delta_5m"],
            "ce_pct_5m": e["ce_pct_5m"],
            "pe_pct_5m": e["pe_pct_5m"],
            "activity_5m": e["activity_5m"],
            "imbalance_5m": e["imbalance_5m"],

            "pcr_previous_5m": e["pcr_previous_5m"],
            "pcr_current_5m": e["pcr_current_5m"],
            "pcr_change_5m": e["pcr_change_5m"],

            "fixed_0920_atm": e["fixed_0920_atm"],
            "ce_0920_oi": e["ce_0920_oi"],
            "pe_0920_oi": e["pe_0920_oi"],
            "ce_session_delta": e["ce_session_delta"],
            "pe_session_delta": e["pe_session_delta"],
            "ce_session_pct": e["ce_session_pct"],
            "pe_session_pct": e["pe_session_pct"],
            "session_activity": e["session_activity"],
            "session_imbalance": e["session_imbalance"],
            "pcr_0920": e["pcr_0920"],
            "pcr_current_session": e["pcr_current_session"],
            "pcr_session_change": e["pcr_session_change"],

            "p1": bool(e["persists_1cp"]),
            "p2": bool(e["persists_2cp"]),
            "p3": bool(e["persists_3cp"]),
            "p4": bool(e["persists_4cp"]),

            "plus_5m": e["directional_move_5m_points"],
            "plus_10m": e["directional_move_10m_points"],
            "plus_15m": e["directional_move_15m_points"],
            "plus_20m": e["directional_move_20m_points"],

            # Causal VWAP: last completed 5m candle at the P1 timestamp.
            "vwap_candle": cb["candle_label"],
            "vwap_available": cb["decision_available_at"][11:16],
            "fut_open": cb["open"],
            "fut_high": cb["high"],
            "fut_low": cb["low"],
            "fut_close": cb["close"],
            "vwap": cb["vwap"],
            "vwap_distance": cb["distance_points"],
            "vwap_side": cb["side"],
            "vwap_cross": cb["cross"],
            "vwap_slope": cb["vwap_slope"],
            "vwap_side_aligned": aligned(e["direction"], cb["side"]),
            "vwap_slope_aligned": slope_aligned(e["direction"], cb["vwap_slope"]),
            "vwap_full_aligned": (
                aligned(e["direction"], cb["side"])
                and slope_aligned(e["direction"], cb["vwap_slope"])
            ),

            # Chart-reference only; not causal at P1.
            "same_label_candle": sb["candle_label"] if sb else None,
            "same_label_available": sb["decision_available_at"][11:16] if sb else None,
            "same_label_close": sb["close"] if sb else None,
            "same_label_vwap": sb["vwap"] if sb else None,
            "same_label_distance": sb["distance_points"] if sb else None,
            "same_label_side": sb["side"] if sb else None,
        }
        rows.append(row)

    return rows, trend_dates, missing_vwap

def summarize(rows):
    result = {}

    for direction in ("BULLISH", "BEARISH"):
        drows = [r for r in rows if r["direction"] == direction]

        groups = {
            "ALL": drows,
            "VWAP_SIDE_ALIGNED": [r for r in drows if r["vwap_side_aligned"]],
            "VWAP_SIDE_NOT_ALIGNED": [r for r in drows if not r["vwap_side_aligned"]],
            "VWAP_SIDE_AND_SLOPE_ALIGNED": [r for r in drows if r["vwap_full_aligned"]],
            "VWAP_SIDE_ALIGNED_IMB_GE_3M": [
                r for r in drows
                if r["vwap_side_aligned"] and abs(r["imbalance_5m"]) >= 3_000_000
            ],
        }

        for name, xs in groups.items():
            key = f"{direction}_{name}"
            result[key] = {
                "events": len(xs),
                "median_abs_imbalance_5m": median([abs(r["imbalance_5m"]) for r in xs]),
                "median_activity_5m": median([r["activity_5m"] for r in xs]),
                "median_pcr_change_5m": median([r["pcr_change_5m"] for r in xs]),
                "median_session_imbalance": median([r["session_imbalance"] for r in xs]),
                "p2_pct": pct_true(xs, "p2"),
                "p3_pct": pct_true(xs, "p3"),
                "p4_pct": pct_true(xs, "p4"),
                "plus5_positive_pct": positive_pct([r["plus_5m"] for r in xs]),
                "plus10_positive_pct": positive_pct([r["plus_10m"] for r in xs]),
                "plus15_positive_pct": positive_pct([r["plus_15m"] for r in xs]),
                "plus20_positive_pct": positive_pct([r["plus_20m"] for r in xs]),
                "median_plus5": median([r["plus_5m"] for r in xs]),
                "median_plus10": median([r["plus_10m"] for r in xs]),
                "median_plus15": median([r["plus_15m"] for r in xs]),
                "median_plus20": median([r["plus_20m"] for r in xs]),
            }

    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern-events", required=True)
    ap.add_argument("--vwap-profile", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output", required=True)
    args = ap.parse_args()

    rows, trend_dates, missing_vwap = build_rows(
        Path(args.pattern_events),
        Path(args.vwap_profile),
    )

    if not rows:
        raise RuntimeError("No trend-day P1 rows produced")

    expected_required = [
        "ce_delta_5m", "pe_delta_5m", "imbalance_5m",
        "pcr_change_5m", "session_imbalance",
        "plus_10m", "plus_20m",
    ]
    for key in expected_required:
        if sum(r.get(key) is not None for r in rows) == 0:
            raise RuntimeError(f"Required field unexpectedly absent: {key}")

    class_counts = {
        "BULLISH_TREND_DAY": len({r["session_date"] for r in rows if r["day_class"]=="BULLISH_TREND_DAY"}),
        "BEARISH_TREND_DAY": len({r["session_date"] for r in rows if r["day_class"]=="BEARISH_TREND_DAY"}),
    }
    if class_counts != {"BULLISH_TREND_DAY":18, "BEARISH_TREND_DAY":18}:
        raise RuntimeError(f"Expected 18+18 sessions in event population, got {class_counts}")

    result = {
        "research_version": VERSION,
        "population": {
            "trend_session_count": 36,
            "bullish_sessions": 18,
            "bearish_sessions": 18,
            "event_count": len(rows),
        },
        "integrity": {
            "missing_causal_vwap": missing_vwap,
            "required_fields_present": True,
            "class_counts": class_counts,
        },
        "definitions": {
            "bullish_p1": "existing OI_PATTERN_CONTROL_TIMING_V1 event: imbalance flips positive, PCR 5m positive, session imbalance improving",
            "bearish_p1": "existing OI_PATTERN_CONTROL_TIMING_V1 event: imbalance flips negative, PCR 5m negative, session imbalance weakening",
            "vwap_alignment": "latest fully completed futures 5m candle available at P1 time; bullish=ABOVE, bearish=BELOW",
            "vwap_full_alignment": "VWAP side aligned AND VWAP slope aligned",
            "same_label_candle": "visual chart validation only; closes 5m after its chart label and is not used at P1",
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
