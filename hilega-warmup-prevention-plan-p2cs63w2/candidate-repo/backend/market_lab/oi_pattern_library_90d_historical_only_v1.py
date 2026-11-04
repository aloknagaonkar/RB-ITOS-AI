from __future__ import annotations

"""
OI_PATTERN_LIBRARY_90D_HISTORICAL_ONLY_V1

Historical-only research scanner.

Scope:
- latest N unique sessions from TRAIN + OOS_A-D only
- every exact 5-minute checkpoint with exact T-5m available
- primary OI strength = Moving ATM ±2
- same physical strikes at T and T-5m
- optional fixed 09:20 ATM ±2 context
- ATM option premium/OI state when available
- forward spot outcomes +5/+10/+15m

No current day, no DB, no OOS E/F/G/H, no strategy/paper/live action.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


VERSION = "OI_PATTERN_LIBRARY_90D_HISTORICAL_ONLY_V1"
FORBIDDEN = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}


def f(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100.0


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))


def detect(rows):
    keys = set().union(*(r.keys() for r in rows))

    def first(*xs):
        return next((x for x in xs if x in keys), None)

    c = {
        "timestamp": first("timestamp", "datetime", "provider_timestamp"),
        "session_date": first("session_date", "date"),
        "spot": first("spot", "underlying_spot"),
        "strike": first("strike", "strike_price"),
        "offset": first("strike_offset", "offset"),
        "atm": first("moving_atm", "atm", "atm_strike"),
        "ce_oi": first("ce_open_interest", "ce_oi", "call_oi"),
        "pe_oi": first("pe_open_interest", "pe_oi", "put_oi"),
        "ce_close": first("ce_close", "ce_premium", "call_close"),
        "pe_close": first("pe_close", "pe_premium", "put_close"),
        "ce_state": first("ce_5m_state"),
        "pe_state": first("pe_5m_state"),
    }

    missing = [
        k
        for k in ("timestamp", "spot", "strike", "offset", "atm", "ce_oi", "pe_oi")
        if c[k] is None
    ]
    if missing:
        raise RuntimeError("Missing positioning columns: " + ", ".join(missing))
    return c


def snapshots(rows, c):
    out = {}
    for r in rows:
        t = dt(r.get(c["timestamp"]))
        if t:
            out.setdefault(t, []).append(r)
    return out


def moving_atm(rows, c):
    for r in rows:
        if f(r.get(c["offset"])) == 0:
            return f(r.get(c["atm"]))
    return None


def strike_row(rows, c, strike):
    for r in rows:
        if f(r.get(c["strike"])) == strike:
            return r
    return None


def aggregate(cur, prev, c, center, width=2, step=50.0):
    wanted = {center + i * step for i in range(-width, width + 1)}
    cm = {f(r[c["strike"]]): r for r in cur}
    pm = {f(r[c["strike"]]): r for r in prev}
    common = sorted(wanted & set(cm) & set(pm))
    if not common:
        return None

    ce0 = sum(f(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce1 = sum(f(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe0 = sum(f(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe1 = sum(f(cm[s][c["pe_oi"]]) or 0 for s in common)

    return {
        "strike_count": len(common),
        "common_strikes": common,
        "ce_oi_previous": ce0,
        "ce_oi_current": ce1,
        "pe_oi_previous": pe0,
        "pe_oi_current": pe1,
        "ce_delta": ce1 - ce0,
        "pe_delta": pe1 - pe0,
        "ce_pct": pct(ce1, ce0),
        "pe_pct": pct(pe1, pe0),
        "activity": abs(ce1 - ce0) + abs(pe1 - pe0),
        "pcr_previous": pe0 / ce0 if ce0 else None,
        "pcr_current": pe1 / ce1 if ce1 else None,
    }


def fixed_atm(snaps, c, date_s, fixed_time):
    hh, mm = map(int, fixed_time.split(":"))
    for t, rows in snaps.items():
        if t.date().isoformat() == date_s and t.hour == hh and t.minute == mm:
            return moving_atm(rows, c)
    return None


def state(price_pct, oi_pct):
    if price_pct is None or oi_pct is None:
        return "UNAVAILABLE"
    if price_pct > 0 and oi_pct > 0:
        return "LONG_BUILDUP"
    if price_pct < 0 and oi_pct > 0:
        return "SHORT_BUILDUP"
    if price_pct > 0 and oi_pct < 0:
        return "SHORT_COVERING"
    if price_pct < 0 and oi_pct < 0:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def pattern_family(r):
    ce = r.get("ce_state")
    pe = r.get("pe_state")

    if ce == "SHORT_COVERING" and pe == "LONG_BUILDUP":
        return "BULLISH_SC_PLUS_PE_LB"
    if ce == "LONG_BUILDUP" and pe == "SHORT_COVERING":
        return "BULLISH_CE_LB_PLUS_PE_SC"
    if ce == "SHORT_BUILDUP" and pe == "LONG_BUILDUP":
        return "BEARISH_CE_SB_PLUS_PE_LB"
    if ce == "LONG_UNWINDING" and pe == "LONG_BUILDUP":
        return "BULLISH_CE_LU_PLUS_PE_LB"

    ce_d = r.get("m_ce_delta")
    pe_d = r.get("m_pe_delta")
    if ce_d is not None and pe_d is not None:
        if ce_d < 0 and pe_d > 0:
            return "BULLISH_QUANTITY_DIVERGENCE"
        if ce_d > 0 and pe_d < 0:
            return "BEARISH_QUANTITY_DIVERGENCE"
        if ce_d > 0 and pe_d > 0:
            return "TWO_SIDED_OI_BUILD"
        if ce_d < 0 and pe_d < 0:
            return "TWO_SIDED_OI_UNWIND"

    return "MIXED"


def build_block(block, path, allowed_dates, fixed_time):
    rows = read_csv(path)
    c = detect(rows)
    sn = snapshots(rows, c)

    by_date = defaultdict(list)
    for t in sn:
        by_date[t.date().isoformat()].append(t)

    result = []
    skipped_incomplete_pm2 = 0

    for date_s, times in by_date.items():
        if date_s not in allowed_dates:
            continue

        fa = fixed_atm(sn, c, date_s, fixed_time)

        for t in sorted(times):
            if t.minute % 5 != 0:
                continue

            prev = sn.get(t - timedelta(minutes=5))
            if not prev:
                continue

            cur = sn[t]
            ma = moving_atm(cur, c)
            if ma is None:
                continue

            moving = aggregate(cur, prev, c, ma, width=2)
            if not moving or moving["strike_count"] != 5:
                skipped_incomplete_pm2 += 1
                continue

            fixed = aggregate(cur, prev, c, fa, width=2) if fa is not None else None

            cur_atm = strike_row(cur, c, ma)
            prev_atm = strike_row(prev, c, ma)

            ce_price_pct = pe_price_pct = None
            ce_state = pe_state = "UNAVAILABLE"

            if cur_atm and prev_atm and c["ce_close"]:
                ce_price_pct = pct(f(cur_atm.get(c["ce_close"])), f(prev_atm.get(c["ce_close"])))
            if cur_atm and prev_atm and c["pe_close"]:
                pe_price_pct = pct(f(cur_atm.get(c["pe_close"])), f(prev_atm.get(c["pe_close"])))

            if cur_atm and c["ce_state"] and cur_atm.get(c["ce_state"]):
                ce_state = cur_atm.get(c["ce_state"])
            else:
                ce_state = state(ce_price_pct, moving["ce_pct"])

            if cur_atm and c["pe_state"] and cur_atm.get(c["pe_state"]):
                pe_state = cur_atm.get(c["pe_state"])
            else:
                pe_state = state(pe_price_pct, moving["pe_pct"])

            spot = f(cur[0].get(c["spot"]))

            r = {
                "block": block,
                "session_date": date_s,
                "timestamp": t.isoformat(),
                "time": t.strftime("%H:%M"),
                "spot": spot,
                "moving_atm": ma,
                "fixed_atm": fa,
                "m_ce_oi": moving["ce_oi_current"],
                "m_pe_oi": moving["pe_oi_current"],
                "m_ce_delta": moving["ce_delta"],
                "m_pe_delta": moving["pe_delta"],
                "m_ce_pct": moving["ce_pct"],
                "m_pe_pct": moving["pe_pct"],
                "m_activity": moving["activity"],
                "m_pcr_previous": moving["pcr_previous"],
                "m_pcr": moving["pcr_current"],
                "m_pcr_change": (
                    moving["pcr_current"] - moving["pcr_previous"]
                    if moving["pcr_current"] is not None
                    and moving["pcr_previous"] is not None
                    else None
                ),
                "m_common_strikes": moving["common_strikes"],
                "atm_ce_price_pct": ce_price_pct,
                "atm_pe_price_pct": pe_price_pct,
                "ce_state": ce_state,
                "pe_state": pe_state,
                "f_ce_delta": fixed["ce_delta"] if fixed else None,
                "f_pe_delta": fixed["pe_delta"] if fixed else None,
                "f_activity": fixed["activity"] if fixed else None,
                "f_pcr": fixed["pcr_current"] if fixed else None,
            }

            for mins in (5, 10, 15):
                future = sn.get(t + timedelta(minutes=mins))
                future_spot = f(future[0].get(c["spot"])) if future else None
                r[f"forward_{mins}m_points"] = (
                    future_spot - spot
                    if future_spot is not None and spot is not None
                    else None
                )

            r["pattern_family"] = pattern_family(r)
            result.append(r)

    return result, skipped_incomplete_pm2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positioning", action="append", required=True,
                    help="BLOCK|positioning.csv; use TRAIN/OOS_A-D only")
    ap.add_argument("--latest-sessions", type=int, default=90)
    ap.add_argument("--fixed-atm-time", default="09:20")
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output")
    a = ap.parse_args()

    specs = []
    all_dates = set()

    for spec in a.positioning:
        block, path = spec.split("|", 1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")
        specs.append((block, path))

        rows = read_csv(path)
        c = detect(rows)
        for r in rows:
            t = dt(r.get(c["timestamp"]))
            if t:
                all_dates.add(t.date().isoformat())

    latest_dates = sorted(all_dates)[-a.latest_sessions:]
    latest_set = set(latest_dates)

    rows = []
    skipped = 0

    for block, path in specs:
        x, s = build_block(block, path, latest_set, a.fixed_atm_time)
        rows.extend(x)
        skipped += s

    rows.sort(key=lambda r: (r["session_date"], r["timestamp"]))

    family_counts = Counter(r["pattern_family"] for r in rows)

    direction_summary = {}
    for family in sorted(family_counts):
        xs = [r for r in rows if r["pattern_family"] == family]
        direction_summary[family] = {
            "count": len(xs),
            "median_activity": sorted(r["m_activity"] for r in xs)[len(xs)//2] if xs else None,
            "forward_5m_positive_count": sum(
                1 for r in xs if r["forward_5m_points"] is not None and r["forward_5m_points"] > 0
            ),
            "forward_5m_negative_count": sum(
                1 for r in xs if r["forward_5m_points"] is not None and r["forward_5m_points"] < 0
            ),
            "forward_10m_positive_count": sum(
                1 for r in xs if r["forward_10m_points"] is not None and r["forward_10m_points"] > 0
            ),
            "forward_10m_negative_count": sum(
                1 for r in xs if r["forward_10m_points"] is not None and r["forward_10m_points"] < 0
            ),
            "forward_15m_positive_count": sum(
                1 for r in xs if r["forward_15m_points"] is not None and r["forward_15m_points"] > 0
            ),
            "forward_15m_negative_count": sum(
                1 for r in xs if r["forward_15m_points"] is not None and r["forward_15m_points"] < 0
            ),
        }

    result = {
        "research_version": VERSION,
        "scope": {
            "requested_latest_sessions": a.latest_sessions,
            "selected_session_count": len(latest_dates),
            "first_session": latest_dates[0] if latest_dates else None,
            "last_session": latest_dates[-1] if latest_dates else None,
            "blocks": sorted({b for b, _ in specs}),
            "forbidden_blocks": sorted(FORBIDDEN),
        },
        "primary_strength": {
            "source": "MOVING_ATM_PM2",
            "formula": "ABS(CE_DELTA) + ABS(PE_DELTA)",
            "same_physical_strikes_t_vs_t_minus_5": True,
            "full_five_strikes_required": True,
        },
        "secondary_context": {
            "fixed_atm_pm2": True,
            "fixed_atm_time": a.fixed_atm_time,
        },
        "checkpoint_count": len(rows),
        "skipped_incomplete_pm2_count": skipped,
        "pattern_family_counts": dict(family_counts),
        "pattern_family_outcomes": direction_summary,
        "rows": rows,
        "integrity": {
            "historical_only": True,
            "db_used": False,
            "current_day_used": False,
            "oos_e_f_g_h_used": False,
            "strategy_rule_changed": False,
            "paper_or_live_action": False,
        },
    }

    outp = Path(a.output)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    if a.csv_output:
        cp = Path(a.csv_output)
        cp.parent.mkdir(parents=True, exist_ok=True)
        if rows:
            fields = list(rows[0].keys())
            with cp.open("w", newline="", encoding="utf-8") as h:
                w = csv.DictWriter(h, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)

    print(json.dumps({
        "research_version": VERSION,
        "selected_session_count": len(latest_dates),
        "historical_range": [
            latest_dates[0] if latest_dates else None,
            latest_dates[-1] if latest_dates else None,
        ],
        "checkpoint_count": len(rows),
        "skipped_incomplete_pm2_count": skipped,
        "pattern_family_counts": dict(family_counts),
        "output": a.output,
        "csv_output": a.csv_output,
    }, indent=2))


if __name__ == "__main__":
    main()
