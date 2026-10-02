#!/usr/bin/env python3
"""
B FAMILY — V29 FROZEN RUNNER-EXIT CANDIDATE HISTORICAL OOS

This validates a newly frozen runner-exit hypothesis on a historical block
strictly before V23 (before 2025-02-06).

Frozen entry / runner classification
------------------------------------
Family-B entry: unchanged canonical detector.
V20 runner classifier:
  after +20 proof, wait fixed 10 minutes
  RUNNER_STRENGTHENING iff:
    net directional progress from +20 > 0
    AND directional futures-VWAP change > 0

New V29 exit candidate
----------------------
Applies ONLY after an event has already been classified
RUNNER_STRENGTHENING.

A joint deterioration episode START occurs causally when:
  drawdown_from_running_MFE_close > 0
  AND
  prior-minute directional futures-VWAP change < 0

At exactly +3 minutes from that episode start, trigger V29 EXIT if BOTH:
  1. directional futures-VWAP is below its level at episode start
  2. directional close move has failed to recover above its level
     at episode start

No magnitude threshold.
No optimization.
No same-episode persistence requirement.
If criteria are not met, continue and evaluate future episode starts.

Exit timestamp is the +3m checkpoint candle.
Exit move uses the underlying close of that checkpoint candle.

This is research-only. No production/runtime/order code changes.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

from market_lab import opening_candle_midpoint_framework_v1 as fw

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

MANIFEST = Path(
    "data/historical-validation/manifest-b-v29-pre-v23-100.json"
)
UNDERLYING_CSV = Path(
    "data/historical-evidence/b-v29-pre-v23-100-underlying.csv"
)
FUTURES_CSV = Path(
    "data/historical-evidence/b-v29-pre-v23-100-futures-vwap.csv"
)

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-v29-runner-exit-oos-100"
)

SESSION_CSV = OUTDIR / "session-summary-v29.csv"
EVENT_CSV = OUTDIR / "b-events-v29.csv"
RUNNER_CSV = OUTDIR / "runner-exit-validation-v29.csv"
REPORT_JSON = OUTDIR / "report-v29.json"
SUMMARY_TXT = OUTDIR / "summary-v29.txt"

EXPECTED_SESSIONS = 100
PROOF_POINTS = 20.0
V20_OBS_MINUTES = 10
V29_CONFIRM_MINUTES = 3
MILESTONES = (20, 30, 50, 75, 100)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_dt(ts):
    return datetime.fromisoformat(ts)


def minute_key(dt):
    return dt.isoformat()


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable_price(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def directional_vwap(direction, row):
    if not row or row.get("diff") is None:
        return None
    d = float(row["diff"])
    return d if direction == "BULLISH" else -d


def load_sessions():
    obj = json.loads(MANIFEST.read_text())
    sessions = sorted(x["session_date"] for x in obj["sessions"])

    if len(sessions) != EXPECTED_SESSIONS:
        raise SystemExit(
            f"STOP: manifest has {len(sessions)} sessions, expected {EXPECTED_SESSIONS}"
        )

    if len(set(sessions)) != EXPECTED_SESSIONS:
        raise SystemExit("STOP: duplicate session dates in manifest")

    if sessions[-1] >= "2025-02-06":
        raise SystemExit(
            f"STOP: V29 session overlaps V23 boundary: {sessions[-1]}"
        )

    return sessions


def load_underlying():
    rows = fw.load_csv(UNDERLYING_CSV)
    by_session = fw.underlying_by_session(rows)
    minute_maps = {}

    for session, minute_rows in by_session.items():
        u = {}
        for r in minute_rows:
            raw_ts = r.get("timestamp")
            if hasattr(raw_ts, "isoformat"):
                ts = raw_ts.isoformat()
            elif raw_ts:
                ts = str(raw_ts)
            else:
                raw_dt = r.get("dt")
                if hasattr(raw_dt, "isoformat"):
                    ts = raw_dt.isoformat()
                elif raw_dt:
                    ts = str(raw_dt)
                else:
                    raise ValueError("UNDERLYING_ROW_MISSING_TIMESTAMP")

            u[ts] = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume") or 0.0),
            }

        minute_maps[session] = u

    return by_session, minute_maps


def load_futures():
    out = defaultdict(dict)
    conflicts = 0

    with FUTURES_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            d = r["session_date"]
            ts = r["timestamp"]
            close = float(r["close"])
            vwap = (
                float(r["session_vwap"])
                if r.get("session_vwap") not in ("", None)
                else None
            )
            diff = close - vwap if vwap is not None else None

            rec = {
                "close": close,
                "vwap": vwap,
                "diff": diff,
            }

            if ts in out[d] and out[d][ts] != rec:
                conflicts += 1
                continue

            out[d][ts] = rec

    return dict(out), conflicts


def build_framework(session_date, minute_rows):
    bars = fw.aggregate_5m(minute_rows)
    red = fw.select_reference_bar(bars, "RED")
    green = fw.select_reference_bar(bars, "GREEN")
    events = []

    if red is not None:
        events.append(
            fw.build_event(
                block="V29_PRE_V23_OOS",
                session_date=session_date,
                minute_rows=minute_rows,
                bar=red,
                colour="RED",
                evidence_idx={},
                atm_idx={},
            )
        )

    if green is not None:
        events.append(
            fw.build_event(
                block="V29_PRE_V23_OOS",
                session_date=session_date,
                minute_rows=minute_rows,
                bar=green,
                colour="GREEN",
                evidence_idx={},
                atm_idx={},
            )
        )

    return events


def milestones(ev, u, canon):
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    invalid = ev.get("structural_invalidation_timestamp")
    out = {m: None for m in MILESTONES}

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not canon.is_trusted(ts):
            continue
        if invalid and ts >= invalid:
            break

        fav = directional(
            ev["direction"],
            entry,
            favorable_price(ev["direction"], u[ts]),
        )

        for m in MILESTONES:
            if out[m] is None and fav >= m:
                out[m] = ts

    return out


def classify_v20(ev, u, fut, proof_ts, canon):
    if proof_ts is None:
        return {
            "classification_status": "NOT_APPLICABLE_NO_PLUS20",
            "classification": None,
        }

    end_ts = minute_key(
        parse_dt(proof_ts) + timedelta(minutes=V20_OBS_MINUTES)
    )
    invalid = ev.get("structural_invalidation_timestamp")

    if not canon.is_trusted(end_ts):
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "OBSERVATION_END_AFTER_TRUSTED_CUTOFF",
        }

    if invalid and end_ts >= invalid:
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "STRUCTURAL_INVALIDATION_BEFORE_10M_BOUNDARY",
        }

    if end_ts not in u:
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "MISSING_UNDERLYING_AT_10M_BOUNDARY",
        }

    proof_v = directional_vwap(ev["direction"], fut.get(proof_ts))
    end_v = directional_vwap(ev["direction"], fut.get(end_ts))

    if proof_v is None or end_v is None:
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "MISSING_FUTURES_VWAP_AT_PROOF_OR_10M",
        }

    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    end_move = directional(
        ev["direction"],
        entry,
        u[end_ts]["close"],
    )

    net_progress = end_move - PROOF_POINTS
    vwap_change = end_v - proof_v

    label = (
        "RUNNER_STRENGTHENING"
        if net_progress > 0 and vwap_change > 0
        else "NORMAL_B"
    )

    return {
        "classification_status": "CLASSIFIED",
        "classification": label,
        "observation_end_timestamp": end_ts,
        "net_directional_progress_from_plus20": net_progress,
        "proof_directional_vwap_diff": proof_v,
        "end_directional_vwap_diff": end_v,
        "directional_vwap_change": vwap_change,
    }


def structural_metrics(ev, u):
    entry_ts = ev["entry_timestamp"]
    invalid = ev.get("structural_invalidation_timestamp")
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])

    peak = None
    peak_ts = None

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if invalid and ts >= invalid:
            break

        fav = directional(
            ev["direction"],
            entry,
            favorable_price(ev["direction"], u[ts]),
        )
        if peak is None or fav > peak:
            peak = fav
            peak_ts = ts

    invalid_close_move = None
    if invalid and invalid in u:
        invalid_close_move = directional(
            ev["direction"],
            entry,
            u[invalid]["close"],
        )

    giveback = None
    if peak is not None and invalid_close_move is not None:
        giveback = peak - invalid_close_move

    return {
        "structural_peak_mfe": peak,
        "structural_peak_timestamp": peak_ts,
        "structural_invalidation_close_move": invalid_close_move,
        "structural_peak_to_invalidation_giveback": giveback,
    }


def apply_v29_exit(ev, class_ts, u, fut, canon):
    """
    Scan causally from classification forward.

    Joint deterioration episode start:
      drawdown from running MFE using close > 0
      AND prior-minute directional futures-VWAP change < 0

    At +3m checkpoint:
      exit iff directional VWAP < episode-start directional VWAP
      AND directional close move <= episode-start directional close move

    If not exit, continue scanning future episode starts.
    """
    direction = ev["direction"]
    entry_ts = ev["entry_timestamp"]
    invalid = ev.get("structural_invalidation_timestamp")
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])

    timestamps = [
        ts for ts in sorted(u)
        if ts >= class_ts
        and canon.is_trusted(ts)
        and (not invalid or ts < invalid)
    ]

    if not timestamps:
        return {
            "v29_exit_triggered": False,
            "v29_exit_timestamp": None,
            "v29_exit_move": None,
            "v29_episode_start_timestamp": None,
            "v29_episode_start_move": None,
            "v29_episode_start_vwap": None,
            "v29_checkpoint_vwap": None,
            "v29_vwap_change": None,
            "v29_price_change_vs_episode_start": None,
            "v29_episode_count_evaluated": 0,
        }

    running_mfe = None
    prev_dvwap = None
    prior_joint = False
    evaluated_episode_starts = set()
    episode_count = 0

    for ts in timestamps:
        bar = u[ts]

        fav = directional(
            direction,
            entry,
            favorable_price(direction, bar),
        )
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        close_move = directional(direction, entry, bar["close"])
        drawdown = running_mfe - close_move

        dvwap = directional_vwap(direction, fut.get(ts))
        vwap_change_prior = (
            None if dvwap is None or prev_dvwap is None
            else dvwap - prev_dvwap
        )

        joint = (
            drawdown > 0
            and vwap_change_prior is not None
            and vwap_change_prior < 0
        )

        # Start only on FALSE -> TRUE transition.
        if joint and not prior_joint and ts not in evaluated_episode_starts:
            evaluated_episode_starts.add(ts)
            episode_count += 1

            checkpoint_ts = minute_key(
                parse_dt(ts) + timedelta(minutes=V29_CONFIRM_MINUTES)
            )

            # If structural lifecycle ends before checkpoint, do not evaluate.
            if invalid and checkpoint_ts >= invalid:
                pass
            elif not canon.is_trusted(checkpoint_ts):
                pass
            elif checkpoint_ts not in u or checkpoint_ts not in fut:
                pass
            else:
                start_vwap = dvwap
                end_vwap = directional_vwap(
                    direction,
                    fut.get(checkpoint_ts),
                )
                end_move = directional(
                    direction,
                    entry,
                    u[checkpoint_ts]["close"],
                )

                if start_vwap is not None and end_vwap is not None:
                    vwap_change = end_vwap - start_vwap
                    price_change = end_move - close_move

                    if vwap_change < 0 and price_change <= 0:
                        return {
                            "v29_exit_triggered": True,
                            "v29_exit_timestamp": checkpoint_ts,
                            "v29_exit_move": end_move,
                            "v29_episode_start_timestamp": ts,
                            "v29_episode_start_move": close_move,
                            "v29_episode_start_vwap": start_vwap,
                            "v29_checkpoint_vwap": end_vwap,
                            "v29_vwap_change": vwap_change,
                            "v29_price_change_vs_episode_start": price_change,
                            "v29_episode_count_evaluated": episode_count,
                        }

        prior_joint = joint
        if dvwap is not None:
            prev_dvwap = dvwap

    return {
        "v29_exit_triggered": False,
        "v29_exit_timestamp": None,
        "v29_exit_move": None,
        "v29_episode_start_timestamp": None,
        "v29_episode_start_move": None,
        "v29_episode_start_vwap": None,
        "v29_checkpoint_vwap": None,
        "v29_vwap_change": None,
        "v29_price_change_vs_episode_start": None,
        "v29_episode_count_evaluated": episode_count,
    }


def post_exit_diagnostics(ev, exit_ts, u):
    if not exit_ts:
        return {
            "post_exit_new_mfe": None,
            "post_exit_max_favorable": None,
        }

    direction = ev["direction"]
    entry = float(ev.get("entry_close") or u[ev["entry_timestamp"]]["close"])
    invalid = ev.get("structural_invalidation_timestamp")

    # Running peak at/through exit.
    pre_exit_peak = None
    for ts in sorted(u):
        if ts <= ev["entry_timestamp"]:
            continue
        if ts > exit_ts:
            break
        if invalid and ts >= invalid:
            break
        fav = directional(direction, entry, favorable_price(direction, u[ts]))
        pre_exit_peak = fav if pre_exit_peak is None else max(pre_exit_peak, fav)

    post_peak = None
    for ts in sorted(u):
        if ts <= exit_ts:
            continue
        if invalid and ts >= invalid:
            break
        fav = directional(direction, entry, favorable_price(direction, u[ts]))
        post_peak = fav if post_peak is None else max(post_peak, fav)

    new_mfe = (
        post_peak is not None
        and pre_exit_peak is not None
        and post_peak > pre_exit_peak + 1e-9
    )

    return {
        "post_exit_new_mfe": new_mfe,
        "post_exit_max_favorable": post_peak,
    }


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


def main():
    print("B FAMILY — V29 FROZEN RUNNER-EXIT CANDIDATE HISTORICAL OOS")
    print("=" * 118)

    canon = import_module(CANON, "canonical_b_v29")
    sessions = load_sessions()
    by_session_rows, underlying = load_underlying()
    futures, conflicts = load_futures()

    if conflicts:
        raise SystemExit(f"STOP: futures duplicate conflicts={conflicts}")

    session_rows = []
    event_rows = []
    runner_rows = []

    for n, session in enumerate(sessions, 1):
        minute_rows = by_session_rows.get(session, [])
        u = underlying.get(session, {})
        fut = futures.get(session, {})

        if len(u) != 375:
            raise SystemExit(
                f"STOP: {session} underlying rows={len(u)} expected=375"
            )
        if len(fut) != 375:
            raise SystemExit(
                f"STOP: {session} futures rows={len(fut)} expected=375"
            )

        framework = build_framework(session, minute_rows)
        detected = []

        for e in framework:
            b_event = canon.family_b_for_event(e, u, fut)
            if not b_event:
                continue

            ev = canon.measure_event(dict(b_event), u)
            ms = milestones(ev, u, canon)
            cls = classify_v20(ev, u, fut, ms[20], canon)

            row = dict(ev)
            for m in MILESTONES:
                row[f"plus{m}_timestamp"] = ms[m]
                row[f"reached_plus{m}"] = ms[m] is not None
            row.update(cls)
            row.update(structural_metrics(ev, u))

            event_rows.append(row)
            detected.append(row)

            if (
                cls.get("classification_status") == "CLASSIFIED"
                and cls.get("classification") == "RUNNER_STRENGTHENING"
            ):
                v29 = apply_v29_exit(
                    ev,
                    cls["observation_end_timestamp"],
                    u,
                    fut,
                    canon,
                )
                diag = post_exit_diagnostics(
                    ev,
                    v29.get("v29_exit_timestamp"),
                    u,
                )

                rr = dict(row)
                rr.update(v29)
                rr.update(diag)

                # Did the candidate exit before structural +75/+100 milestones?
                for m in (50, 75, 100):
                    mt = ms[m]
                    et = v29.get("v29_exit_timestamp")
                    rr[f"v29_exit_before_plus{m}"] = (
                        bool(et and mt and et < mt)
                    )

                # Difference versus structural invalidation close when available.
                structural_close = rr.get("structural_invalidation_close_move")
                exit_move = rr.get("v29_exit_move")
                rr["v29_minus_structural_close_move"] = (
                    None
                    if exit_move is None or structural_close is None
                    else float(exit_move) - float(structural_close)
                )

                runner_rows.append(rr)

        session_rows.append({
            "session_date": session,
            "underlying_rows": len(u),
            "futures_rows": len(fut),
            "framework_event_count": len(framework),
            "b_event_count": len(detected),
            "runner_strengthening_count": sum(
                r.get("classification") == "RUNNER_STRENGTHENING"
                for r in detected
            ),
        })

        print(
            f"{n:3d}/{len(sessions)} {session} "
            f"framework={len(framework)} "
            f"B={len(detected)} "
            f"RS={session_rows[-1]['runner_strengthening_count']}"
        )

    exits = [r for r in runner_rows if r["v29_exit_triggered"]]
    no_exits = [r for r in runner_rows if not r["v29_exit_triggered"]]

    lines = [
        "B FAMILY — V29 FROZEN RUNNER-EXIT CANDIDATE HISTORICAL OOS",
        "=" * 118,
        f"session_range={sessions[0]} -> {sessions[-1]}",
        f"sessions={len(sessions)}",
        f"framework_events={sum(r['framework_event_count'] for r in session_rows)}",
        f"b_events={len(event_rows)}",
        f"runner_strengthening_events={len(runner_rows)}",
        f"v29_exit_triggered={len(exits)}",
        f"v29_no_exit={len(no_exits)}",
        "",
        "V29 EXIT CANDIDATE",
        "-" * 118,
        "Joint deterioration start = drawdown>0 AND prior-minute directional VWAP change<0",
        "At +3m EXIT iff directional VWAP < episode-start VWAP",
        "AND directional close move <= episode-start directional close move",
        "",
        "RUNNER PRESERVATION",
        "-" * 118,
    ]

    for m in (50, 75, 100):
        structural_runners = [r for r in runner_rows if r[f"reached_plus{m}"]]
        cut = [r for r in structural_runners if r[f"v29_exit_before_plus{m}"]]
        lines.append(
            f"structural +{m} runners={len(structural_runners)} "
            f"V29 exited before +{m}={len(cut)} "
            f"preserved={len(structural_runners)-len(cut)}/{len(structural_runners)}"
        )

    new_mfe_after = [
        r for r in exits if r.get("post_exit_new_mfe") is True
    ]

    improvement = stats(
        r["v29_minus_structural_close_move"] for r in exits
    )
    exit_moves = stats(r["v29_exit_move"] for r in exits)
    structural_moves = stats(
        r["structural_invalidation_close_move"]
        for r in exits
    )

    lines += [
        "",
        "EXIT QUALITY",
        "-" * 118,
        f"candidate exits={len(exits)}",
        f"post-exit later new MFE={len(new_mfe_after)}/{len(exits)}",
        f"V29 exit move median={fmt(exit_moves['median'])} mean={fmt(exit_moves['mean'])}",
        f"structural invalidation close median={fmt(structural_moves['median'])} mean={fmt(structural_moves['mean'])}",
        f"V29 minus structural close median={fmt(improvement['median'])} mean={fmt(improvement['mean'])}",
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- V29 candidate was frozen before this historical OOS run.",
        "- No threshold search or parameter tuning in this validator.",
        "- Family-B entry unchanged.",
        "- V20 runner classifier unchanged.",
        "- Candidate applies only to RUNNER_STRENGTHENING events.",
        "- Underlying NIFTY points only; not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_V29_RUNNER_EXIT_OOS_100",
        "session_range": [sessions[0], sessions[-1]],
        "session_count": len(sessions),
        "framework_event_count": sum(
            r["framework_event_count"] for r in session_rows
        ),
        "b_event_count": len(event_rows),
        "runner_strengthening_event_count": len(runner_rows),
        "v29_exit_count": len(exits),
        "v29_no_exit_count": len(no_exits),
        "post_exit_new_mfe_count": len(new_mfe_after),
        "exit_move_stats": exit_moves,
        "structural_invalidation_close_stats": structural_moves,
        "v29_minus_structural_close_stats": improvement,
        "runner_preservation": {
            str(m): {
                "structural_reached": sum(
                    bool(r[f"reached_plus{m}"]) for r in runner_rows
                ),
                "v29_exit_before": sum(
                    bool(r[f"v29_exit_before_plus{m}"]) for r in runner_rows
                ),
            }
            for m in (50, 75, 100)
        },
        "candidate": {
            "confirm_minutes": V29_CONFIRM_MINUTES,
            "episode_start": (
                "drawdown_from_running_MFE_close>0 AND "
                "prior_minute_directional_VWAP_change<0"
            ),
            "exit_condition": (
                "directional_VWAP_at_plus3 < episode_start_directional_VWAP "
                "AND directional_close_move_at_plus3 <= episode_start_close_move"
            ),
        },
        "guards": {
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "threshold_search": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(SESSION_CSV, session_rows)
    write_csv(EVENT_CSV, event_rows)
    write_csv(RUNNER_CSV, runner_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("SESSION CSV :", SESSION_CSV)
    print("EVENT CSV   :", EVENT_CSV)
    print("RUNNER CSV  :", RUNNER_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
