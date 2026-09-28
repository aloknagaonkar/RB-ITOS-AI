#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import statistics
from datetime import datetime
from pathlib import Path

V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v61-reentry-necessity-exit-policy-comparison"
)
CASE_CSV = OUTDIR / "reentry-policy-cases-v61.csv"
SUMMARY_TXT = OUTDIR / "summary-v61.txt"
REPORT_JSON = OUTDIR / "report-v61.json"

CAP20_EVENTS = {"CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT"}
REENTRY_EVENTS = {
    "POST_CAP20_REENTRY_TRIGGERED",
    "POST_RESCUE_REENTRY_TRIGGERED",
    "REENTRY_COUNT_1",
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def dpoints(direction: str, a: float, b: float) -> float:
    return b - a if direction == "BULLISH" else a - b


def close_move(direction: str, entry: float, row: dict) -> float:
    return dpoints(direction, entry, float(row["close"]))


def favorable(direction: str, entry: float, row: dict) -> float:
    px = float(row["high"] if direction == "BULLISH" else row["low"])
    return dpoints(direction, entry, px)


def bars(u: dict, start: str, end: str | None = None):
    s = dt(start)
    e = dt(end) if end else None
    return [
        (ts, u[ts])
        for ts in sorted(u, key=dt)
        if dt(ts) >= s and (e is None or dt(ts) <= e)
    ]


def first(seg, event_types):
    types = {event_types} if isinstance(event_types, str) else set(event_types)
    return next((r for r in seg if r.get("event_type") in types), None)


def price(r):
    if r is None or r.get("underlying_price") is None:
        return None
    return float(r["underlying_price"])


def session_end_close(direction: str, entry_px: float, uday: dict):
    ts = max(uday, key=dt)
    return ts, close_move(direction, entry_px, uday[ts])


def policy_exit_fixed_proof(
    bs,
    direction,
    entry_px,
    proof_threshold,
    protected_close_level,
):
    armed = False
    for ts, row in bs:
        if favorable(direction, entry_px, row) >= proof_threshold:
            armed = True
        if armed:
            cm = close_move(direction, entry_px, row)
            if cm <= protected_close_level:
                return ts, cm, True
    return None, None, armed


def policy_exit_trailing(bs, direction, entry_px, proof_threshold=20.0, trail=20.0):
    armed = False
    running_mfe = float("-inf")
    for ts, row in bs:
        running_mfe = max(running_mfe, favorable(direction, entry_px, row))
        if running_mfe >= proof_threshold:
            armed = True
        if armed:
            cm = close_move(direction, entry_px, row)
            if cm <= running_mfe - trail:
                return ts, cm, True
    return None, None, armed


def fallback_to_terminal_or_session(
    exit_ts,
    exit_points,
    terminal,
    direction,
    reentry_px,
    uday,
):
    if exit_ts is not None:
        return exit_ts, exit_points, "POLICY_EXIT"

    terminal_px = price(terminal)
    if terminal is not None and terminal_px is not None:
        return (
            terminal["event_timestamp"],
            dpoints(direction, reentry_px, terminal_px),
            "STRUCTURAL_TERMINAL",
        )

    end_ts, end_points = session_end_close(direction, reentry_px, uday)
    return end_ts, end_points, "SESSION_END_MARK"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def main():
    v55 = load_module(V55, "v55_v61")
    v52 = load_module(V52, "v52_v61")
    canon = load_module(CANON, "canon_v61")
    v57 = load_module(V57, "v57_v61")

    rows = []
    all_cap20_count = 0
    reentry_count = 0

    for block in v52.BLOCKS:
        u, fut, framework = v55.load_block(block, v52, canon)

        for day in sorted(set(u).intersection(fut)):
            audit, open_active, active_family = v57.replay_session(day, u[day], fut[day])

            entries = [
                (i, r)
                for i, r in enumerate(audit)
                if r.get("event_type") in ("B_ENTRY", "E_ENTRY")
            ]

            for seq, (idx, en) in enumerate(entries, 1):
                next_idx = entries[seq][0] if seq < len(entries) else len(audit)
                seg = audit[idx:next_idx]

                rescue = first(seg, CAP20_EVENTS)
                if rescue is None:
                    continue

                all_cap20_count += 1

                richer = first(
                    seg,
                    {"POST_CAP20_REENTRY_TRIGGERED", "POST_RESCUE_REENTRY_TRIGGERED"},
                )
                reentry = richer or first(seg, REENTRY_EVENTS)

                direction = en["direction"]
                family = en["family"]
                entry_px = float(en["underlying_price"])
                rescue_px = price(rescue)
                terminal = first(seg, "STRUCTURAL_TERMINAL")
                terminal_px = price(terminal)

                first_leg = (
                    dpoints(direction, entry_px, rescue_px)
                    if rescue_px is not None else None
                )
                baseline_structural = (
                    dpoints(direction, entry_px, terminal_px)
                    if terminal_px is not None else None
                )

                # No-reentry policy: CAP20 exit is final.
                no_reentry_total = first_leg

                row = {
                    "block": block["name"],
                    "session_date": day,
                    "trade_seq": seq,
                    "family": family,
                    "direction": direction,
                    "entry_timestamp": en["event_timestamp"],
                    "rescue_timestamp": rescue["event_timestamp"],
                    "first_leg_points": first_leg,
                    "baseline_structural_points": baseline_structural,
                    "has_reentry": reentry is not None,
                    "no_reentry_total_points": no_reentry_total,
                }

                if reentry is None:
                    # For CAP20 cases where no re-entry triggered, every candidate
                    # equals CAP20-only because there is no second leg.
                    for key in (
                        "current_marked_total_points",
                        "protect10_after20_total_points",
                        "protect20_after30_total_points",
                        "breakeven_after20_total_points",
                        "trail20_after20_total_points",
                    ):
                        row[key] = first_leg
                    row.update({
                        "reentry_timestamp": "",
                        "reentry_price": None,
                        "terminal_timestamp": terminal["event_timestamp"] if terminal else "",
                        "current_second_leg_points": None,
                        "current_second_leg_strict": None,
                        "current_exit_basis": "NO_REENTRY_TRIGGER",
                        "protect10_after20_second_leg": None,
                        "protect20_after30_second_leg": None,
                        "breakeven_after20_second_leg": None,
                        "trail20_after20_second_leg": None,
                    })
                    rows.append(row)
                    continue

                reentry_count += 1
                reentry_px = price(reentry)
                if reentry_px is None:
                    continue

                end_ts = terminal["event_timestamp"] if terminal else max(u[day], key=dt)
                bs = bars(u[day], reentry["event_timestamp"], end_ts)

                # Current management:
                # strict value only when a structural terminal exists.
                current_strict = (
                    dpoints(direction, reentry_px, terminal_px)
                    if terminal_px is not None else None
                )
                if current_strict is not None:
                    current_marked = current_strict
                    current_basis = "STRUCTURAL_TERMINAL"
                else:
                    _, current_marked = session_end_close(direction, reentry_px, u[day])
                    current_basis = "SESSION_END_MARK"

                # Exploratory second-leg protection candidates. Re-entry timestamp
                # stays frozen; only exit management differs.
                p10_ts, p10_pts, p10_armed = policy_exit_fixed_proof(
                    bs, direction, reentry_px, 20.0, 10.0
                )
                p10_ts, p10_pts, p10_basis = fallback_to_terminal_or_session(
                    p10_ts, p10_pts, terminal, direction, reentry_px, u[day]
                )

                p20_ts, p20_pts, p20_armed = policy_exit_fixed_proof(
                    bs, direction, reentry_px, 30.0, 20.0
                )
                p20_ts, p20_pts, p20_basis = fallback_to_terminal_or_session(
                    p20_ts, p20_pts, terminal, direction, reentry_px, u[day]
                )

                be_ts, be_pts, be_armed = policy_exit_fixed_proof(
                    bs, direction, reentry_px, 20.0, 0.0
                )
                be_ts, be_pts, be_basis = fallback_to_terminal_or_session(
                    be_ts, be_pts, terminal, direction, reentry_px, u[day]
                )

                tr_ts, tr_pts, tr_armed = policy_exit_trailing(
                    bs, direction, reentry_px, proof_threshold=20.0, trail=20.0
                )
                tr_ts, tr_pts, tr_basis = fallback_to_terminal_or_session(
                    tr_ts, tr_pts, terminal, direction, reentry_px, u[day]
                )

                row.update({
                    "reentry_timestamp": reentry["event_timestamp"],
                    "reentry_price": reentry_px,
                    "terminal_timestamp": terminal["event_timestamp"] if terminal else "",
                    "current_second_leg_points": current_marked,
                    "current_second_leg_strict": current_strict,
                    "current_exit_basis": current_basis,

                    "protect10_after20_armed": p10_armed,
                    "protect10_after20_exit_timestamp": p10_ts,
                    "protect10_after20_exit_basis": p10_basis,
                    "protect10_after20_second_leg": p10_pts,

                    "protect20_after30_armed": p20_armed,
                    "protect20_after30_exit_timestamp": p20_ts,
                    "protect20_after30_exit_basis": p20_basis,
                    "protect20_after30_second_leg": p20_pts,

                    "breakeven_after20_armed": be_armed,
                    "breakeven_after20_exit_timestamp": be_ts,
                    "breakeven_after20_exit_basis": be_basis,
                    "breakeven_after20_second_leg": be_pts,

                    "trail20_after20_armed": tr_armed,
                    "trail20_after20_exit_timestamp": tr_ts,
                    "trail20_after20_exit_basis": tr_basis,
                    "trail20_after20_second_leg": tr_pts,

                    "current_marked_total_points": (
                        first_leg + current_marked if first_leg is not None else None
                    ),
                    "protect10_after20_total_points": (
                        first_leg + p10_pts if first_leg is not None else None
                    ),
                    "protect20_after30_total_points": (
                        first_leg + p20_pts if first_leg is not None else None
                    ),
                    "breakeven_after20_total_points": (
                        first_leg + be_pts if first_leg is not None else None
                    ),
                    "trail20_after20_total_points": (
                        first_leg + tr_pts if first_leg is not None else None
                    ),
                })
                rows.append(row)

    OUTDIR.mkdir(parents=True, exist_ok=True)

    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)

    with CASE_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    re = [r for r in rows if r["has_reentry"]]

    policy_defs = [
        ("CAP20_ONLY_NO_REENTRY", "no_reentry_total_points"),
        ("CURRENT_REENTRY_MARKED", "current_marked_total_points"),
        ("REENTRY_PROTECT10_AFTER20", "protect10_after20_total_points"),
        ("REENTRY_PROTECT20_AFTER30", "protect20_after30_total_points"),
        ("REENTRY_BREAKEVEN_AFTER20", "breakeven_after20_total_points"),
        ("REENTRY_TRAIL20_AFTER20", "trail20_after20_total_points"),
    ]

    no_reentry_sum = sum(
        r["no_reentry_total_points"]
        for r in rows
        if r["no_reentry_total_points"] is not None
    )

    policy_summary = []
    for name, key in policy_defs:
        vals_all = [r[key] for r in rows if r.get(key) is not None]
        vals_re = [r[key] for r in re if r.get(key) is not None]
        total = sum(vals_all) if vals_all else None
        re_total = sum(vals_re) if vals_re else None
        policy_summary.append({
            "policy": name,
            "cap20_cases": len(vals_all),
            "reentry_cases": len(vals_re),
            "total_points_all_cap20": total,
            "mean_points_all_cap20": mean(vals_all),
            "median_points_all_cap20": median(vals_all),
            "reentry_subset_total_points": re_total,
            "reentry_subset_mean_points": mean(vals_re),
            "reentry_subset_median_points": median(vals_re),
            "improvement_vs_cap20_only_all_cap20": (
                total - no_reentry_sum
                if total is not None and no_reentry_sum is not None else None
            ),
        })

    strict_current = [
        r["current_second_leg_strict"]
        for r in re
        if r.get("current_second_leg_strict") is not None
    ]

    report = {
        "model": "MIDPOINT_V61_REENTRY_NECESSITY_EXIT_POLICY_COMPARISON",
        "scope": "FIXED_CAP20_AND_FIXED_REENTRY_TIMESTAMPS",
        "cap20_cases": all_cap20_count,
        "reentry_cases": reentry_count,
        "current_reentry_structural_terminal_comparable": len(strict_current),
        "current_reentry_structural_second_leg_sum": sum(strict_current) if strict_current else None,
        "policies": policy_summary,
        "notes": [
            "No B/E entry rule changed.",
            "No CAP20 rule changed.",
            "No re-entry timestamp changed.",
            "CAP20_ONLY_NO_REENTRY is the direct test of whether re-entry is necessary.",
            "CURRENT_REENTRY_MARKED uses structural terminal when available and session-end close for open cases.",
            "Protected policies are exploratory screens only, not selected live rules.",
            "Underlying directional points only; no option P&L.",
        ],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT V61 — RE-ENTRY NECESSITY / SECOND-LEG EXIT COMPARISON")
    lines.append("=" * 112)
    lines.append("Fixed B/E entries, fixed CAP20 rescues, fixed re-entry timestamps; no entry tuning")
    lines.append("")
    lines.append(
        f"CAP20 cases={all_cap20_count} re-entry-triggered cases={reentry_count} "
        f"current structural-terminal comparable reentries={len(strict_current)}"
    )
    lines.append("")
    lines.append("POLICY COMPARISON — ALL CAP20 CASES")
    lines.append("-" * 112)
    for p in policy_summary:
        lines.append(
            f"{p['policy']}: total={p['total_points_all_cap20']} "
            f"mean={p['mean_points_all_cap20']} "
            f"median={p['median_points_all_cap20']} "
            f"delta_vs_CAP20_only={p['improvement_vs_cap20_only_all_cap20']}"
        )

    lines.append("")
    lines.append("RE-ENTRY SUBSET")
    lines.append("-" * 112)
    for p in policy_summary:
        lines.append(
            f"{p['policy']}: total={p['reentry_subset_total_points']} "
            f"mean={p['reentry_subset_mean_points']} "
            f"median={p['reentry_subset_median_points']}"
        )

    lines.append("")
    lines.append("STRICT CURRENT SECOND-LEG CHECK")
    lines.append("-" * 112)
    lines.append(
        f"completed structural-terminal reentries={len(strict_current)} "
        f"second-leg sum={sum(strict_current) if strict_current else None} "
        f"mean={mean(strict_current)} median={median(strict_current)}"
    )

    lines.append("")
    lines.append("CASE DETAIL")
    lines.append("-" * 112)
    for r in re:
        lines.append(
            f"{r['session_date']} {r['family']} {r['direction']} "
            f"CAP20_ONLY={r['no_reentry_total_points']} "
            f"CURRENT={r['current_marked_total_points']}({r['current_exit_basis']}) "
            f"P10_AFTER20={r['protect10_after20_total_points']} "
            f"P20_AFTER30={r['protect20_after30_total_points']} "
            f"BE_AFTER20={r['breakeven_after20_total_points']} "
            f"TRAIL20={r['trail20_after20_total_points']}"
        )

    lines.append("")
    lines.append("INTERPRETATION RULE")
    lines.append("-" * 112)
    lines.append(
        "If CAP20_ONLY remains stronger than every fixed-reentry policy, re-entry is not supported by this sample."
    )
    lines.append(
        "If a protected fixed-reentry policy improves on CAP20_ONLY, the trigger may be useful but needs separate validation on more re-entry events."
    )
    lines.append(
        "Do not select a production exit from these 9 re-entry cases alone."
    )
    lines.append("")
    lines.append(f"CASE CSV    = {CASE_CSV}")
    lines.append(f"REPORT JSON = {REPORT_JSON}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
