#!/usr/bin/env python3
"""
B FAMILY — 60-SESSION WARNING AGE / PROFIT SEGMENTATION V4

Purpose
-------
Describe B warnings by:
- how long after entry the warning occurred;
- P&L-equivalent underlying NIFTY points at warning;
- maximum favorable excursion achieved BEFORE warning;
- how much of the event's source MFE had already occurred before warning;
- warning -> recovery time;
- post-warning MFE;
- whether a 3-minute recovery window would retain or exit the event.

Important
---------
- Frozen B entry definition is unchanged.
- No new production exit is created.
- No arbitrary early/late minute threshold is hard-coded.
- Warning age is summarized using DATA-DERIVED quartiles.
- Profit state at warning uses the natural zero-point split:
    warning_points > 0  -> PROFITABLE_AT_WARNING
    warning_points <= 0 -> NONPROFIT_AT_WARNING
- Underlying NIFTY points only, not option-premium P&L.
"""

from __future__ import annotations

import csv
import glob
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path("data/historical-evidence")
V2 = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-60-session-warning-recovery-v2"
    / "b-family-warning-recovery-events-v2.csv"
)

OUT = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-60-session-warning-age-profit-v4"
)
OUT_CSV = OUT / "b-family-warning-age-profit-events-v4.csv"
OUT_TXT = OUT / "b-family-warning-age-profit-summary-v4.txt"


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def ts(v):
    return datetime.fromisoformat(v) if v else None


def minutes(a, b):
    if not a or not b:
        return None
    return int((ts(b) - ts(a)).total_seconds() // 60)


def dmove(direction, entry, later):
    if entry is None or later is None:
        return None
    return later - entry if direction == "BULLISH" else entry - later


def load_underlying():
    out = {}
    seen = set()

    for pattern in (
        str(ROOT / "underlying-ohlc-*.csv"),
        str(ROOT / "**" / "underlying-ohlc-*.csv"),
    ):
        for p in sorted(glob.glob(pattern, recursive=True)):
            if p in seen:
                continue
            seen.add(p)
            try:
                with open(p, newline="") as fh:
                    for r in csv.DictReader(fh):
                        day = r.get("session_date")
                        stamp = r.get("timestamp")
                        if not day or not stamp:
                            continue
                        row = {
                            "open": num(r.get("open")),
                            "high": num(r.get("high")),
                            "low": num(r.get("low")),
                            "close": num(r.get("close")),
                        }
                        if row["close"] is not None:
                            out.setdefault(day, {})[stamp] = row
            except Exception:
                pass

    return out


def favorable_extreme(direction, entry, candles):
    """
    candles: iterable[(timestamp, OHLC dict)]
    Returns (directional points, timestamp, level)
    """
    best = None
    for stamp, bar in candles:
        level = bar["high"] if direction == "BULLISH" else bar["low"]
        if level is None:
            continue
        points = dmove(direction, entry, level)
        if best is None or points > best[0]:
            best = (points, stamp, level)

    return best if best else (None, None, None)


def percentile(values, p):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]

    idx = (len(vals) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def med(values):
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None


def fmt(v, digits=2):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    if not V2.exists():
        raise FileNotFoundError(
            f"{V2}\nRun b_family_60_session_warning_recovery_v2.py first."
        )

    source = list(csv.DictReader(open(V2, newline="")))
    under = load_underlying()

    rows = []

    for r in source:
        warning = r.get("warning_timestamp") or ""
        if not warning:
            continue

        day = r["session_date"]
        direction = r["direction"]
        entry_stamp = r["entry_timestamp"]
        recovery = r.get("recovery_timestamp") or ""
        invalid = r.get("invalidation_timestamp") or ""

        entry = num(r.get("entry_close"))
        warning_points = num(r.get("warning_points"))
        source_mfe = num(r.get("source_mfe"))

        bars = under.get(day, {})

        # Strictly before the warning candle.
        pre_warning_bars = [
            (stamp, bar)
            for stamp, bar in sorted(bars.items())
            if entry_stamp < stamp < warning
        ]

        # From warning onward, up to structural invalidation inclusive, or 15:14.
        post_warning_bars = [
            (stamp, bar)
            for stamp, bar in sorted(bars.items())
            if stamp >= warning
            and stamp[11:16] <= "15:14"
            and (not invalid or stamp <= invalid)
        ]

        pre_mfe, pre_mfe_ts, pre_mfe_level = favorable_extreme(
            direction, entry, pre_warning_bars
        )
        post_mfe, post_mfe_ts, post_mfe_level = favorable_extreme(
            direction, entry, post_warning_bars
        )

        pct_source_mfe_before_warning = None
        if (
            pre_mfe is not None
            and source_mfe is not None
            and source_mfe > 0
        ):
            pct_source_mfe_before_warning = 100.0 * pre_mfe / source_mfe

        entry_to_warning = minutes(entry_stamp, warning)
        warning_to_recovery = minutes(warning, recovery) if recovery else None
        warning_to_invalid = minutes(warning, invalid) if invalid else None

        recovered_within_3m = bool(
            recovery
            and warning_to_recovery is not None
            and warning_to_recovery <= 3
            and (not invalid or ts(recovery) < ts(invalid))
        )

        if recovered_within_3m:
            three_min_action = "RETAIN_RECOVERED"
        else:
            # If midpoint invalidated <=3m, causal action is invalidation.
            if invalid and warning_to_invalid is not None and warning_to_invalid <= 3:
                three_min_action = "EXIT_MIDPOINT_BEFORE_3M"
            else:
                three_min_action = "EXIT_AT_3M_IF_CLOSE_AVAILABLE"

        profit_state = (
            "PROFITABLE_AT_WARNING"
            if warning_points is not None and warning_points > 0
            else "NONPROFIT_AT_WARNING"
        )

        rows.append({
            "session_date": day,
            "direction": direction,
            "entry_timestamp": entry_stamp,
            "warning_timestamp": warning,
            "entry_to_warning_min": entry_to_warning,
            "warning_points": warning_points,
            "warning_profit_state": profit_state,
            "pre_warning_mfe_points": pre_mfe,
            "pre_warning_mfe_timestamp": pre_mfe_ts,
            "pct_source_mfe_achieved_before_warning": pct_source_mfe_before_warning,
            "recovery_timestamp": recovery or None,
            "warning_to_recovery_min": warning_to_recovery,
            "invalidation_timestamp": invalid or None,
            "warning_to_invalidation_min": warning_to_invalid,
            "post_warning_mfe_points": post_mfe,
            "post_warning_mfe_timestamp": post_mfe_ts,
            "source_mfe": source_mfe,
            "new_favorable_extreme_after_recovery":
                r.get("new_favorable_extreme_after_recovery"),
            "final_class": r.get("final_class"),
            "recovered_within_3m": recovered_within_3m,
            "three_min_candidate_action": three_min_action,
        })

    # Data-derived warning-age quartiles.
    ages = [r["entry_to_warning_min"] for r in rows]
    q1 = percentile(ages, 0.25)
    q2 = percentile(ages, 0.50)
    q3 = percentile(ages, 0.75)

    def age_band(age):
        if age is None:
            return "UNKNOWN"
        if age <= q1:
            return "Q1_EARLIEST"
        if age <= q2:
            return "Q2"
        if age <= q3:
            return "Q3"
        return "Q4_LATEST"

    for r in rows:
        r["warning_age_band"] = age_band(r["entry_to_warning_min"])

    OUT.mkdir(parents=True, exist_ok=True)

    fields = [
        "session_date","direction","entry_timestamp","warning_timestamp",
        "entry_to_warning_min","warning_age_band",
        "warning_points","warning_profit_state",
        "pre_warning_mfe_points","pre_warning_mfe_timestamp",
        "pct_source_mfe_achieved_before_warning",
        "recovery_timestamp","warning_to_recovery_min",
        "invalidation_timestamp","warning_to_invalidation_min",
        "post_warning_mfe_points","post_warning_mfe_timestamp",
        "source_mfe","new_favorable_extreme_after_recovery","final_class",
        "recovered_within_3m","three_min_candidate_action",
    ]

    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    lines = []
    lines.append("B FAMILY — 60-SESSION WARNING AGE / PROFIT SEGMENTATION V4")
    lines.append("=" * 118)
    lines.append(f"Warning events: {len(rows)}")
    lines.append(
        f"Warning-age quartiles (minutes from B entry): "
        f"Q1={fmt(q1,1)} median={fmt(q2,1)} Q3={fmt(q3,1)}"
    )
    lines.append("No hard-coded early/late threshold is used.")
    lines.append("")

    # Natural profit-state split.
    for state in ("NONPROFIT_AT_WARNING", "PROFITABLE_AT_WARNING"):
        g = [r for r in rows if r["warning_profit_state"] == state]
        if not g:
            continue
        lines.append(state)
        lines.append("-" * 118)
        lines.append(f"events: {len(g)}")
        lines.append(f"median entry->warning min: {fmt(med([x['entry_to_warning_min'] for x in g]),1)}")
        lines.append(f"median warning points: {fmt(med([x['warning_points'] for x in g]))}")
        lines.append(f"median pre-warning MFE: {fmt(med([x['pre_warning_mfe_points'] for x in g]))}")
        lines.append(
            f"median % source MFE achieved before warning: "
            f"{fmt(med([x['pct_source_mfe_achieved_before_warning'] for x in g]),1)}%"
        )
        lines.append(f"median post-warning MFE: {fmt(med([x['post_warning_mfe_points'] for x in g]))}")
        lines.append(
            f"recovered within 3m: "
            f"{sum(x['recovered_within_3m'] for x in g)}/{len(g)}"
        )
        lines.append("")

    # Data-derived age bands.
    lines.append("WARNING AGE BANDS — DATA-DERIVED QUARTILES")
    lines.append("=" * 118)
    for band in ("Q1_EARLIEST","Q2","Q3","Q4_LATEST"):
        g = [r for r in rows if r["warning_age_band"] == band]
        if not g:
            continue
        lines.append(
            f"{band}: n={len(g)} "
            f"medianAge={fmt(med([x['entry_to_warning_min'] for x in g]),1)}m "
            f"medianWarnPts={fmt(med([x['warning_points'] for x in g]))} "
            f"medianPreWarnMFE={fmt(med([x['pre_warning_mfe_points'] for x in g]))} "
            f"medianPostWarnMFE={fmt(med([x['post_warning_mfe_points'] for x in g]))} "
            f"recover<=3m={sum(x['recovered_within_3m'] for x in g)}/{len(g)}"
        )

    lines.append("")
    lines.append("EVENT DETAIL — SORTED BY WARNING AGE")
    lines.append("=" * 118)

    for r in sorted(rows, key=lambda x: x["entry_to_warning_min"]):
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"age={r['entry_to_warning_min']}m "
            f"band={r['warning_age_band']} "
            f"warnPts={fmt(r['warning_points'])} "
            f"preMFE={fmt(r['pre_warning_mfe_points'])} "
            f"prePct={fmt(r['pct_source_mfe_achieved_before_warning'],1)}% "
            f"recovery={(r['recovery_timestamp'][11:16] if r['recovery_timestamp'] else '-')} "
            f"w2r={r['warning_to_recovery_min']} "
            f"postMFE={fmt(r['post_warning_mfe_points'])} "
            f"3m={'KEEP' if r['recovered_within_3m'] else 'NO_RECOVERY_IN_3M'} "
            f"class={r['final_class']}"
        )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- V4 is descriptive segmentation, not a production exit rule.")
    lines.append("- Warning age bands are derived from this sample's quartiles.")
    lines.append("- The zero-point profit split is descriptive, not a new threshold optimization.")
    lines.append("- Do not freeze the 3-minute rule from the same 60-session sample.")
    lines.append("- Underlying NIFTY points are not option CE/PE premium profit.")

    summary = "\n".join(lines)
    OUT_TXT.write_text(summary)

    print(summary)
    print()
    print("CSV:", OUT_CSV)
    print("TXT:", OUT_TXT)


if __name__ == "__main__":
    main()
