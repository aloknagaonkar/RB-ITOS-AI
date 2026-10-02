#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from market_lab.midpoint_strategy.boundary_classifier import MidpointBoundaryClassifierV55
from market_lab.midpoint_strategy.family_b_detector import (
    FamilyBDelayedDetector,
    FamilyBObservation,
)
from market_lab.midpoint_strategy.structure import structure_still_valid

V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-confirmed-trend-36-v56-5"
)
EVENT_CSV = OUTDIR / "event-level-v56-5.csv"
SESSION_CSV = OUTDIR / "session-summary-v56-5.csv"
REPORT_JSON = OUTDIR / "report-v56-5.json"
SUMMARY_TXT = OUTDIR / "summary-v56-5.txt"

BULLISH_18 = [
    "2026-05-18",
    "2026-05-20",
    "2026-05-25",
    "2026-06-02",
    "2026-06-12",
    "2026-06-16",
    "2026-06-17",
    "2026-06-18",
    "2026-06-24",
    "2026-07-06",
    "2026-07-10",
    "2026-07-13",
    "2026-07-17",
    "2026-07-27",
    "2026-07-29",
    "2026-08-03",
    "2026-08-25",
    "2026-09-02",
]

BEARISH_18 = [
    "2026-05-12",
    "2026-05-19",
    "2026-05-29",
    "2026-06-01",
    "2026-06-23",
    "2026-06-29",
    "2026-07-07",
    "2026-07-08",
    "2026-07-14",
    "2026-07-16",
    "2026-07-22",
    "2026-08-18",
    "2026-08-24",
    "2026-08-26",
    "2026-08-27",
    "2026-09-03",
    "2026-09-07",
    "2026-09-08",
]

COHORT = {d: "BULLISH" for d in BULLISH_18}
COHORT.update({d: "BEARISH" for d in BEARISH_18})


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def iso_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def observation(ts: str, urow: dict, frow: dict) -> FamilyBObservation:
    return FamilyBObservation(
        timestamp=ts,
        close=float(urow["close"]),
        futures_price=float(frow["close"]),
        futures_vwap=float(frow["vwap"]),
    )


def common_session_observations(u_day: dict, f_day: dict) -> list[FamilyBObservation]:
    return [
        observation(ts, u_day[ts], f_day[ts])
        for ts in sorted(set(u_day).intersection(f_day))
    ]


def ref_from_event(v55, ev):
    return v55.ref_from_event(ev)


def directional_points(direction: str, entry: float, current: float) -> float:
    if direction == "BULLISH":
        return current - entry
    if direction == "BEARISH":
        return entry - current
    raise ValueError(direction)


def favorable_points(direction: str, entry: float, urow: dict) -> float:
    px = float(urow["high"]) if direction == "BULLISH" else float(urow["low"])
    return directional_points(direction, entry, px)


def adverse_points(direction: str, entry: float, urow: dict) -> float:
    px = float(urow["low"]) if direction == "BULLISH" else float(urow["high"])
    return directional_points(direction, entry, px)


def terminal_invalidated(ref, close: float) -> bool:
    if ref.reference_type == "RED":
        return close > ref.midpoint
    return close < ref.midpoint


def b_entry_for_event(
    detector: FamilyBDelayedDetector,
    ref,
    boundary_obs: FamilyBObservation,
    observations: list[FamilyBObservation],
):
    history_to_boundary = [o for o in observations if iso_dt(o.timestamp) <= iso_dt(boundary_obs.timestamp)]
    watch = detector.start_watch(ref, boundary_obs, history_to_boundary)
    if not watch.active:
        return None, "NOT_STARTED"

    for current in observations:
        if iso_dt(current.timestamp) <= iso_dt(boundary_obs.timestamp):
            continue
        history = [o for o in observations if iso_dt(o.timestamp) <= iso_dt(current.timestamp)]
        d = detector.evaluate(watch, current, history)
        if d.result == "ENTRY":
            return current, "ENTRY"
        if d.result in ("EXPIRED", "INVALIDATED", "NO_B"):
            return None, d.result
    return None, "NO_ENTRY_BY_SESSION_END"


def entry_geometry(ref, entry_obs, u_day: dict):
    entry_ts = entry_obs.timestamp
    entry_dt = iso_dt(entry_ts)
    entry_px = float(entry_obs.close)

    future_ts = [
        ts for ts in sorted(u_day)
        if iso_dt(ts) > entry_dt
    ]

    mfe = 0.0
    mae = 0.0
    plus20 = False
    terminal_ts = None
    terminal_close = None
    terminal_reason = "SESSION_END"

    for ts in future_ts:
        row = u_day[ts]
        fav = favorable_points(ref.direction, entry_px, row)
        adv = adverse_points(ref.direction, entry_px, row)
        mfe = max(mfe, fav)
        mae = min(mae, adv)
        if fav >= 20.0:
            plus20 = True

        close = float(row["close"])
        if terminal_invalidated(ref, close):
            terminal_ts = ts
            terminal_close = close
            terminal_reason = "MIDPOINT_INVALIDATION"
            break

    if terminal_ts is None:
        if future_ts:
            terminal_ts = future_ts[-1]
            terminal_close = float(u_day[terminal_ts]["close"])
        else:
            terminal_ts = entry_ts
            terminal_close = entry_px

    terminal_points = directional_points(ref.direction, entry_px, terminal_close)
    minutes = max(
        0.0,
        (iso_dt(terminal_ts) - entry_dt).total_seconds() / 60.0,
    )

    return {
        "entry_price": entry_px,
        "terminal_timestamp": terminal_ts,
        "terminal_reason": terminal_reason,
        "terminal_directional_points": terminal_points,
        "mfe_points": mfe,
        "mae_points": mae,
        "plus20_reached": plus20,
        "minutes_to_terminal": minutes,
    }


def mean_or_none(xs):
    return statistics.mean(xs) if xs else None


def median_or_none(xs):
    return statistics.median(xs) if xs else None


def pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def summarize_entries(rows):
    entries = [r for r in rows if r["entry"]]
    aligned = [r for r in entries if r["alignment"] == "TREND_ALIGNED"]
    counter = [r for r in entries if r["alignment"] == "COUNTER_TREND"]
    mfe = [float(r["mfe_points"]) for r in entries]
    mae = [float(r["mae_points"]) for r in entries]
    terminal = [float(r["terminal_directional_points"]) for r in entries]

    return {
        "events": len(rows),
        "owner_E": sum(r["owner"] == "E" for r in rows),
        "owner_B": sum(r["owner"] == "B" for r in rows),
        "owner_OTHER_FRESH_A": sum(r["owner"] == "OTHER_FRESH_A" for r in rows),
        "entries_total": len(entries),
        "entries_E": sum(r["entry"] and r["family"] == "E" for r in rows),
        "entries_B": sum(r["entry"] and r["family"] == "B" for r in rows),
        "trend_aligned_entries": len(aligned),
        "counter_trend_entries": len(counter),
        "trend_aligned_pct": pct(len(aligned), len(entries)),
        "plus20_count": sum(bool(r["plus20_reached"]) for r in entries),
        "plus20_pct": pct(sum(bool(r["plus20_reached"]) for r in entries), len(entries)),
        "mfe_mean": mean_or_none(mfe),
        "mfe_median": median_or_none(mfe),
        "mae_mean": mean_or_none(mae),
        "mae_median": median_or_none(mae),
        "terminal_points_mean": mean_or_none(terminal),
        "terminal_points_median": median_or_none(terminal),
        "positive_terminal_count": sum(x > 0 for x in terminal),
        "positive_terminal_pct": pct(sum(x > 0 for x in terminal), len(terminal)),
    }


def write_csv(path: Path, rows: list[dict]):
    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    if len(BULLISH_18) != 18 or len(BEARISH_18) != 18:
        raise SystemExit("STOP: cohort must remain exactly 18 bullish + 18 bearish")
    if set(BULLISH_18).intersection(BEARISH_18):
        raise SystemExit("STOP: cohort overlap")

    v55 = import_module(V55, "v55_for_v56_5")
    v52 = import_module(V52, "v52_for_v56_5")
    canon = import_module(CANON, "canon_for_v56_5")

    block = next(b for b in v52.BLOCKS if b["name"] == "B4_2025-12-12_to_2026-09-08")
    u, fut, framework = v55.load_block(block, v52, canon)

    missing_u = sorted(set(COHORT) - set(u))
    missing_f = sorted(set(COHORT) - set(fut))
    if missing_u or missing_f:
        raise SystemExit(
            f"STOP: cohort source missing underlying={missing_u} futures={missing_f}"
        )

    classifier = MidpointBoundaryClassifierV55()
    detector = FamilyBDelayedDetector()

    event_rows = []
    for ev in framework:
        d = ev["session_date"]
        if d not in COHORT:
            continue

        ref = ref_from_event(v55, ev)
        observations = common_session_observations(u[d], fut[d])
        by_ts = {o.timestamp: o for o in observations}
        t0 = ev["boundary_break_timestamp"]
        if t0 not in by_ts:
            raise SystemExit(f"STOP: exact boundary observation missing {d} {t0}")

        boundary = by_ts[t0]
        history = [o for o in observations if iso_dt(o.timestamp) <= iso_dt(t0)]
        decision = classifier.classify(
            reference=ref,
            boundary_observation=boundary,
            history=history,
        )

        row = {
            "session_date": d,
            "confirmed_session_direction": COHORT[d],
            "event_direction": ev["direction"],
            "reference_type": ref.reference_type,
            "boundary_timestamp": t0,
            "owner": decision.owner,
            "owner_reason": decision.reason,
            "raw_futures_vwap_diff": decision.raw_futures_vwap_diff,
            "directional_vwap_diff": decision.directional_vwap_diff,
            "candidate_a_at_boundary": decision.candidate_a_at_boundary,
            "family": "",
            "entry": False,
            "entry_timestamp": "",
            "b_watch_result": "",
            "alignment": "",
            "entry_price": "",
            "terminal_timestamp": "",
            "terminal_reason": "",
            "terminal_directional_points": "",
            "mfe_points": "",
            "mae_points": "",
            "plus20_reached": "",
            "minutes_to_terminal": "",
        }

        entry_obs = None
        if decision.owner == "E":
            row["family"] = "E"
            row["entry"] = True
            row["entry_timestamp"] = t0
            entry_obs = boundary
        elif decision.owner == "B":
            row["family"] = "B"
            entry_obs, b_result = b_entry_for_event(
                detector, ref, boundary, observations
            )
            row["b_watch_result"] = b_result
            if entry_obs is not None:
                row["entry"] = True
                row["entry_timestamp"] = entry_obs.timestamp

        if row["entry"]:
            row["alignment"] = (
                "TREND_ALIGNED"
                if ev["direction"] == COHORT[d]
                else "COUNTER_TREND"
            )
            row.update(entry_geometry(ref, entry_obs, u[d]))

        event_rows.append(row)

    if not event_rows:
        raise SystemExit("STOP: no cohort events found")

    session_rows = []
    for d in sorted(COHORT):
        rows = [r for r in event_rows if r["session_date"] == d]
        s = summarize_entries(rows)
        session_rows.append({
            "session_date": d,
            "confirmed_session_direction": COHORT[d],
            **s,
        })

    bullish_rows = [r for r in event_rows if r["confirmed_session_direction"] == "BULLISH"]
    bearish_rows = [r for r in event_rows if r["confirmed_session_direction"] == "BEARISH"]
    combined = summarize_entries(event_rows)
    bullish = summarize_entries(bullish_rows)
    bearish = summarize_entries(bearish_rows)

    zero_entry_sessions = [
        r["session_date"] for r in session_rows if r["entries_total"] == 0
    ]

    report = {
        "model": "MIDPOINT_CONFIRMED_TREND_36_V56_5",
        "scope": "EVENT_LEVEL_COHORT_SCREEN_NOT_FULL_COORDINATOR_REPLAY",
        "frozen_cohort": {
            "bullish_18": BULLISH_18,
            "bearish_18": BEARISH_18,
        },
        "summaries": {
            "bullish_18": bullish,
            "bearish_18": bearish,
            "combined_36": combined,
        },
        "zero_entry_sessions": zero_entry_sessions,
        "notes": [
            "Exactly one V55 owner per structural boundary event.",
            "E enters immediately at boundary.",
            "B uses canonical delayed Family-B confirmation up to 10 minutes.",
            "Post-entry geometry is measured independently per event to adverse midpoint close or session end.",
            "This does not yet enforce the full one-active-reference coordinator across all events.",
            "CAP20/reentry/runner lifecycle is intentionally deferred to V57 full historical B+E lifecycle replay.",
            "No thresholds are tuned from this cohort result.",
        ],
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_CSV, event_rows)
    write_csv(SESSION_CSV, session_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT V56.5 — CONFIRMED TREND 36: B+E EVENT-LEVEL VALIDATION")
    lines.append("=" * 100)
    lines.append("Frozen cohort: 18 confirmed bullish + 18 confirmed bearish sessions")
    lines.append("NO RULE TUNING — diagnostic cohort screen")
    lines.append("")

    for label, s in [
        ("BULLISH_18", bullish),
        ("BEARISH_18", bearish),
        ("COMBINED_36", combined),
    ]:
        lines.append(label)
        lines.append("-" * 100)
        lines.append(
            f"events={s['events']} owner_E={s['owner_E']} owner_B={s['owner_B']} "
            f"owner_OTHER_FRESH_A={s['owner_OTHER_FRESH_A']}"
        )
        lines.append(
            f"entries={s['entries_total']} E_entries={s['entries_E']} B_entries={s['entries_B']} "
            f"trend_aligned={s['trend_aligned_entries']} counter_trend={s['counter_trend_entries']} "
            f"aligned_pct={s['trend_aligned_pct']}"
        )
        lines.append(
            f"+20={s['plus20_count']} ({s['plus20_pct']}%) "
            f"MFE mean/median={s['mfe_mean']}/{s['mfe_median']} "
            f"MAE mean/median={s['mae_mean']}/{s['mae_median']}"
        )
        lines.append(
            f"terminal points mean/median={s['terminal_points_mean']}/{s['terminal_points_median']} "
            f"positive_terminal={s['positive_terminal_count']} ({s['positive_terminal_pct']}%)"
        )
        lines.append("")

    lines.append(f"zero-entry sessions={len(zero_entry_sessions)} {zero_entry_sessions}")
    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- Event-level cohort screen only.")
    lines.append("- V57 next = full historical B+E coordinator/lifecycle replay.")
    lines.append("- V57 must enforce one active reference and shared +20/+10/DEGRADED/CAP20/reentry lifecycle.")
    lines.append("")
    lines.append(f"EVENT CSV   = {EVENT_CSV}")
    lines.append(f"SESSION CSV = {SESSION_CSV}")
    lines.append(f"REPORT JSON = {REPORT_JSON}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
