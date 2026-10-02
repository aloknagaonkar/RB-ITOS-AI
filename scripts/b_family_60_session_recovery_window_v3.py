#!/usr/bin/env python3
"""
B FAMILY — 60-SESSION RECOVERY-WINDOW VALIDATION V3

Tests causal warning-management windows of 1/2/3/5 minutes.

Frozen B ENTRY logic is unchanged.

Policy under test
-----------------
After the first post-entry WARNING:
1. Keep observing for N completed 1m candles.
2. If B RECOVERY occurs within N minutes, retain the B lifecycle.
3. If midpoint invalidation happens before recovery/window expiry, exit on
   the invalidation close.
4. If no recovery occurs by the end of N minutes and midpoint is still intact,
   exit on the exact N-minute close.

This is NOT a production rule. It is a causal research simulation.

For each window the report measures:
- recovered warnings retained
- recovered warnings falsely exited
- no-recovery warnings exited before structural invalidation
- exit points vs B entry
- points saved/lost versus waiting for midpoint invalidation
- later favorable excursion sacrificed after a research exit
- bull/bear splits

Underlying NIFTY points only; not option-premium P&L.
"""

from __future__ import annotations

import csv
import glob
from collections import defaultdict
from datetime import datetime, timedelta
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
    / "b-family-60-session-recovery-window-v3"
)
OUT_CSV = OUT / "b-family-recovery-window-events-v3.csv"
OUT_TXT = OUT / "b-family-recovery-window-summary-v3.txt"

WINDOWS = (1, 2, 3, 5)


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def dt(v):
    return datetime.fromisoformat(v) if v else None


def dmove(direction, entry, later):
    if entry is None or later is None:
        return None
    return later - entry if direction == "BULLISH" else entry - later


def med(values):
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None


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
                        day, ts = r.get("session_date"), r.get("timestamp")
                        if not day or not ts:
                            continue
                        vals = {k: num(r.get(k)) for k in ("open","high","low","close")}
                        if vals["close"] is None:
                            continue
                        out.setdefault(day, {})[ts] = vals
            except Exception:
                pass
    return out


def favorable_extreme(direction, entry, bars):
    best = None
    for ts, bar in bars:
        level = bar["high"] if direction == "BULLISH" else bar["low"]
        if level is None:
            continue
        pts = dmove(direction, entry, level)
        if best is None or pts > best[0]:
            best = (pts, ts, level)
    return best if best else (None, None, None)


def main():
    if not V2.exists():
        raise FileNotFoundError(
            f"{V2}\nRun b_family_60_session_warning_recovery_v2.py first."
        )

    src = list(csv.DictReader(open(V2, newline="")))
    under = load_underlying()

    out_rows = []
    per_window = defaultdict(list)

    for r in src:
        day = r["session_date"]
        direction = r["direction"]
        entry_ts = r["entry_timestamp"]
        warning_ts = r["warning_timestamp"]
        recovery_ts = r.get("recovery_timestamp") or ""
        invalid_ts = r.get("invalidation_timestamp") or ""
        entry = num(r.get("entry_close"))
        source_mfe = num(r.get("source_mfe"))

        warning_dt = dt(warning_ts)
        daybars = under.get(day, {})

        for window in WINDOWS:
            deadline_dt = warning_dt + timedelta(minutes=window)
            deadline_ts = deadline_dt.isoformat()

            recovery_within = bool(
                recovery_ts
                and dt(recovery_ts) <= deadline_dt
                and (not invalid_ts or dt(recovery_ts) < dt(invalid_ts))
            )

            invalid_before_or_at_deadline = bool(
                invalid_ts and dt(invalid_ts) <= deadline_dt
            )

            action = None
            exit_ts = None
            retained = False

            if recovery_within:
                action = "RETAIN_RECOVERED"
                retained = True
            elif invalid_before_or_at_deadline:
                action = "EXIT_MIDPOINT_INVALIDATION"
                exit_ts = invalid_ts
            else:
                action = "EXIT_WINDOW_EXPIRED"
                exit_ts = deadline_ts

            exit_close = None
            exit_points = None
            if exit_ts:
                exit_close = daybars.get(exit_ts, {}).get("close")
                exit_points = dmove(direction, entry, exit_close)

            invalid_close = daybars.get(invalid_ts, {}).get("close") if invalid_ts else None
            invalid_points = dmove(direction, entry, invalid_close)

            points_saved_vs_invalidation = None
            if exit_points is not None and invalid_points is not None:
                points_saved_vs_invalidation = exit_points - invalid_points

            # Favorable excursion available AFTER a simulated early exit until
            # structural invalidation (or trusted session end if no invalidation).
            sacrificed_mfe = None
            post_exit_mfe = None
            post_exit_mfe_ts = None
            if exit_ts and exit_close is not None:
                future = [
                    (ts, bar)
                    for ts, bar in sorted(daybars.items())
                    if ts > exit_ts
                    and ts[11:16] <= "15:14"
                    and (not invalid_ts or ts <= invalid_ts)
                ]
                post_exit_mfe, post_exit_mfe_ts, _ = favorable_extreme(
                    direction, entry, future
                )
                if source_mfe is not None and exit_points is not None:
                    # Opportunity beyond the simulated exit's directional result.
                    sacrificed_mfe = max(0.0, source_mfe - exit_points)

            eventually_recovered = bool(recovery_ts)
            eventually_invalidated = bool(invalid_ts)

            classification = (
                "TRUE_RETAIN_RECOVERY"
                if retained and eventually_recovered
                else "FALSE_EXIT_RECOVERED_LATER"
                if (not retained and eventually_recovered)
                else "EARLY_EXIT_NO_RECOVERY"
                if (not retained and not eventually_recovered)
                else "OTHER"
            )

            rec = {
                "window_min": window,
                "session_date": day,
                "direction": direction,
                "entry_timestamp": entry_ts,
                "entry_close": entry,
                "warning_timestamp": warning_ts,
                "warning_points": num(r.get("warning_points")),
                "recovery_timestamp": recovery_ts or None,
                "eventually_recovered": eventually_recovered,
                "invalidation_timestamp": invalid_ts or None,
                "eventually_invalidated": eventually_invalidated,
                "recovery_within_window": recovery_within,
                "action": action,
                "exit_timestamp": exit_ts,
                "exit_close": exit_close,
                "exit_points": exit_points,
                "invalidation_points": invalid_points,
                "points_saved_vs_invalidation": points_saved_vs_invalidation,
                "source_mfe": source_mfe,
                "post_exit_mfe": post_exit_mfe,
                "post_exit_mfe_timestamp": post_exit_mfe_ts,
                "sacrificed_mfe_vs_source": sacrificed_mfe,
                "classification": classification,
            }
            out_rows.append(rec)
            per_window[window].append(rec)

    OUT.mkdir(parents=True, exist_ok=True)

    fields = [
        "window_min","session_date","direction","entry_timestamp","entry_close",
        "warning_timestamp","warning_points",
        "recovery_timestamp","eventually_recovered",
        "invalidation_timestamp","eventually_invalidated",
        "recovery_within_window","action",
        "exit_timestamp","exit_close","exit_points",
        "invalidation_points","points_saved_vs_invalidation",
        "source_mfe","post_exit_mfe","post_exit_mfe_timestamp",
        "sacrificed_mfe_vs_source","classification",
    ]

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    lines = []
    lines.append("B FAMILY — 60-SESSION RECOVERY-WINDOW VALIDATION V3")
    lines.append("=" * 118)
    lines.append("Frozen B entry logic unchanged.")
    lines.append("Policy tested: wait N minutes after warning for recovery; otherwise exit causally.")
    lines.append("")

    for window in WINDOWS:
        rows = per_window[window]
        retained = [r for r in rows if r["action"] == "RETAIN_RECOVERED"]
        false_exit = [r for r in rows if r["classification"] == "FALSE_EXIT_RECOVERED_LATER"]
        no_rec_exit = [r for r in rows if r["classification"] == "EARLY_EXIT_NO_RECOVERY"]
        saved = [r["points_saved_vs_invalidation"] for r in rows if r["points_saved_vs_invalidation"] is not None]
        exit_pts = [r["exit_points"] for r in rows if r["exit_points"] is not None]
        sacrificed = [r["sacrificed_mfe_vs_source"] for r in rows if r["sacrificed_mfe_vs_source"] is not None]

        lines.append(f"WINDOW = {window} MINUTE(S)")
        lines.append("-" * 118)
        lines.append(f"warning events: {len(rows)}")
        lines.append(f"recovered warnings retained: {len(retained)}")
        lines.append(f"recovered warnings falsely exited before later recovery: {len(false_exit)}")
        lines.append(f"no-recovery warnings exited: {len(no_rec_exit)}")
        lines.append(f"median simulated exit points: {med(exit_pts)}")
        lines.append(f"median points saved vs midpoint invalidation: {med(saved)}")
        lines.append(f"median favorable excursion sacrificed by simulated exit: {med(sacrificed)}")

        for side in ("BULLISH", "BEARISH"):
            sr = [r for r in rows if r["direction"] == side]
            sr_false = sum(r["classification"] == "FALSE_EXIT_RECOVERED_LATER" for r in sr)
            sr_keep = sum(r["classification"] == "TRUE_RETAIN_RECOVERY" for r in sr)
            sr_norec = sum(r["classification"] == "EARLY_EXIT_NO_RECOVERY" for r in sr)
            lines.append(
                f"{side}: events={len(sr)} retained_recovery={sr_keep} "
                f"false_exit_later_recovery={sr_false} no_recovery_exit={sr_norec}"
            )
        lines.append("")

    lines.append("EVENT DETAIL")
    lines.append("=" * 118)
    for window in WINDOWS:
        lines.append(f"\nWINDOW {window}m")
        for r in per_window[window]:
            lines.append(
                f"{r['session_date']} {r['direction']} "
                f"warn={r['warning_timestamp'][11:16]} "
                f"recovery={(r['recovery_timestamp'][11:16] if r['recovery_timestamp'] else '-')} "
                f"invalid={(r['invalidation_timestamp'][11:16] if r['invalidation_timestamp'] else '-')} "
                f"action={r['action']} "
                f"exit={(r['exit_timestamp'][11:16] if r['exit_timestamp'] else '-')} "
                f"exitPts={r['exit_points']} "
                f"savedVsInv={r['points_saved_vs_invalidation']} "
                f"MFE={r['source_mfe']} "
                f"class={r['classification']}"
            )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- Do not choose a window from this sample alone.")
    lines.append("- A false exit means recovery happened after the tested waiting window.")
    lines.append("- Saved-vs-invalidation is only available when structural invalidation exists.")
    lines.append("- MFE sacrificed is hindsight opportunity cost, not realized P&L.")
    lines.append("- Underlying NIFTY points are not CE/PE option-premium profit.")

    text = "\n".join(lines)
    OUT_TXT.write_text(text)
    print(text)
    print()
    print("CSV:", OUT_CSV)
    print("TXT:", OUT_TXT)


if __name__ == "__main__":
    main()
