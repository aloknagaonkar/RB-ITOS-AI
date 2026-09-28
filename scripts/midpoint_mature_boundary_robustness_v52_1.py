#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
VALIDATION = Path("data/historical-validation")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

OUTDIR = ROOT / "hilega-pcr-oi-support-research-v1" / "midpoint-mature-boundary-robustness-v52_1"
EVENTS_CSV = OUTDIR / "events-v52_1.csv"
BLOCKS_CSV = OUTDIR / "blocks-v52_1.csv"
REPORT_JSON = OUTDIR / "report-v52_1.json"
SUMMARY_TXT = OUTDIR / "summary-v52_1.txt"

THRESHOLD = 5.0
HORIZONS = (5, 10, 15, 30)
MILESTONES = (20, 30, 50, 75, 100)
TRUSTED_END = "15:14"

BLOCKS = (
    {
        "name": "B1_2024-08-16_to_2025-02-05",
        "manifest": VALIDATION / "manifest-b-v29-pre-v23-100.json",
        "underlying": ROOT / "b-v29-pre-v23-100-underlying.csv",
        "futures": ROOT / "b-v29-pre-v23-100-futures-vwap.csv",
        "start": "2024-08-16",
        "end": "2025-02-05",
    },
    {
        "name": "B2_2025-02-06_to_2025-07-16",
        "manifest": VALIDATION / "manifest-b-v23-pre-v22-100.json",
        "underlying": ROOT / "b-v23-pre-v22-100-underlying.csv",
        "futures": ROOT / "b-v23-pre-v22-100-futures-vwap.csv",
        "start": "2025-02-06",
        "end": "2025-07-16",
    },
    {
        "name": "B3_2025-07-17_to_2025-12-11",
        "manifest": VALIDATION / "manifest-b-v22-untouched-100.json",
        "underlying": ROOT / "b-v22-untouched-100-underlying.csv",
        "futures": ROOT / "b-v22-untouched-100-futures-vwap.csv",
        "start": "2025-07-17",
        "end": "2025-12-11",
    },
    {
        "name": "B4_2025-12-12_to_2026-09-08",
        "manifest": None,
        "underlying": None,
        "futures": ROOT / "midpoint-v2-nifty-futures-vwap-v1-all180.csv",
        "start": "2025-12-12",
        "end": "2026-09-08",
    },
)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_csv(path: Path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def parse_dt(s: str):
    return datetime.fromisoformat(s)


def minute_key(dt: datetime):
    return dt.isoformat()


def trusted(ts: str):
    return ts[11:16] <= TRUSTED_END


def directional(direction: str, entry: float, price: float):
    return price - entry if direction == "BULLISH" else entry - price


def beyond_threshold(direction: str, diff: float):
    return diff < -THRESHOLD if direction == "BEARISH" else diff > THRESHOLD


def candidate_a(direction: str, at_ts: str, fut: dict[str, dict]):
    cur = fut.get(at_ts)
    if cur is None:
        return None
    dt = parse_dt(at_ts)
    vals = []
    for i in range(5, -1, -1):
        row = fut.get(minute_key(dt - timedelta(minutes=i)))
        if row is not None:
            vals.append(float(row["diff"]))
    if not vals:
        return None

    d = float(cur["diff"])
    if direction == "BEARISH":
        return d < -THRESHOLD and any(x >= -THRESHOLD for x in vals)
    return d > THRESHOLD and any(x <= THRESHOLD for x in vals)


def load_manifest_sessions(path: Path):
    obj = json.loads(path.read_text())
    sessions = sorted(x["session_date"] for x in obj["sessions"])
    if len(sessions) != 100 or len(set(sessions)) != 100:
        raise SystemExit(f"STOP: {path} does not contain exactly 100 unique sessions")
    return sessions


def load_explicit_underlying(path: Path, sessions: set[str]):
    by = defaultdict(dict)
    conflicts = 0
    for r in load_csv(path):
        d = r.get("session_date")
        ts = r.get("timestamp")
        if d not in sessions or not ts or not trusted(ts):
            continue
        rec = {
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        old = by[d].get(ts)
        if old is not None and old != rec:
            conflicts += 1
            continue
        by[d][ts] = rec
    return dict(by), conflicts


def load_explicit_futures(path: Path, sessions: set[str]):
    by = defaultdict(dict)
    conflicts = 0
    for r in load_csv(path):
        d = r.get("session_date")
        ts = r.get("timestamp")
        if d not in sessions or not ts or not trusted(ts):
            continue
        close = float(r["close"])
        raw_vwap = r.get("session_vwap")
        if raw_vwap in ("", None):
            raw_vwap = r.get("vwap")
        if raw_vwap in ("", None):
            continue
        vwap = float(raw_vwap)
        rec = {"close": close, "vwap": vwap, "diff": close - vwap}
        old = by[d].get(ts)
        if old is not None and (
            abs(old["close"] - rec["close"]) > 1e-9
            or abs(old["vwap"] - rec["vwap"]) > 1e-6
        ):
            conflicts += 1
            continue
        by[d][ts] = rec
    return dict(by), conflicts


def aggregate_5m(session: str, u: dict[str, dict]):
    """
    Exact clock buckets 09:15-09:19, 09:20-09:24, ...
    Only complete 5-minute buckets are emitted.
    """
    rows = []
    start = datetime.fromisoformat(f"{session}T09:15:00+05:30")
    end = datetime.fromisoformat(f"{session}T15:14:00+05:30")
    cur = start
    while cur <= end:
        ts_list = [minute_key(cur + timedelta(minutes=i)) for i in range(5)]
        if all(ts in u for ts in ts_list):
            bars = [u[ts] for ts in ts_list]
            rows.append({
                "start": ts_list[0],
                "end": ts_list[-1],
                "open": float(bars[0]["open"]),
                "high": max(float(x["high"]) for x in bars),
                "low": min(float(x["low"]) for x in bars),
                "close": float(bars[-1]["close"]),
            })
        cur += timedelta(minutes=5)
    return rows


def build_framework_for_session(session: str, u: dict[str, dict]):
    """
    Frozen opening framework:
    - ignore the 09:15-09:19 5m candle
    - first later RED 5m candle defines RED reference
    - first later GREEN 5m candle defines GREEN reference
    - require a 1m close through midpoint first
    - then first later/equal-sequence 1m close through original boundary
    """
    bars5 = aggregate_5m(session, u)
    refs = {}

    for b in bars5:
        if b["start"][11:16] == "09:15":
            continue
        if "RED" not in refs and b["close"] < b["open"]:
            refs["RED"] = b
        if "GREEN" not in refs and b["close"] > b["open"]:
            refs["GREEN"] = b
        if len(refs) == 2:
            break

    out = []
    for ref_type, ref in refs.items():
        high = float(ref["high"])
        low = float(ref["low"])
        mid = (high + low) / 2.0
        direction = "BEARISH" if ref_type == "RED" else "BULLISH"
        setup_type = "RED_BREAK" if ref_type == "RED" else "GREEN_BREAK"

        midpoint_seen = False
        boundary_ts = None
        for ts in sorted(u):
            if ts <= ref["end"] or not trusted(ts):
                continue
            close = float(u[ts]["close"])

            if not midpoint_seen:
                if ref_type == "RED" and close < mid:
                    midpoint_seen = True
                elif ref_type == "GREEN" and close > mid:
                    midpoint_seen = True

            if midpoint_seen:
                if ref_type == "RED" and close < low:
                    boundary_ts = ts
                    break
                if ref_type == "GREEN" and close > high:
                    boundary_ts = ts
                    break

        if boundary_ts is not None:
            out.append({
                "session_date": session,
                "direction": direction,
                "setup_type": setup_type,
                "boundary_break_timestamp": boundary_ts,
                "reference_high": high,
                "reference_midpoint": mid,
                "reference_low": low,
                "reference_start_timestamp": ref["start"],
                "reference_end_timestamp": ref["end"],
            })
    return out


def event_key(e: dict):
    return (
        e["session_date"],
        e["direction"],
        e["boundary_break_timestamp"],
        round(float(e["reference_high"]), 8),
        round(float(e["reference_midpoint"]), 8),
        round(float(e["reference_low"]), 8),
    )


def canonical_parity_check(canon, b4_u: dict):
    _, canonical_events = canon.load_framework()
    canonical = [
        e for e in canonical_events
        if "2025-12-12" <= e["session_date"] <= "2026-09-08"
        and e.get("boundary_break_timestamp")
    ]

    rebuilt = []
    for d in sorted(b4_u):
        if "2025-12-12" <= d <= "2026-09-08":
            rebuilt.extend(build_framework_for_session(d, b4_u[d]))

    ckeys = {event_key({
        "session_date": e["session_date"],
        "direction": canon.direction_for(e),
        "boundary_break_timestamp": e["boundary_break_timestamp"],
        "reference_high": float(e["reference_high"]),
        "reference_midpoint": float(e["reference_midpoint"]),
        "reference_low": float(e["reference_low"]),
    }) for e in canonical}
    rkeys = {event_key(e) for e in rebuilt}

    missing = sorted(ckeys - rkeys)
    extra = sorted(rkeys - ckeys)

    print(f"canonical framework events = {len(ckeys)}")
    print(f"rebuilt framework events   = {len(rkeys)}")
    print(f"framework missing          = {len(missing)}")
    print(f"framework extra            = {len(extra)}")

    if missing or extra:
        print("First missing:", missing[:3])
        print("First extra  :", extra[:3])
        raise SystemExit("STOP: deterministic framework builder does not match canonical B4")

    return rebuilt


def mature_streak(direction: str, t0: str, fut: dict[str, dict]):
    dt = parse_dt(t0)
    n = 0
    for i in range(121):
        ts = minute_key(dt - timedelta(minutes=i))
        row = fut.get(ts)
        if row is None or not beyond_threshold(direction, float(row["diff"])):
            break
        n += 1
    return n


def first_midpoint_invalidation(direction, entry_ts, midpoint, u):
    for ts in sorted(u):
        if ts <= entry_ts or not trusted(ts):
            continue
        c = float(u[ts]["close"])
        if direction == "BEARISH" and c > midpoint:
            return ts
        if direction == "BULLISH" and c < midpoint:
            return ts
    return None


def measure(ev, u):
    direction = ev["direction"]
    entry_ts = ev["boundary_break_timestamp"]
    midpoint = float(ev["reference_midpoint"])
    entry = float(u[entry_ts]["close"])
    invalid = first_midpoint_invalidation(direction, entry_ts, midpoint, u)

    window = []
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if invalid is not None and ts >= invalid:
            break
        if not trusted(ts):
            break
        window.append((ts, u[ts]))

    mfe = mae = None
    if window:
        mfe = max(
            directional(
                direction,
                entry,
                float(bar["high"]) if direction == "BULLISH" else float(bar["low"]),
            )
            for _, bar in window
        )
        mae = min(
            directional(
                direction,
                entry,
                float(bar["low"]) if direction == "BULLISH" else float(bar["high"]),
            )
            for _, bar in window
        )

    out = {
        "entry_close": entry,
        "structural_invalidation_timestamp": invalid,
        "mfe": mfe,
        "mae": mae,
    }

    dt0 = parse_dt(entry_ts)
    for h in HORIZONS:
        ts = minute_key(dt0 + timedelta(minutes=h))
        if ts in u and trusted(ts) and (invalid is None or ts < invalid):
            out[f"move_{h}m"] = directional(direction, entry, float(u[ts]["close"]))
        else:
            out[f"move_{h}m"] = None

    for m in MILESTONES:
        out[f"reached_{m}"] = bool(mfe is not None and mfe >= m)
    return out


def stats(rows):
    if not rows:
        return {"n": 0}

    def vals(k):
        return [float(r[k]) for r in rows if r.get(k) not in (None, "")]

    def s(k):
        x = vals(k)
        return {
            "n": len(x),
            "mean": mean(x) if x else None,
            "median": median(x) if x else None,
            "min": min(x) if x else None,
            "max": max(x) if x else None,
        }

    out = {
        "n": len(rows),
        "bull": sum(r["direction"] == "BULLISH" for r in rows),
        "bear": sum(r["direction"] == "BEARISH" for r in rows),
        "mfe": s("mfe"),
        "mae": s("mae"),
        "mature_streak": s("mature_streak_minutes"),
    }
    for h in HORIZONS:
        out[f"move_{h}m"] = s(f"move_{h}m")
    for m in MILESTONES:
        n = sum(bool(r.get(f"reached_{m}")) for r in rows)
        out[f"reached_{m}"] = {"count": n, "pct": 100.0 * n / len(rows)}
    return out


def fmt(v):
    return "-" if v is None else f"{v:.2f}"


def write_csv(path, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    print("MIDPOINT MATURE-A-AT-BOUNDARY ROBUSTNESS — V52.1")
    print("=" * 100)
    print("DETERMINISTIC SOURCES — frozen V51 rule — research only")
    print()

    canon = import_module(CANON, "canonical_v52_1")

    # B4 uses the exact canonical loaders.
    _, b4_u_raw, b4_u_conflicts = canon.load_underlying()
    b4_f = canon.load_futures()
    b4_u = {
        d: dict(rows)
        for d, rows in b4_u_raw.items()
        if "2025-12-12" <= d <= "2026-09-08"
    }
    b4_f = {
        d: dict(rows)
        for d, rows in b4_f.items()
        if "2025-12-12" <= d <= "2026-09-08"
    }
    if b4_u_conflicts != 0:
        raise SystemExit(f"STOP: canonical B4 underlying conflicts={b4_u_conflicts}")

    print("=== FRAMEWORK BUILDER PARITY AGAINST CANONICAL B4 ===")
    b4_framework = canonical_parity_check(canon, b4_u)
    print("PASS: deterministic framework builder matches canonical B4 exactly")
    print()

    all_events = []
    source_diag = {}

    for block in BLOCKS:
        name = block["name"]
        print(f"=== {name} ===")

        if block["manifest"] is None:
            sessions = sorted(
                d for d in b4_u
                if block["start"] <= d <= block["end"] and d in b4_f
            )
            u = b4_u
            fut = b4_f
            framework = [
                e for e in b4_framework
                if block["start"] <= e["session_date"] <= block["end"]
            ]
            u_conflicts = 0
            f_conflicts = 0
        else:
            for p in (block["manifest"], block["underlying"], block["futures"]):
                if not p.exists():
                    raise SystemExit(f"STOP: missing deterministic source {p}")

            sessions = load_manifest_sessions(block["manifest"])
            if sessions[0] != block["start"] or sessions[-1] != block["end"]:
                raise SystemExit(
                    f"STOP: {name} manifest range {sessions[0]}->{sessions[-1]} "
                    f"does not match expected {block['start']}->{block['end']}"
                )

            session_set = set(sessions)
            u, u_conflicts = load_explicit_underlying(block["underlying"], session_set)
            fut, f_conflicts = load_explicit_futures(block["futures"], session_set)

            if u_conflicts or f_conflicts:
                raise SystemExit(
                    f"STOP: {name} conflicts underlying={u_conflicts} futures={f_conflicts}"
                )

            framework = []
            for d in sessions:
                if d not in u:
                    raise SystemExit(f"STOP: {name} missing underlying session {d}")
                framework.extend(build_framework_for_session(d, u[d]))

        dual_sessions = [d for d in sessions if d in u and d in fut]
        print(f"sessions             = {len(sessions)}")
        print(f"dual-valid sessions  = {len(dual_sessions)}")
        print(f"framework events     = {len(framework)}")
        print(f"underlying conflicts = {u_conflicts}")
        print(f"futures conflicts    = {f_conflicts}")

        if len(dual_sessions) != len(sessions):
            missing = sorted(set(sessions) - set(dual_sessions))
            raise SystemExit(f"STOP: {name} missing dual-valid sessions: {missing[:10]}")

        block_events = []
        for ev in framework:
            d = ev["session_date"]
            t0 = ev["boundary_break_timestamp"]
            if d not in u or d not in fut or t0 not in u[d] or t0 not in fut[d]:
                continue

            direction = ev["direction"]
            diff = float(fut[d][t0]["diff"])
            a0 = candidate_a(direction, t0, fut[d])

            if a0 is False and beyond_threshold(direction, diff):
                row = dict(ev)
                row.update({
                    "block": name,
                    "futures_vwap_diff_at_boundary": diff,
                    "candidate_a_at_boundary": False,
                    "mature_streak_minutes": mature_streak(direction, t0, fut[d]),
                    "underlying_source": (
                        "CANONICAL_UNDERLYING_GLOB"
                        if block["underlying"] is None else str(block["underlying"])
                    ),
                    "futures_source": str(block["futures"]),
                })
                row.update(measure(ev, u[d]))
                block_events.append(row)

        print(f"MATURE_A_AT_BOUNDARY = {len(block_events)}")
        print()
        all_events.extend(block_events)
        source_diag[name] = {
            "session_count": len(sessions),
            "framework_event_count": len(framework),
            "mature_event_count": len(block_events),
            "underlying_conflicts": u_conflicts,
            "futures_conflicts": f_conflicts,
            "underlying_source": (
                "canonical UNDERLYING_GLOB"
                if block["underlying"] is None else str(block["underlying"])
            ),
            "futures_source": str(block["futures"]),
        }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, all_events)

    block_rows = []
    block_stats = {}
    for block in BLOCKS:
        name = block["name"]
        bucket = [r for r in all_events if r["block"] == name]
        s0 = stats(bucket)
        block_stats[name] = s0
        block_rows.append({
            "block": name,
            "start": block["start"],
            "end": block["end"],
            "n": s0.get("n", 0),
            "bull": s0.get("bull", 0),
            "bear": s0.get("bear", 0),
            "mfe_mean": s0.get("mfe", {}).get("mean"),
            "mfe_median": s0.get("mfe", {}).get("median"),
            "mae_mean": s0.get("mae", {}).get("mean"),
            "mae_median": s0.get("mae", {}).get("median"),
            **{
                f"reached_{m}_pct": s0.get(f"reached_{m}", {}).get("pct")
                for m in MILESTONES
            },
        })
    write_csv(BLOCKS_CSV, block_rows)

    combined = stats(all_events)
    report = {
        "model": "MIDPOINT_MATURE_A_AT_BOUNDARY_ROBUSTNESS_V52_1",
        "research_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "frozen_definition": {
            "candidate_a_at_boundary": False,
            "directional_futures_vwap_already_beyond_plusminus_5": True,
            "entry_geometry": "boundary-break close",
            "terminal": "first adverse midpoint close or trusted 15:14 cutoff",
            "streak_filter": None,
            "direction_specific_tuning": False,
            "exit_optimization": False,
        },
        "canonical_framework_builder_parity": "PASS",
        "sources": source_diag,
        "blocks": block_stats,
        "combined": combined,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT MATURE-A-AT-BOUNDARY ROBUSTNESS — V52.1")
    lines.append("=" * 100)
    lines.append("DETERMINISTIC SOURCES — FROZEN V51 DEFINITION — RESEARCH ONLY")
    lines.append("")
    lines.append("Canonical framework builder parity: PASS")
    lines.append("All explicit-source duplicate conflicts: 0")
    lines.append("")

    for block in BLOCKS:
        name = block["name"]
        s0 = block_stats[name]
        lines.append(f"{name} [{block['start']} -> {block['end']}]")
        lines.append("-" * 100)
        lines.append(
            f"n={s0.get('n',0)} bull={s0.get('bull',0)} bear={s0.get('bear',0)}"
        )
        if s0.get("n", 0):
            lines.append(
                f"MFE mean={fmt(s0['mfe']['mean'])} median={fmt(s0['mfe']['median'])} | "
                f"MAE mean={fmt(s0['mae']['mean'])} median={fmt(s0['mae']['median'])}"
            )
            for h in HORIZONS:
                x = s0[f"move_{h}m"]
                lines.append(
                    f"{h:>2}m move: n={x['n']} mean={fmt(x['mean'])} median={fmt(x['median'])}"
                )
            for m in MILESTONES:
                x = s0[f"reached_{m}"]
                lines.append(f"+{m:<3} = {x['count']}/{s0['n']} ({x['pct']:.1f}%)")
            st = s0["mature_streak"]
            lines.append(
                f"mature streak: median={fmt(st['median'])} mean={fmt(st['mean'])} "
                f"min={fmt(st['min'])} max={fmt(st['max'])}"
            )
        lines.append("")

    lines.append("COMBINED FOUR-BLOCK VIEW")
    lines.append("-" * 100)
    lines.append(
        f"n={combined.get('n',0)} bull={combined.get('bull',0)} bear={combined.get('bear',0)}"
    )
    if combined.get("n", 0):
        lines.append(
            f"MFE mean={fmt(combined['mfe']['mean'])} median={fmt(combined['mfe']['median'])}"
        )
        lines.append(
            f"MAE mean={fmt(combined['mae']['mean'])} median={fmt(combined['mae']['median'])}"
        )
        for m in MILESTONES:
            x = combined[f"reached_{m}"]
            lines.append(f"+{m:<3} = {x['count']}/{combined['n']} ({x['pct']:.1f}%)")
    lines.append("")

    lines.append("INTERPRETATION GUARD")
    lines.append("-" * 100)
    lines.append(
        "Date-separated robustness, but not globally pristine OOS. The broader Midpoint research "
        "history has already influenced strategy development."
    )
    lines.append(
        "2026-09-28 is excluded and remains separate fresh evidence."
    )
    lines.append(
        "MFE/MAE and milestones are Nifty underlying-point opportunity geometry, not option P&L."
    )
    lines.append(
        "Do not enable a new live family from V52.1 alone."
    )
    lines.append("")
    lines.append(f"EVENTS CSV  = {EVENTS_CSV}")
    lines.append(f"BLOCKS CSV  = {BLOCKS_CSV}")
    lines.append(f"REPORT JSON = {REPORT_JSON}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
