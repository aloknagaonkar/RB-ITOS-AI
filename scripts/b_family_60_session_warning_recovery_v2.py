#!/usr/bin/env python3
"""
B FAMILY — 60-SESSION WARNING / RECOVERY ANALYSIS V2

Builds on V1 health-state validation.
Research-only diagnostics; frozen B entry logic is unchanged.

For every B event with a warning, reports:
- entry -> warning minutes
- warning -> recovery minutes
- warning -> invalidation minutes
- directional points at warning
- directional points at recovery
- directional points at invalidation
- maximum favorable excursion AFTER warning
- maximum adverse excursion AFTER warning
- maximum favorable excursion AFTER recovery
- whether recovery made a new favorable extreme vs the pre-warning period

Underlying NIFTY points only. No option-premium P&L.
"""

from __future__ import annotations

import csv
import glob
from datetime import datetime
from pathlib import Path

ROOT = Path("data/historical-evidence")
V1 = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-60-session-health-validation-v1"
    / "b-family-health-events-v1.csv"
)

OUT = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-60-session-warning-recovery-v2"
)
OUT_CSV = OUT / "b-family-warning-recovery-events-v2.csv"
OUT_TXT = OUT / "b-family-warning-recovery-summary-v2.txt"


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_ts(v):
    if not v:
        return None
    return datetime.fromisoformat(v)


def mins(a, b):
    if not a or not b:
        return None
    return int((parse_ts(b) - parse_ts(a)).total_seconds() // 60)


def dmove(direction, entry, later):
    if entry is None or later is None:
        return None
    return later - entry if direction == "BULLISH" else entry - later


def load_underlying():
    out = {}
    seen = set()
    for pat in (
        str(ROOT / "underlying-ohlc-*.csv"),
        str(ROOT / "**" / "underlying-ohlc-*.csv"),
    ):
        for p in sorted(glob.glob(pat, recursive=True)):
            if p in seen:
                continue
            seen.add(p)
            try:
                with open(p, newline="") as f:
                    for r in csv.DictReader(f):
                        d = r.get("session_date")
                        ts = r.get("timestamp")
                        if not d or not ts:
                            continue
                        vals = {k: num(r.get(k)) for k in ("open","high","low","close")}
                        if vals["close"] is None:
                            continue
                        out.setdefault(d, {})[ts] = vals
            except Exception:
                pass
    return out


def favorable_extreme(direction, entry, rows):
    """
    Return (points, timestamp, level) using intraminute high/low.
    """
    if entry is None or not rows:
        return None, None, None
    best = None
    for ts, bar in rows:
        level = bar["high"] if direction == "BULLISH" else bar["low"]
        if level is None:
            continue
        pts = dmove(direction, entry, level)
        if best is None or pts > best[0]:
            best = (pts, ts, level)
    return best if best else (None, None, None)


def adverse_extreme(direction, entry, rows):
    """
    Return most adverse directional excursion as negative points.
    """
    if entry is None or not rows:
        return None, None, None
    worst = None
    for ts, bar in rows:
        level = bar["low"] if direction == "BULLISH" else bar["high"]
        if level is None:
            continue
        pts = dmove(direction, entry, level)
        if worst is None or pts < worst[0]:
            worst = (pts, ts, level)
    return worst if worst else (None, None, None)


def main():
    if not V1.exists():
        raise FileNotFoundError(
            f"{V1}\nRun b_family_60_session_health_validation_v1.py first."
        )

    base = list(csv.DictReader(open(V1, newline="")))
    under = load_underlying()

    rows = []

    for r in base:
        warning = r.get("first_warning_timestamp") or ""
        if not warning:
            continue

        day = r["session_date"]
        direction = r["direction"]
        entry_ts = r["entry_timestamp"]
        entry = num(r.get("entry_close"))
        recovery = r.get("first_recovery_timestamp") or ""
        invalid = r.get("midpoint_invalidation_timestamp") or ""
        bars = under.get(day, {})

        warning_close = bars.get(warning, {}).get("close")
        recovery_close = bars.get(recovery, {}).get("close") if recovery else None
        invalid_close = bars.get(invalid, {}).get("close") if invalid else None

        # Analysis end is invalidation if present, otherwise trusted 15:14.
        all_after_warning = [
            (ts, bar)
            for ts, bar in sorted(bars.items())
            if ts >= warning
            and ts[11:16] <= "15:14"
            and (not invalid or ts <= invalid)
        ]

        after_recovery = [
            (ts, bar)
            for ts, bar in sorted(bars.items())
            if recovery
            and ts >= recovery
            and ts[11:16] <= "15:14"
            and (not invalid or ts <= invalid)
        ]

        pre_warning = [
            (ts, bar)
            for ts, bar in sorted(bars.items())
            if entry_ts < ts < warning
        ]

        fw_pts, fw_ts, fw_level = favorable_extreme(direction, entry, all_after_warning)
        aw_pts, aw_ts, aw_level = adverse_extreme(direction, entry, all_after_warning)
        fr_pts, fr_ts, fr_level = favorable_extreme(direction, entry, after_recovery)

        pre_pts, pre_ts, pre_level = favorable_extreme(direction, entry, pre_warning)

        new_extreme_after_recovery = None
        if recovery:
            if fr_pts is not None and pre_pts is not None:
                new_extreme_after_recovery = fr_pts > pre_pts
            elif fr_pts is not None:
                new_extreme_after_recovery = True

        out = {
            "session_date": day,
            "direction": direction,
            "entry_timestamp": entry_ts,
            "entry_close": entry,
            "warning_timestamp": warning,
            "warning_reason": r.get("first_warning_reason"),
            "entry_to_warning_min": mins(entry_ts, warning),
            "warning_close": warning_close,
            "warning_points": dmove(direction, entry, warning_close),
            "recovery_timestamp": recovery or None,
            "warning_to_recovery_min": mins(warning, recovery) if recovery else None,
            "recovery_close": recovery_close,
            "recovery_points": dmove(direction, entry, recovery_close),
            "invalidation_timestamp": invalid or None,
            "warning_to_invalidation_min": mins(warning, invalid) if invalid else None,
            "invalidation_close": invalid_close,
            "invalidation_points": dmove(direction, entry, invalid_close),
            "post_warning_mfe_points": fw_pts,
            "post_warning_mfe_timestamp": fw_ts,
            "post_warning_mfe_level": fw_level,
            "post_warning_mae_points": aw_pts,
            "post_warning_mae_timestamp": aw_ts,
            "post_warning_mae_level": aw_level,
            "post_recovery_mfe_points": fr_pts,
            "post_recovery_mfe_timestamp": fr_ts,
            "pre_warning_mfe_points": pre_pts,
            "new_favorable_extreme_after_recovery": new_extreme_after_recovery,
            "source_mfe": num(r.get("mfe")),
            "source_mae": num(r.get("mae")),
            "final_class": r.get("final_class"),
        }
        rows.append(out)

    OUT.mkdir(parents=True, exist_ok=True)

    fields = [
        "session_date","direction","entry_timestamp","entry_close",
        "warning_timestamp","warning_reason","entry_to_warning_min",
        "warning_close","warning_points",
        "recovery_timestamp","warning_to_recovery_min","recovery_close","recovery_points",
        "invalidation_timestamp","warning_to_invalidation_min",
        "invalidation_close","invalidation_points",
        "pre_warning_mfe_points",
        "post_warning_mfe_points","post_warning_mfe_timestamp","post_warning_mfe_level",
        "post_warning_mae_points","post_warning_mae_timestamp","post_warning_mae_level",
        "post_recovery_mfe_points","post_recovery_mfe_timestamp",
        "new_favorable_extreme_after_recovery",
        "source_mfe","source_mae","final_class",
    ]

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    recovered = [r for r in rows if r["recovery_timestamp"]]
    no_recovery = [r for r in rows if not r["recovery_timestamp"]]
    recovered_new_extreme = [
        r for r in recovered if r["new_favorable_extreme_after_recovery"] is True
    ]

    def med(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        n = len(vals)
        return vals[n//2] if n % 2 else (vals[n//2-1] + vals[n//2]) / 2

    text = []
    text.append("B FAMILY — 60-SESSION WARNING / RECOVERY ANALYSIS V2")
    text.append("=" * 110)
    text.append(f"Warning events analyzed: {len(rows)}")
    text.append(f"Recovered before invalidation/end: {len(recovered)}")
    text.append(f"No recovery: {len(no_recovery)}")
    text.append(
        f"Recovered events making NEW favorable extreme after recovery: "
        f"{len(recovered_new_extreme)}/{len(recovered)}"
    )
    text.append("")
    text.append("MEDIANS")
    text.append(
        f"entry -> warning minutes: "
        f"{med([r['entry_to_warning_min'] for r in rows])}"
    )
    text.append(
        f"warning -> recovery minutes (recovered only): "
        f"{med([r['warning_to_recovery_min'] for r in recovered])}"
    )
    text.append(
        f"warning -> invalidation minutes (where invalidated): "
        f"{med([r['warning_to_invalidation_min'] for r in rows])}"
    )
    text.append(
        f"points at warning: "
        f"{med([r['warning_points'] for r in rows])}"
    )
    text.append(
        f"post-warning MFE: "
        f"{med([r['post_warning_mfe_points'] for r in rows])}"
    )
    text.append(
        f"post-warning MAE: "
        f"{med([r['post_warning_mae_points'] for r in rows])}"
    )
    text.append("")
    text.append("EVENT DETAIL")
    text.append("-" * 110)

    for r in rows:
        text.append(
            f"{r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp'][11:16]} "
            f"warn={r['warning_timestamp'][11:16]} "
            f"e2w={r['entry_to_warning_min']}m "
            f"warnPts={r['warning_points']} "
            f"rec={(r['recovery_timestamp'][11:16] if r['recovery_timestamp'] else '-')} "
            f"w2r={r['warning_to_recovery_min']} "
            f"inv={(r['invalidation_timestamp'][11:16] if r['invalidation_timestamp'] else '-')} "
            f"w2i={r['warning_to_invalidation_min']} "
            f"postWarnMFE={r['post_warning_mfe_points']} "
            f"postWarnMAE={r['post_warning_mae_points']} "
            f"postRecMFE={r['post_recovery_mfe_points']} "
            f"newExtreme={r['new_favorable_extreme_after_recovery']} "
            f"class={r['final_class']}"
        )

    text.append("")
    text.append("IMPORTANT")
    text.append("- Warning is NOT treated as an exit.")
    text.append("- Recovery is descriptive; no new B rule is frozen.")
    text.append("- MFE/MAE here are underlying NIFTY excursion diagnostics.")
    text.append("- Use this to decide whether another validation pass is justified.")

    summary = "\n".join(text)
    OUT_TXT.write_text(summary)

    print(summary)
    print()
    print("CSV:", OUT_CSV)
    print("TXT:", OUT_TXT)


if __name__ == "__main__":
    main()
