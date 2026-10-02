#!/usr/bin/env python3
"""
REJECTED FAMILY-C MECHANISM DECOMPOSITION — 60 SESSIONS — V1

Consumes the existing Family-C rejection audit CSV and classifies each rejected
former-C by:
- termination -> would-be C gap bucket
- same-direction Family-D relationship:
    exact same timestamp
    within 1m
    within 3m
    within 5m
    later than 5m
    no same-direction D

Research only. No thresholds or event rules are changed.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
INPUT = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-family-c-rejection-audit-60-session-v1"
    / "rejected-former-family-c-v1.csv"
)
OUTDIR = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-family-c-rejected-mechanism-decomposition-60-v1"
)
DETAIL_CSV = OUTDIR / "rejected-c-mechanism-decomposition-v1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1.txt"

def parse_ts(ts):
    return datetime.fromisoformat(ts)

def delta_minutes(a, b):
    return abs((parse_ts(b) - parse_ts(a)).total_seconds()) / 60.0

def fnum(v):
    if v in (None, ""):
        return None
    return float(v)

def qdesc(vals):
    xs = sorted(float(x) for x in vals if x not in (None, ""))
    if not xs:
        return "n=0"
    def q(p):
        return xs[round((len(xs)-1)*p)]
    return (
        f"n={len(xs)} mean={mean(xs):+.2f} median={median(xs):+.2f} "
        f"p25={q(.25):+.2f} p75={q(.75):+.2f} "
        f"min={xs[0]:+.2f} max={xs[-1]:+.2f}"
    )

def gap_bucket(v):
    if v is None: return "NO_TERMINATION"
    if v <= 5: return "LE_5M"
    if v <= 15: return "6_15M"
    if v <= 30: return "16_30M"
    if v <= 60: return "31_60M"
    if v <= 120: return "61_120M"
    return "GT_120M"

def d_relation(row):
    d = row.get("first_same_direction_family_d_after_termination")
    c = row.get("entry_timestamp")
    if not d:
        return "NO_SAME_DIRECTION_D", None
    gap = delta_minutes(c, d)
    if gap == 0: return "D_EXACT_SAME_TIMESTAMP", gap
    if gap <= 1: return "D_WITHIN_1M", gap
    if gap <= 3: return "D_WITHIN_3M", gap
    if gap <= 5: return "D_WITHIN_5M", gap
    return "D_LATER_GT_5M", gap

def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def main():
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    with INPUT.open(newline="") as f:
        rows = list(csv.DictReader(f))

    out = []
    for r in rows:
        x = dict(r)
        tg = fnum(r.get("termination_to_would_be_rebreak_minutes"))
        rel, dg = d_relation(r)
        x["gap_bucket_recalc"] = gap_bucket(tg)
        x["d_relation_to_would_be_c"] = rel
        x["would_be_c_to_same_direction_d_minutes"] = "" if dg is None else dg
        out.append(x)

    write_csv(DETAIL_CSV, out)

    lines = []
    lines.append("REJECTED FAMILY-C MECHANISM DECOMPOSITION — 60 SESSIONS — V1")
    lines.append("=" * 110)
    lines.append(f"rejected former-C rows = {len(out)}")
    lines.append("")

    lines.append("BY TERMINATION -> WOULD-BE C GAP")
    lines.append("-" * 110)
    gb = Counter(r["gap_bucket_recalc"] for r in out)
    for b in ("LE_5M","6_15M","16_30M","31_60M","61_120M","GT_120M","NO_TERMINATION"):
        lines.append(f"{b:<20} n={gb.get(b,0):3d}")
    lines.append("")

    lines.append("BY SAME-DIRECTION FAMILY-D RELATIONSHIP")
    lines.append("-" * 110)
    rc = Counter(r["d_relation_to_would_be_c"] for r in out)
    for k in (
        "D_EXACT_SAME_TIMESTAMP","D_WITHIN_1M","D_WITHIN_3M",
        "D_WITHIN_5M","D_LATER_GT_5M","NO_SAME_DIRECTION_D"
    ):
        lines.append(f"{k:<28} n={rc.get(k,0):3d}")
    lines.append("")

    lines.append("CROSS-TAB GAP BUCKET x D RELATION")
    lines.append("-" * 110)
    rels = (
        "D_EXACT_SAME_TIMESTAMP","D_WITHIN_1M","D_WITHIN_3M",
        "D_WITHIN_5M","D_LATER_GT_5M","NO_SAME_DIRECTION_D"
    )
    for b in ("LE_5M","6_15M","16_30M","31_60M","61_120M","GT_120M"):
        sub = [r for r in out if r["gap_bucket_recalc"] == b]
        counts = Counter(r["d_relation_to_would_be_c"] for r in sub)
        lines.append(
            f"{b:<10} n={len(sub):2d} " +
            " ".join(f"{k}={counts.get(k,0)}" for k in rels)
        )
    lines.append("")

    lines.append("DESCRIPTIVE OUTCOMES BY GAP BUCKET")
    lines.append("-" * 110)
    for b in ("LE_5M","6_15M","16_30M","31_60M","61_120M","GT_120M"):
        sub = [r for r in out if r["gap_bucket_recalc"] == b]
        lines.append(
            f"{b:<10} MFE[{qdesc(fnum(r.get('mfe')) for r in sub)}] "
            f"MAE[{qdesc(fnum(r.get('mae')) for r in sub)}]"
        )
        for h in (1,3,5,10,15):
            lines.append(
                f"  +{h:2d}m {qdesc(fnum(r.get(f'move_{h}m')) for r in sub)}"
            )
    lines.append("")

    lines.append("25 AUG")
    lines.append("-" * 110)
    for r in out:
        if r.get("session_date") == "2026-08-25":
            lines.append(
                f"{r['entry_timestamp']} {r['direction']} "
                f"gap={r['gap_bucket_recalc']} "
                f"d_relation={r['d_relation_to_would_be_c']} "
                f"same_dir_D={r.get('first_same_direction_family_d_after_termination')}"
            )
    lines.append("")
    lines.append("No rule changes are made by this audit.")
    lines.append(f"DETAIL CSV = {DETAIL_CSV}")
    lines.append(f"SUMMARY    = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
