#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

OUTDIR = RESEARCH / "midpoint-mature-boundary-robustness-v52"
EVENTS_CSV = OUTDIR / "events-v52.csv"
BLOCKS_CSV = OUTDIR / "blocks-v52.csv"
REPORT_JSON = OUTDIR / "report-v52.json"
SUMMARY_TXT = OUTDIR / "summary-v52.txt"

THRESHOLD = 5.0
MILESTONES = (20, 30, 50, 75, 100)
HORIZONS = (5, 10, 15, 30)

BLOCKS = (
    ("B1_2024-08-16_to_2025-02-05", "2024-08-16", "2025-02-05"),
    ("B2_2025-02-06_to_2025-07-16", "2025-02-06", "2025-07-16"),
    ("B3_2025-07-17_to_2025-12-11", "2025-07-17", "2025-12-11"),
    ("B4_2025-12-12_to_2026-09-08", "2025-12-12", "2026-09-08"),
)


def load_csv(path: Path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in ("", None):
        return None
    return float(v)


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def minute_key(dt: datetime) -> str:
    return dt.isoformat()


def date_in_any_block(d: str) -> bool:
    return any(start <= d <= end for _, start, end in BLOCKS)


def block_for(d: str) -> str | None:
    for name, start, end in BLOCKS:
        if start <= d <= end:
            return name
    return None


def trusted(ts: str) -> bool:
    try:
        t = parse_dt(ts)
    except Exception:
        return False
    hhmm = t.strftime("%H:%M")
    return "09:15" <= hhmm <= "15:14"


def directional(direction: str, entry: float, price: float) -> float:
    return price - entry if direction == "BULLISH" else entry - price


def beyond_threshold(direction: str, diff: float) -> bool:
    return diff < -THRESHOLD if direction == "BEARISH" else diff > THRESHOLD


def candidate_a(direction: str, at_ts: str, fut: dict[str, dict]) -> bool | None:
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


def discover_framework_events():
    """
    Discover one-row-per-event structural artifacts by schema.
    We keep only rows that have:
      session_date, boundary_break_timestamp,
      reference_high, reference_midpoint, reference_low,
      and either setup_type or direction.
    Richest row wins per structural key.
    """
    found = {}
    source_counts = Counter()
    scanned = 0

    for p in RESEARCH.rglob("*.csv"):
        try:
            rows = load_csv(p)
        except Exception:
            continue
        scanned += 1
        if not rows:
            continue
        hdr = set(rows[0].keys())

        required = {
            "session_date",
            "boundary_break_timestamp",
            "reference_high",
            "reference_midpoint",
            "reference_low",
        }
        if not required.issubset(hdr):
            continue
        if not ({"setup_type", "direction"} & hdr):
            continue

        for r in rows:
            d = r.get("session_date")
            t0 = r.get("boundary_break_timestamp")
            if not d or not t0 or not date_in_any_block(d):
                continue
            try:
                hi = f(r.get("reference_high"))
                mid = f(r.get("reference_midpoint"))
                lo = f(r.get("reference_low"))
            except Exception:
                continue
            if None in (hi, mid, lo):
                continue

            direction = str(r.get("direction") or "").upper()
            setup_type = str(r.get("setup_type") or "").upper()

            if direction not in {"BULLISH", "BEARISH"}:
                if "RED" in setup_type:
                    direction = "BEARISH"
                elif "GREEN" in setup_type:
                    direction = "BULLISH"
                else:
                    continue

            key = (d, direction, t0, hi, mid, lo)
            richness = sum(r.get(k) not in ("", None) for k in r)
            if key not in found or richness > found[key][0]:
                found[key] = (
                    richness,
                    {
                        "session_date": d,
                        "direction": direction,
                        "setup_type": r.get("setup_type"),
                        "boundary_break_timestamp": t0,
                        "reference_high": hi,
                        "reference_midpoint": mid,
                        "reference_low": lo,
                        "_framework_source": str(p),
                    },
                )
            source_counts[str(p)] += 1

    return [x[1] for x in found.values()], dict(source_counts), scanned


def discover_underlying():
    """
    Discover raw 1m underlying OHLC by schema.
    Exact duplicate rows are tolerated.
    Conflicting duplicates are counted and STOP the run.
    """
    by = defaultdict(dict)
    source_counts = Counter()
    conflicts = 0

    for p in ROOT.rglob("*.csv"):
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows:
            continue
        hdr = set(rows[0].keys())
        if not {"session_date", "timestamp", "open", "high", "low", "close"}.issubset(hdr):
            continue

        # Avoid event/summary outputs that happen to carry OHLC aliases.
        name = p.name.lower()
        if any(x in name for x in ("event", "summary", "scorecard", "report")):
            continue

        used = False
        for r in rows:
            d = r.get("session_date")
            ts = r.get("timestamp")
            if not d or not ts or not date_in_any_block(d):
                continue
            try:
                row = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
            except Exception:
                continue

            old = by[d].get(ts)
            if old is not None and old != row:
                conflicts += 1
                continue
            by[d][ts] = row
            used = True

        if used:
            source_counts[str(p)] += 1

    return dict(by), dict(source_counts), conflicts


def discover_futures():
    """
    Discover futures 1m close + session VWAP or precomputed diff.
    Exact duplicate rows are tolerated.
    Conflicting duplicates STOP the run.
    """
    by = defaultdict(dict)
    source_counts = Counter()
    conflicts = 0

    for p in ROOT.rglob("*.csv"):
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows:
            continue
        hdr = set(rows[0].keys())
        if not {"session_date", "timestamp", "close"}.issubset(hdr):
            continue
        if not ({"session_vwap", "vwap", "diff"} & hdr):
            continue

        name = p.name.lower()
        # Prefer actual futures/VWAP raw artifacts.
        if "future" not in name and "vwap" not in name:
            continue

        used = False
        for r in rows:
            d = r.get("session_date")
            ts = r.get("timestamp")
            if not d or not ts or not date_in_any_block(d):
                continue

            try:
                close = float(r["close"])
                if r.get("diff") not in ("", None):
                    diff = float(r["diff"])
                    vwap = (
                        float(r.get("session_vwap") or r.get("vwap"))
                        if (r.get("session_vwap") or r.get("vwap")) not in ("", None)
                        else close - diff
                    )
                else:
                    vv = r.get("session_vwap")
                    if vv in ("", None):
                        vv = r.get("vwap")
                    if vv in ("", None):
                        continue
                    vwap = float(vv)
                    diff = close - vwap
            except Exception:
                continue

            row = {"close": close, "vwap": vwap, "diff": diff}
            old = by[d].get(ts)
            if old is not None:
                if (
                    abs(old["close"] - row["close"]) > 1e-9
                    or abs(old["vwap"] - row["vwap"]) > 1e-6
                    or abs(old["diff"] - row["diff"]) > 1e-6
                ):
                    conflicts += 1
                    continue
            by[d][ts] = row
            used = True

        if used:
            source_counts[str(p)] += 1

    return dict(by), dict(source_counts), conflicts


def mature_streak(direction: str, t0: str, fut: dict[str, dict]) -> int:
    dt = parse_dt(t0)
    n = 0
    for i in range(0, 121):
        ts = minute_key(dt - timedelta(minutes=i))
        row = fut.get(ts)
        if row is None or not beyond_threshold(direction, float(row["diff"])):
            break
        n += 1
    return n


def first_midpoint_invalidation(direction: str, entry_ts: str, midpoint: float, u: dict):
    for ts in sorted(u):
        if ts <= entry_ts or not trusted(ts):
            continue
        c = float(u[ts]["close"])
        if direction == "BEARISH" and c > midpoint:
            return ts
        if direction == "BULLISH" and c < midpoint:
            return ts
    return None


def measure(ev: dict, u: dict):
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
    else:
        mfe = mae = None

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


def stats(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}

    def values(k):
        return [float(r[k]) for r in rows if r.get(k) not in (None, "")]

    def s(k):
        xs = values(k)
        return {
            "n": len(xs),
            "mean": mean(xs) if xs else None,
            "median": median(xs) if xs else None,
            "min": min(xs) if xs else None,
            "max": max(xs) if xs else None,
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


def fmt(x):
    return "-" if x is None else f"{x:.2f}"


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
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
    print("MIDPOINT MATURE-A-AT-BOUNDARY ROBUSTNESS — V52")
    print("=" * 96)
    print("RESEARCH ONLY — frozen V51 definition, no threshold changes")

    framework, framework_sources, framework_scanned = discover_framework_events()
    underlying, underlying_sources, u_conflicts = discover_underlying()
    futures, futures_sources, f_conflicts = discover_futures()

    print(f"framework events discovered = {len(framework)}")
    print(f"framework CSVs scanned       = {framework_scanned}")
    print(f"underlying sessions          = {len(underlying)}")
    print(f"futures sessions             = {len(futures)}")
    print(f"underlying conflicts         = {u_conflicts}")
    print(f"futures conflicts            = {f_conflicts}")

    if u_conflicts or f_conflicts:
        raise SystemExit("STOP: conflicting duplicate raw data detected")

    rows = []
    skipped = Counter()

    for ev in sorted(
        framework,
        key=lambda r: (r["session_date"], r["boundary_break_timestamp"], r["direction"]),
    ):
        d = ev["session_date"]
        block = block_for(d)
        if block is None:
            continue

        u = underlying.get(d)
        fut = futures.get(d)
        t0 = ev["boundary_break_timestamp"]

        if not u or not fut:
            skipped["missing_dual_session"] += 1
            continue
        if t0 not in u or t0 not in fut:
            skipped["missing_t0"] += 1
            continue
        if not trusted(t0):
            skipped["untrusted_t0"] += 1
            continue

        direction = ev["direction"]
        diff = float(fut[t0]["diff"])
        a0 = candidate_a(direction, t0, fut)

        if a0 is False and beyond_threshold(direction, diff):
            row = dict(ev)
            row.update(
                block=block,
                futures_vwap_diff_at_boundary=diff,
                candidate_a_at_boundary=False,
                mature_streak_minutes=mature_streak(direction, t0, fut),
            )
            row.update(measure(ev, u))
            rows.append(row)

    block_rows = []
    block_stats = {}
    for name, start, end in BLOCKS:
        bucket = [r for r in rows if r["block"] == name]
        st = stats(bucket)
        block_stats[name] = st
        block_rows.append({
            "block": name,
            "start_date": start,
            "end_date": end,
            "n": st.get("n", 0),
            "bull": st.get("bull", 0),
            "bear": st.get("bear", 0),
            "mfe_mean": st.get("mfe", {}).get("mean"),
            "mfe_median": st.get("mfe", {}).get("median"),
            "mae_mean": st.get("mae", {}).get("mean"),
            "mae_median": st.get("mae", {}).get("median"),
            **{
                f"reached_{m}_pct": st.get(f"reached_{m}", {}).get("pct")
                for m in MILESTONES
            },
        })

    combined = stats(rows)

    report = {
        "model": "MIDPOINT_MATURE_A_AT_BOUNDARY_ROBUSTNESS_V52",
        "research_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "definition_frozen_from_v51": {
            "threshold": 5.0,
            "candidate_a_at_boundary": False,
            "directional_vwap_already_beyond_threshold": True,
            "entry_timestamp": "boundary_break_timestamp",
            "terminal": "first adverse midpoint close or trusted cutoff",
            "no_direction_specific_thresholds": True,
            "no_streak_tuning": True,
        },
        "blocks": block_stats,
        "combined": combined,
        "skipped": dict(skipped),
        "source_diagnostics": {
            "framework_sources": framework_sources,
            "underlying_sources": underlying_sources,
            "futures_sources": futures_sources,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, rows)
    write_csv(BLOCKS_CSV, block_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT MATURE-A-AT-BOUNDARY ROBUSTNESS — V52")
    lines.append("=" * 96)
    lines.append("RESEARCH ONLY — frozen V51 definition")
    lines.append("")
    lines.append(
        "Definition: at structural boundary T0, canonical Candidate A is FALSE, "
        "but raw futures-VWAP is already directionally beyond +/-5."
    )
    lines.append("No streak tuning. No direction-specific threshold. No exit optimization.")
    lines.append("")

    for name, start, end in BLOCKS:
        s0 = block_stats[name]
        lines.append(f"{name}  [{start} -> {end}]")
        lines.append("-" * 96)
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
                    f"{h:>2}m move n={x['n']} mean={fmt(x['mean'])} median={fmt(x['median'])}"
                )
            for m in MILESTONES:
                x = s0[f"reached_{m}"]
                lines.append(
                    f"+{m:<3} = {x['count']}/{s0['n']} ({x['pct']:.1f}%)"
                )
            ms = s0["mature_streak"]
            lines.append(
                f"mature streak median={fmt(ms['median'])} mean={fmt(ms['mean'])} "
                f"min={fmt(ms['min'])} max={fmt(ms['max'])}"
            )
        lines.append("")

    lines.append("COMBINED FOUR-BLOCK VIEW")
    lines.append("-" * 96)
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

    lines.append("ROBUSTNESS INTERPRETATION GUARD")
    lines.append("-" * 96)
    lines.append(
        "These blocks are date-separated robustness slices, but the broader research history "
        "has already influenced Midpoint development. Treat this as robustness evidence, not "
        "globally untouched OOS."
    )
    lines.append(
        "Do not enable a new live family from V52 alone. 2026-09-28 remains separate fresh evidence."
    )
    lines.append(
        "MFE/MAE and milestone results are Nifty underlying-point opportunity geometry, not option P&L."
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
