#!/usr/bin/env python3
"""
B FAMILY — V27 RUNNER PERSISTENCE / RECOVERY DIAGNOSTIC

Purpose
-------
Descriptive follow-up to V26.

Question:
What distinguishes temporary runner deterioration that later recovers from
deterioration that persists into the end of the canonical lifecycle?

This script uses the V26 minute timeline only. It does NOT define an exit rule,
search thresholds, or modify Family-B / V20 logic.

Per runner it measures:
- longest consecutive directional-VWAP weakening run
- longest consecutive "no new MFE" run
- longest consecutive joint deterioration run:
    drawdown_from_running_mfe_close > 0
    AND vwap_change_vs_prior_minute < 0
- count of joint deterioration episodes
- how many joint episodes later recover to a new MFE
- median / max minutes from episode end to new MFE
- terminal joint deterioration episode properties
- whether a new MFE occurs after the terminal episode

Definitions are intentionally sign-based / structural and contain no tuned
magnitude threshold.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1")
V26 = ROOT / "b-family-runner-deterioration-diagnostic-v26"

TIMELINE_IN = V26 / "runner-minute-timeline-v26.csv"

OUTDIR = ROOT / "b-family-runner-persistence-recovery-diagnostic-v27"
EVENT_OUT = OUTDIR / "runner-persistence-recovery-events-v27.csv"
EPISODE_OUT = OUTDIR / "runner-joint-deterioration-episodes-v27.csv"
REPORT_JSON = OUTDIR / "report-v27.json"
SUMMARY_TXT = OUTDIR / "summary-v27.txt"


def load_rows():
    if not TIMELINE_IN.exists():
        raise SystemExit(f"STOP: missing V26 timeline: {TIMELINE_IN}")
    with TIMELINE_IN.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit("STOP: V26 timeline is empty")
    return rows


def f(v):
    if v in (None, ""):
        return None
    return float(v)


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def consecutive_runs(rows, predicate):
    runs = []
    start = None
    bucket = []

    for row in rows:
        if predicate(row):
            if start is None:
                start = row["timestamp"]
                bucket = []
            bucket.append(row)
        else:
            if bucket:
                runs.append(bucket)
            start = None
            bucket = []

    if bucket:
        runs.append(bucket)

    return runs


def has_new_mfe_after(rows, end_idx, reference_mfe):
    for j in range(end_idx + 1, len(rows)):
        rmfe = f(rows[j]["running_mfe"])
        if rmfe is not None and rmfe > reference_mfe + 1e-9:
            return True, rows[j]
    return False, None


def analyze_session(rows):
    rows = sorted(rows, key=lambda r: r["timestamp"])

    # Add index for episode lookup.
    for i, row in enumerate(rows):
        row["_idx"] = i

    # VWAP weakening = strictly negative one-minute directional VWAP change.
    vwap_runs = consecutive_runs(
        rows,
        lambda r: (
            f(r["vwap_change_vs_prior_minute"]) is not None
            and f(r["vwap_change_vs_prior_minute"]) < 0
        ),
    )

    # No-new-MFE run: running MFE unchanged from prior minute.
    no_new_flags = []
    prior = None
    for row in rows:
        rmfe = f(row["running_mfe"])
        flag = prior is not None and rmfe is not None and rmfe <= prior + 1e-9
        no_new_flags.append(flag)
        if rmfe is not None:
            prior = rmfe

    no_new_runs = []
    bucket = []
    for row, flag in zip(rows, no_new_flags):
        if flag:
            bucket.append(row)
        else:
            if bucket:
                no_new_runs.append(bucket)
            bucket = []
    if bucket:
        no_new_runs.append(bucket)

    # Joint deterioration is sign-only: any close drawdown from running MFE
    # together with one-minute directional VWAP weakening.
    joint_runs = consecutive_runs(
        rows,
        lambda r: (
            f(r["drawdown_from_running_mfe_close"]) is not None
            and f(r["drawdown_from_running_mfe_close"]) > 0
            and f(r["vwap_change_vs_prior_minute"]) is not None
            and f(r["vwap_change_vs_prior_minute"]) < 0
        ),
    )

    episodes = []
    for n, run in enumerate(joint_runs, 1):
        start = run[0]
        end = run[-1]
        end_idx = end["_idx"]
        reference_mfe = f(end["running_mfe"]) or 0.0

        recovered, recovery_row = has_new_mfe_after(
            rows, end_idx, reference_mfe
        )

        recovery_minutes = None
        if recovered:
            recovery_minutes = (
                f(recovery_row["minutes_since_classification"])
                - f(end["minutes_since_classification"])
            )

        max_dd = max(
            f(x["drawdown_from_running_mfe_close"]) or 0.0
            for x in run
        )

        vwap_total_change = sum(
            f(x["vwap_change_vs_prior_minute"]) or 0.0
            for x in run
        )

        episodes.append({
            "validation_block": start.get("validation_block"),
            "session_date": start["session_date"],
            "direction": start["direction"],
            "episode_number": n,
            "start_timestamp": start["timestamp"],
            "end_timestamp": end["timestamp"],
            "start_minutes_since_classification": f(
                start["minutes_since_classification"]
            ),
            "end_minutes_since_classification": f(
                end["minutes_since_classification"]
            ),
            "duration_minutes": len(run),
            "max_drawdown_during_episode": max_dd,
            "vwap_total_change_during_episode": vwap_total_change,
            "running_mfe_at_episode_end": reference_mfe,
            "new_mfe_after_episode": recovered,
            "recovery_timestamp": (
                recovery_row["timestamp"] if recovery_row else None
            ),
            "minutes_episode_end_to_new_mfe": recovery_minutes,
        })

    terminal = episodes[-1] if episodes else None

    recovered_eps = [e for e in episodes if e["new_mfe_after_episode"]]
    failed_eps = [e for e in episodes if not e["new_mfe_after_episode"]]

    event = {
        "validation_block": rows[0].get("validation_block"),
        "session_date": rows[0]["session_date"],
        "direction": rows[0]["direction"],
        "classification_timestamp": rows[0]["classification_timestamp"],
        "structural_invalidation_timestamp": rows[0][
            "structural_invalidation_timestamp"
        ],
        "timeline_minutes": len(rows),
        "peak_running_mfe": max(f(r["running_mfe"]) or 0.0 for r in rows),
        "longest_vwap_weakening_run_minutes": max(
            (len(x) for x in vwap_runs), default=0
        ),
        "longest_no_new_mfe_run_minutes": max(
            (len(x) for x in no_new_runs), default=0
        ),
        "joint_deterioration_episode_count": len(episodes),
        "longest_joint_deterioration_run_minutes": max(
            (e["duration_minutes"] for e in episodes), default=0
        ),
        "recovered_joint_episode_count": len(recovered_eps),
        "nonrecovered_joint_episode_count": len(failed_eps),
        "terminal_joint_start_timestamp": (
            terminal["start_timestamp"] if terminal else None
        ),
        "terminal_joint_duration_minutes": (
            terminal["duration_minutes"] if terminal else None
        ),
        "terminal_joint_max_drawdown": (
            terminal["max_drawdown_during_episode"] if terminal else None
        ),
        "terminal_joint_vwap_total_change": (
            terminal["vwap_total_change_during_episode"] if terminal else None
        ),
        "new_mfe_after_terminal_joint_episode": (
            terminal["new_mfe_after_episode"] if terminal else None
        ),
    }

    return event, episodes


def main():
    print("B FAMILY — V27 RUNNER PERSISTENCE / RECOVERY DIAGNOSTIC")
    print("=" * 118)

    rows = load_rows()

    by_session = defaultdict(list)
    for row in rows:
        by_session[row["session_date"]].append(row)

    if len(by_session) != 11:
        raise SystemExit(
            f"STOP: expected 11 runner sessions from V26, got {len(by_session)}"
        )

    event_rows = []
    episode_rows = []

    for i, session in enumerate(sorted(by_session), 1):
        event, episodes = analyze_session(by_session[session])
        event_rows.append(event)
        episode_rows.extend(episodes)

        print(
            f"{i:2d}/11 {session} {event['direction']} "
            f"peak={fmt(event['peak_running_mfe'])} "
            f"VWAPweakMax={event['longest_vwap_weakening_run_minutes']}m "
            f"noNewMFEMax={event['longest_no_new_mfe_run_minutes']}m "
            f"jointEpisodes={event['joint_deterioration_episode_count']} "
            f"jointMax={event['longest_joint_deterioration_run_minutes']}m "
            f"terminalRecovered={event['new_mfe_after_terminal_joint_episode']}"
        )

    recovered = [
        e for e in episode_rows if str(e["new_mfe_after_episode"]).lower() == "true"
        or e["new_mfe_after_episode"] is True
    ]
    nonrecovered = [
        e for e in episode_rows if not (
            str(e["new_mfe_after_episode"]).lower() == "true"
            or e["new_mfe_after_episode"] is True
        )
    ]

    recovery_time = stats(
        e["minutes_episode_end_to_new_mfe"] for e in recovered
    )
    recovered_duration = stats(e["duration_minutes"] for e in recovered)
    failed_duration = stats(e["duration_minutes"] for e in nonrecovered)
    recovered_dd = stats(e["max_drawdown_during_episode"] for e in recovered)
    failed_dd = stats(e["max_drawdown_during_episode"] for e in nonrecovered)
    recovered_vwap = stats(
        e["vwap_total_change_during_episode"] for e in recovered
    )
    failed_vwap = stats(
        e["vwap_total_change_during_episode"] for e in nonrecovered
    )

    longest_vwap = stats(
        r["longest_vwap_weakening_run_minutes"] for r in event_rows
    )
    longest_joint = stats(
        r["longest_joint_deterioration_run_minutes"] for r in event_rows
    )
    longest_no_mfe = stats(
        r["longest_no_new_mfe_run_minutes"] for r in event_rows
    )

    terminal_recovered = sum(
        r["new_mfe_after_terminal_joint_episode"] is True
        for r in event_rows
    )
    terminal_nonrecovered = sum(
        r["new_mfe_after_terminal_joint_episode"] is False
        for r in event_rows
    )

    lines = [
        "B FAMILY — V27 RUNNER PERSISTENCE / RECOVERY DIAGNOSTIC",
        "=" * 118,
        f"runner_events={len(event_rows)}",
        f"joint_deterioration_episodes={len(episode_rows)}",
        f"recovered_episodes={len(recovered)}",
        f"nonrecovered_episodes={len(nonrecovered)}",
        "",
        "RUNNER-LEVEL PERSISTENCE",
        "-" * 118,
        f"longest VWAP weakening run: median={fmt(longest_vwap['median'])}m mean={fmt(longest_vwap['mean'])}m max={fmt(longest_vwap['max'])}m",
        f"longest joint deterioration run: median={fmt(longest_joint['median'])}m mean={fmt(longest_joint['mean'])}m max={fmt(longest_joint['max'])}m",
        f"longest no-new-MFE run: median={fmt(longest_no_mfe['median'])}m mean={fmt(longest_no_mfe['mean'])}m max={fmt(longest_no_mfe['max'])}m",
        "",
        "JOINT DETERIORATION EPISODE RECOVERY",
        "-" * 118,
        f"recovered episodes duration: n={recovered_duration['n']} median={fmt(recovered_duration['median'])}m mean={fmt(recovered_duration['mean'])}m",
        f"nonrecovered episodes duration: n={failed_duration['n']} median={fmt(failed_duration['median'])}m mean={fmt(failed_duration['mean'])}m",
        f"recovered episodes max drawdown: median={fmt(recovered_dd['median'])} mean={fmt(recovered_dd['mean'])}",
        f"nonrecovered episodes max drawdown: median={fmt(failed_dd['median'])} mean={fmt(failed_dd['mean'])}",
        f"recovered episodes VWAP total change: median={fmt(recovered_vwap['median'])} mean={fmt(recovered_vwap['mean'])}",
        f"nonrecovered episodes VWAP total change: median={fmt(failed_vwap['median'])} mean={fmt(failed_vwap['mean'])}",
        f"episode-end -> new MFE recovery time: n={recovery_time['n']} median={fmt(recovery_time['median'])}m mean={fmt(recovery_time['mean'])}m max={fmt(recovery_time['max'])}m",
        "",
        "TERMINAL EPISODES",
        "-" * 118,
        f"terminal episode later made new MFE: {terminal_recovered}/{len(event_rows)}",
        f"terminal episode had no later new MFE: {terminal_nonrecovered}/{len(event_rows)}",
        "",
        "EVENT DETAILS",
        "-" * 118,
    ]

    for r in event_rows:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"peak={fmt(r['peak_running_mfe'])} "
            f"vwapWeakMax={r['longest_vwap_weakening_run_minutes']}m "
            f"noNewMFEMax={r['longest_no_new_mfe_run_minutes']}m "
            f"jointEpisodes={r['joint_deterioration_episode_count']} "
            f"jointMax={r['longest_joint_deterioration_run_minutes']}m "
            f"terminalDur={r['terminal_joint_duration_minutes']}m "
            f"terminalDD={fmt(r['terminal_joint_max_drawdown'])} "
            f"terminalVWAPchg={fmt(r['terminal_joint_vwap_total_change'])} "
            f"terminalRecovered={r['new_mfe_after_terminal_joint_episode']}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Descriptive persistence/recovery diagnostic only.",
        "- No duration, drawdown, or VWAP magnitude is an exit threshold.",
        "- No exit rule is selected.",
        "- No threshold search or parameter optimization is performed.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- Structural invalidation remains the canonical lifecycle boundary.",
        "- Results use underlying NIFTY points, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_RUNNER_PERSISTENCE_RECOVERY_DIAGNOSTIC_V27",
        "runner_event_count": len(event_rows),
        "joint_episode_count": len(episode_rows),
        "recovered_episode_count": len(recovered),
        "nonrecovered_episode_count": len(nonrecovered),
        "runner_level": {
            "longest_vwap_weakening_run_minutes": longest_vwap,
            "longest_joint_deterioration_run_minutes": longest_joint,
            "longest_no_new_mfe_run_minutes": longest_no_mfe,
        },
        "episode_recovery": {
            "recovered_duration_minutes": recovered_duration,
            "nonrecovered_duration_minutes": failed_duration,
            "recovered_max_drawdown": recovered_dd,
            "nonrecovered_max_drawdown": failed_dd,
            "recovered_vwap_total_change": recovered_vwap,
            "nonrecovered_vwap_total_change": failed_vwap,
            "episode_end_to_new_mfe_minutes": recovery_time,
        },
        "terminal": {
            "later_new_mfe_count": terminal_recovered,
            "no_later_new_mfe_count": terminal_nonrecovered,
        },
        "events": event_rows,
        "episodes": episode_rows,
        "guards": {
            "exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_OUT, event_rows)
    write_csv(EPISODE_OUT, episode_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENT CSV   :", EVENT_OUT)
    print("EPISODE CSV :", EPISODE_OUT)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
