#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-preconfirmed-boundary-v51"
)
EVENTS_CSV = OUTDIR / "events-v51.csv"
REPORT_JSON = OUTDIR / "report-v51.json"
SUMMARY_TXT = OUTDIR / "summary-v51.txt"

THRESHOLD = 5.0
MILESTONES = (20, 30, 50, 75, 100)
HORIZONS = (5, 10, 15, 30)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def minute_key(dt: datetime) -> str:
    return dt.isoformat()


def directional(direction: str, entry: float, price: float) -> float:
    return price - entry if direction == "BULLISH" else entry - price


def favorable_price(direction: str, bar: dict) -> float:
    return float(bar["high"]) if direction == "BULLISH" else float(bar["low"])


def adverse_price(direction: str, bar: dict) -> float:
    return float(bar["low"]) if direction == "BULLISH" else float(bar["high"])


def beyond_threshold(direction: str, diff: float) -> bool:
    return diff < -THRESHOLD if direction == "BEARISH" else diff > THRESHOLD


def mature_streak_minutes(direction: str, t0: str, fut: dict) -> int:
    dt = parse_dt(t0)
    streak = 0
    for i in range(0, 121):
        ts = minute_key(dt - timedelta(minutes=i))
        row = fut.get(ts)
        if row is None:
            break
        if not beyond_threshold(direction, float(row["diff"])):
            break
        streak += 1
    return streak


def first_midpoint_invalidation(direction, entry_ts, midpoint, u, is_trusted):
    for ts in sorted(u):
        if ts <= entry_ts or not is_trusted(ts):
            continue
        close = float(u[ts]["close"])
        if direction == "BEARISH" and close > midpoint:
            return ts
        if direction == "BULLISH" and close < midpoint:
            return ts
    return None


def measure(direction, entry_ts, midpoint, u, is_trusted):
    entry = float(u[entry_ts]["close"])
    invalid = first_midpoint_invalidation(direction, entry_ts, midpoint, u, is_trusted)

    window = []
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if invalid is not None and ts >= invalid:
            break
        if not is_trusted(ts):
            break
        window.append((ts, u[ts]))

    out = {
        "entry_close": entry,
        "structural_invalidation_timestamp": invalid,
        "terminal_type": "MIDPOINT_INVALIDATION" if invalid else "TRUSTED_CUTOFF_1514",
    }

    if window:
        mfe_vals = [
            (directional(direction, entry, favorable_price(direction, bar)), ts)
            for ts, bar in window
        ]
        mae_vals = [
            (directional(direction, entry, adverse_price(direction, bar)), ts)
            for ts, bar in window
        ]
        mfe, mfe_ts = max(mfe_vals, key=lambda x: x[0])
        mae, mae_ts = min(mae_vals, key=lambda x: x[0])
        out.update(mfe=mfe, mfe_timestamp=mfe_ts, mae=mae, mae_timestamp=mae_ts)
    else:
        out.update(mfe=None, mfe_timestamp=None, mae=None, mae_timestamp=None)

    dt0 = parse_dt(entry_ts)
    for h in HORIZONS:
        ts = minute_key(dt0 + timedelta(minutes=h))
        if ts in u and is_trusted(ts) and (invalid is None or ts < invalid):
            out[f"move_{h}m"] = directional(direction, entry, float(u[ts]["close"]))
        else:
            out[f"move_{h}m"] = None

    for m in MILESTONES:
        out[f"reached_{m}"] = bool(out["mfe"] is not None and out["mfe"] >= m)
    return out


def summarize(rows):
    if not rows:
        return {"n": 0}

    def nums(key):
        return [float(r[key]) for r in rows if r.get(key) not in (None, "")]

    def stat(key):
        xs = nums(key)
        return {
            "n": len(xs),
            "mean": mean(xs) if xs else None,
            "median": median(xs) if xs else None,
            "min": min(xs) if xs else None,
            "max": max(xs) if xs else None,
        }

    out = {
        "n": len(rows),
        "direction_counts": dict(Counter(r["direction"] for r in rows)),
        "mature_streak_minutes": stat("mature_streak_minutes"),
        "mfe": stat("mfe"),
        "mae": stat("mae"),
    }
    for h in HORIZONS:
        out[f"move_{h}m"] = stat(f"move_{h}m")
    for m in MILESTONES:
        count = sum(bool(r.get(f"reached_{m}")) for r in rows)
        out[f"reached_{m}"] = {"count": count, "pct": 100.0 * count / len(rows)}
    return out


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fmt(v):
    return "-" if v is None else f"{v:.2f}"


def main():
    c = import_module(CANON, "midpoint_canonical_v51")

    _, framework = c.load_framework()
    _, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    if dup_conflicts != 0:
        raise SystemExit(f"STOP: underlying duplicate conflicts={dup_conflicts}")

    rows = []
    missing = Counter()

    for e in framework:
        session = e.get("session_date")
        t0 = e.get("boundary_break_timestamp")
        if not session or not t0 or not c.is_trusted(t0):
            continue

        u = underlying.get(session)
        fut = futures.get(session)
        if not u or not fut:
            missing["missing_session_data"] += 1
            continue
        if t0 not in u or t0 not in fut:
            missing["missing_t0_data"] += 1
            continue

        direction = c.direction_for(e)
        levels = c.setup_levels(e)
        diff = float(fut[t0]["diff"])
        a0 = c.candidate_a(direction, t0, fut)

        if a0 is True:
            category = "FRESH_A_AT_BOUNDARY"
        elif a0 is False and beyond_threshold(direction, diff):
            category = "MATURE_A_AT_BOUNDARY"
        elif a0 is False:
            category = "NO_A_AT_BOUNDARY"
        else:
            category = "A_UNAVAILABLE"

        row = {
            "session_date": session,
            "direction": direction,
            "setup_type": e.get("setup_type"),
            "boundary_break_timestamp": t0,
            "reference_high": levels["high"],
            "reference_midpoint": levels["mid"],
            "reference_low": levels["low"],
            "boundary_entry_close": float(u[t0]["close"]),
            "futures_vwap_diff_at_boundary": diff,
            "candidate_a_at_boundary": a0,
            "boundary_category": category,
            "mature_streak_minutes": (
                mature_streak_minutes(direction, t0, fut)
                if category == "MATURE_A_AT_BOUNDARY"
                else 0
            ),
        }
        row.update(measure(direction, t0, levels["mid"], u, c.is_trusted))
        rows.append(row)

    mature = [r for r in rows if r["boundary_category"] == "MATURE_A_AT_BOUNDARY"]
    fresh = [r for r in rows if r["boundary_category"] == "FRESH_A_AT_BOUNDARY"]
    no_a = [r for r in rows if r["boundary_category"] == "NO_A_AT_BOUNDARY"]

    report = {
        "model": "MIDPOINT_PRECONFIRMED_BOUNDARY_RESEARCH_V51",
        "research_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "canonical_source": str(CANON),
        "threshold_points": THRESHOLD,
        "counts": dict(Counter(r["boundary_category"] for r in rows)),
        "missing": dict(missing),
        "combined": {
            "MATURE_A_AT_BOUNDARY": summarize(mature),
            "FRESH_A_AT_BOUNDARY": summarize(fresh),
            "NO_A_AT_BOUNDARY": summarize(no_a),
        },
        "mature_by_direction": {
            "BULLISH": summarize([r for r in mature if r["direction"] == "BULLISH"]),
            "BEARISH": summarize([r for r in mature if r["direction"] == "BEARISH"]),
        },
    }

    write_csv(EVENTS_CSV, rows)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT PRE-CONFIRMED / MATURE VWAP AT BOUNDARY — V51")
    lines.append("=" * 88)
    lines.append("RESEARCH ONLY — no production rule change")
    lines.append("")
    lines.append(f"framework boundary events = {len(rows)}")
    for k, v in sorted(report["counts"].items()):
        lines.append(f"{k:<28} = {v}")
    lines.append("")

    groups = [
        ("MATURE A AT BOUNDARY — COMBINED", mature),
        ("MATURE A AT BOUNDARY — BEARISH", [r for r in mature if r["direction"] == "BEARISH"]),
        ("MATURE A AT BOUNDARY — BULLISH", [r for r in mature if r["direction"] == "BULLISH"]),
        ("FRESH A AT BOUNDARY — COMPARISON", fresh),
    ]
    for label, bucket in groups:
        s = summarize(bucket)
        lines.append(label)
        lines.append("-" * 88)
        lines.append(f"n = {s.get('n', 0)}")
        if s.get("n", 0):
            lines.append(
                f"MFE mean={fmt(s['mfe']['mean'])} median={fmt(s['mfe']['median'])} "
                f"min={fmt(s['mfe']['min'])} max={fmt(s['mfe']['max'])}"
            )
            lines.append(
                f"MAE mean={fmt(s['mae']['mean'])} median={fmt(s['mae']['median'])} "
                f"min={fmt(s['mae']['min'])} max={fmt(s['mae']['max'])}"
            )
            for h in HORIZONS:
                x = s[f"move_{h}m"]
                lines.append(
                    f"{h:>2}m close move: n={x['n']} "
                    f"mean={fmt(x['mean'])} median={fmt(x['median'])}"
                )
            for m in MILESTONES:
                x = s[f"reached_{m}"]
                lines.append(f"+{m:<3} reached = {x['count']}/{s['n']} ({x['pct']:.1f}%)")
            if label.startswith("MATURE"):
                st = s["mature_streak_minutes"]
                lines.append(
                    f"mature VWAP streak at boundary: "
                    f"median={st['median']} mean={fmt(st['mean'])} "
                    f"min={st['min']} max={st['max']}"
                )
        lines.append("")

    lines.append("INTERPRETATION GUARD")
    lines.append("-" * 88)
    lines.append(
        "Retrospective scan on the already-used canonical historical population. "
        "Do not promote MATURE_A_AT_BOUNDARY to live entry from this result alone."
    )
    lines.append("Underlying-point MFE/MAE are opportunity geometry, not option premium P&L.")
    lines.append(
        "2026-09-28 is outside this canonical historical range and remains separate fresh evidence."
    )
    lines.append("")
    lines.append(f"EVENTS CSV  = {EVENTS_CSV}")
    lines.append(f"REPORT JSON = {REPORT_JSON}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
