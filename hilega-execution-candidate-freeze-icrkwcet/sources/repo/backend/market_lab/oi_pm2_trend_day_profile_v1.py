from __future__ import annotations

"""
OI_PM2_TREND_DAY_PROFILE_V1

Consumes DAY_TREND_CLASSIFICATION_90D_V1 and evaluates Moving ATM ±2 OI only
on selected BULLISH_TREND_DAY and BEARISH_TREND_DAY sessions.

Per checkpoint:
- same physical ATM±2 strikes at T and T-5m
- CE/PE current OI
- signed CE/PE quantity changes
- CE/PE percentage changes
- gross activity = abs(CE delta) + abs(PE delta)
- PCR and PCR change
- CE/PE 5m state

Summaries are descriptive only:
- whole-day class summary
- six time windows
- sign-combination frequencies
- medians for quantity, pct, activity, PCR change
"""

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "OI_PM2_TREND_DAY_PROFILE_V1"
FORBIDDEN = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}


def f(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def dt(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100.0


def med(xs):
    vals = [x for x in xs if x is not None]
    return statistics.median(vals) if vals else None


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))


def detect(rows):
    keys = set().union(*(r.keys() for r in rows))
    def first(*xs):
        return next((x for x in xs if x in keys), None)
    c = {
        "timestamp": first("timestamp"),
        "spot": first("spot"),
        "atm": first("moving_atm"),
        "strike": first("strike"),
        "offset": first("strike_offset"),
        "ce_oi": first("ce_open_interest", "ce_oi"),
        "pe_oi": first("pe_open_interest", "pe_oi"),
        "ce_state": first("ce_5m_state"),
        "pe_state": first("pe_5m_state"),
    }
    missing = [k for k in ("timestamp","spot","atm","strike","offset","ce_oi","pe_oi") if c[k] is None]
    if missing:
        raise RuntimeError("Missing positioning columns: " + ", ".join(missing))
    return c


def snapshots(rows, c):
    out = {}
    for r in rows:
        t = dt(r[c["timestamp"]])
        out.setdefault(t, []).append(r)
    return out


def atm(rows, c):
    for r in rows:
        if f(r[c["offset"]]) == 0:
            return f(r[c["atm"]])
    return None


def atm_row(rows, c, center):
    for r in rows:
        if f(r[c["strike"]]) == center:
            return r
    return None


def aggregate(cur, prev, c, center):
    wanted = {center + i * 50.0 for i in range(-2, 3)}
    cm = {f(r[c["strike"]]): r for r in cur}
    pm = {f(r[c["strike"]]): r for r in prev}
    common = sorted(wanted & set(cm) & set(pm))
    if len(common) != 5:
        return None

    ce0 = sum(f(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce1 = sum(f(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe0 = sum(f(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe1 = sum(f(cm[s][c["pe_oi"]]) or 0 for s in common)

    return {
        "ce_oi": ce1,
        "pe_oi": pe1,
        "ce_delta": ce1-ce0,
        "pe_delta": pe1-pe0,
        "ce_pct": pct(ce1, ce0),
        "pe_pct": pct(pe1, pe0),
        "activity": abs(ce1-ce0)+abs(pe1-pe0),
        "pcr": pe1/ce1 if ce1 else None,
        "pcr_change": (pe1/ce1 - pe0/ce0) if ce1 and ce0 else None,
    }


def window_for(t):
    hm = (t.hour, t.minute)
    if hm < (10,0): return "09:20-10:00"
    if hm < (11,0): return "10:00-11:00"
    if hm < (12,0): return "11:00-12:00"
    if hm < (13,0): return "12:00-13:00"
    if hm < (14,0): return "13:00-14:00"
    return "14:00-CLOSE"


def sign_combo(ce, pe):
    if ce > 0 and pe > 0: return "CE_UP_PE_UP"
    if ce > 0 and pe < 0: return "CE_UP_PE_DOWN"
    if ce < 0 and pe > 0: return "CE_DOWN_PE_UP"
    if ce < 0 and pe < 0: return "CE_DOWN_PE_DOWN"
    return "ZERO_OR_FLAT"


def summarize(rows):
    return {
        "checkpoint_count": len(rows),
        "session_count": len({r["session_date"] for r in rows}),
        "median_ce_oi": med([r["ce_oi"] for r in rows]),
        "median_pe_oi": med([r["pe_oi"] for r in rows]),
        "median_ce_delta": med([r["ce_delta"] for r in rows]),
        "median_pe_delta": med([r["pe_delta"] for r in rows]),
        "median_ce_pct": med([r["ce_pct"] for r in rows]),
        "median_pe_pct": med([r["pe_pct"] for r in rows]),
        "median_activity": med([r["activity"] for r in rows]),
        "median_pcr": med([r["pcr"] for r in rows]),
        "median_pcr_change": med([r["pcr_change"] for r in rows]),
        "sign_combo_counts": dict(Counter(r["sign_combo"] for r in rows)),
        "ce_state_counts": dict(Counter(r["ce_state"] for r in rows)),
        "pe_state_counts": dict(Counter(r["pe_state"] for r in rows)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classification", required=True)
    ap.add_argument("--positioning", action="append", required=True,
                    help="BLOCK|positioning.csv; TRAIN/OOS_A-D only")
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output")
    a = ap.parse_args()

    cls = json.loads(Path(a.classification).read_text())
    if cls.get("research_version") != "DAY_TREND_CLASSIFICATION_90D_V1":
        raise RuntimeError("Unexpected classification research_version")

    day_class = {
        r["session_date"]: r["day_class"]
        for r in cls["sessions"]
        if r["day_class"] in {"BULLISH_TREND_DAY", "BEARISH_TREND_DAY"}
    }

    rows_out = []
    skipped = 0

    for spec in a.positioning:
        block, path = spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")

        rows = read_csv(path)
        c = detect(rows)
        sn = snapshots(rows,c)

        for t in sorted(sn):
            date_s = t.date().isoformat()
            if date_s not in day_class:
                continue
            if (t.hour,t.minute) < (9,20) or (t.hour,t.minute) > (15,29):
                continue
            if t.minute % 5 != 0:
                continue

            prev = sn.get(t-timedelta(minutes=5))
            if not prev:
                continue

            cur = sn[t]
            center = atm(cur,c)
            if center is None:
                continue

            a2 = aggregate(cur,prev,c,center)
            if not a2:
                skipped += 1
                continue

            ar = atm_row(cur,c,center)
            ce_state = ar.get(c["ce_state"]) if ar and c["ce_state"] else "UNAVAILABLE"
            pe_state = ar.get(c["pe_state"]) if ar and c["pe_state"] else "UNAVAILABLE"

            row = {
                "block": block,
                "session_date": date_s,
                "day_class": day_class[date_s],
                "timestamp": t.isoformat(),
                "time": t.strftime("%H:%M"),
                "window": window_for(t),
                "spot": f(cur[0][c["spot"]]),
                "moving_atm": center,
                **a2,
                "ce_state": ce_state,
                "pe_state": pe_state,
                "sign_combo": sign_combo(a2["ce_delta"],a2["pe_delta"]),
            }
            rows_out.append(row)

    rows_out.sort(key=lambda r:(r["session_date"],r["timestamp"]))

    overall = {}
    windows = {}
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        xs=[r for r in rows_out if r["day_class"]==dc]
        overall[dc]=summarize(xs)
        windows[dc]={}
        for w in ("09:20-10:00","10:00-11:00","11:00-12:00",
                  "12:00-13:00","13:00-14:00","14:00-CLOSE"):
            windows[dc][w]=summarize([r for r in xs if r["window"]==w])

    result = {
        "research_version": VERSION,
        "source_classification": cls["research_version"],
        "selected_day_counts": {
            "BULLISH_TREND_DAY": sum(v=="BULLISH_TREND_DAY" for v in day_class.values()),
            "BEARISH_TREND_DAY": sum(v=="BEARISH_TREND_DAY" for v in day_class.values()),
        },
        "primary_oi_scope": {
            "band": "MOVING_ATM_PM2",
            "same_physical_strikes_t_vs_t_minus_5": True,
            "quantity_and_percentage_both_retained": True,
            "activity_formula": "ABS(CE_DELTA)+ABS(PE_DELTA)",
        },
        "checkpoint_count": len(rows_out),
        "skipped_incomplete_pm2_count": skipped,
        "overall": overall,
        "by_time_window": windows,
        "rows": rows_out,
        "integrity": {
            "trend_classification_price_only": True,
            "oi_not_used_to_choose_day_class": True,
            "historical_only": True,
            "oos_e_f_g_h_used": False,
            "strategy_rule_changed": False,
            "paper_or_live_action": False,
        },
    }

    p=Path(a.output)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")

    if a.csv_output and rows_out:
        cp=Path(a.csv_output); cp.parent.mkdir(parents=True,exist_ok=True)
        with cp.open("w",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=list(rows_out[0].keys()))
            w.writeheader(); w.writerows(rows_out)

    print(json.dumps({
        "research_version": VERSION,
        "selected_day_counts": result["selected_day_counts"],
        "checkpoint_count": len(rows_out),
        "skipped_incomplete_pm2_count": skipped,
        "bullish_overall": overall["BULLISH_TREND_DAY"],
        "bearish_overall": overall["BEARISH_TREND_DAY"],
        "output": a.output,
        "csv_output": a.csv_output,
    }, indent=2))


if __name__=="__main__":
    main()
