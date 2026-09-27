#!/usr/bin/env python3
"""
MIDPOINT + VWAP — 60-SESSION OVERLAP / LIFECYCLE AUDIT V1

Input:
  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-vwap-setup-family-60-session-validation-v1/
  setup-family-events-v1.csv

Purpose:
- quantify exact B/C/D overlaps
- quantify near-overlaps within ±1/±3/±5 minutes
- identify B-only / C-only / D-only / overlapping event clusters
- inspect unmeasured events
- verify 25-Aug-2026 taxonomy issue, especially 14:31 C+D overlap

Research only.
No event rules changed.
No Hilega/Candidate-A/runtime/execution changes.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

INPUT = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "midpoint-vwap-setup-family-60-session-validation-v1/"
    "setup-family-events-v1.csv"
)

OUTDIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "midpoint-vwap-setup-family-60-session-overlap-audit-v1"
)

CLUSTERS_CSV = OUTDIR / "overlap-clusters-v1.csv"
PAIRS_CSV = OUTDIR / "overlap-pairs-v1.csv"
UNMEASURED_CSV = OUTDIR / "unmeasured-events-v1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1.txt"

FAMILIES = {
    "B_DELAYED_FULL_CANDIDATE_A": "B",
    "C_FAILED_MIDPOINT_RECLAIM_REBREAK": "C",
    "D_FULL_RANGE_OPPOSITE_RECOVERY_REBREAK": "D",
}

WINDOWS = (0, 1, 3, 5)


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def minutes_apart(a, b):
    return abs((parse_ts(a) - parse_ts(b)).total_seconds()) / 60.0


def load_events():
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    rows = []
    with INPUT.open(newline="") as f:
        for r in csv.DictReader(f):
            fam = FAMILIES.get(r.get("family"))
            if not fam:
                continue

            r["_family_short"] = fam
            rows.append(r)

    return rows


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return

    fields = []
    for r in rows:
        for k in r:
            if not k.startswith("_") and k not in fields:
                fields.append(k)

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: v for k, v in r.items() if not k.startswith("_")})


def pair_rows(events):
    """
    All cross-family pairs on same session + same direction.
    """
    out = []

    grouped = defaultdict(list)
    for r in events:
        grouped[(r["session_date"], r["direction"])].append(r)

    for (session, direction), rows in grouped.items():
        rows = sorted(rows, key=lambda x: x["entry_timestamp"])

        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]

                if a["_family_short"] == b["_family_short"]:
                    continue

                gap = minutes_apart(a["entry_timestamp"], b["entry_timestamp"])

                out.append({
                    "session_date": session,
                    "direction": direction,
                    "family_a": a["_family_short"],
                    "entry_a": a["entry_timestamp"],
                    "family_b": b["_family_short"],
                    "entry_b": b["entry_timestamp"],
                    "gap_minutes": gap,
                    "exact_overlap": gap == 0,
                    "within_1m": gap <= 1,
                    "within_3m": gap <= 3,
                    "within_5m": gap <= 5,
                    "entry_close_a": a.get("entry_close"),
                    "entry_close_b": b.get("entry_close"),
                    "mfe_a": a.get("mfe"),
                    "mfe_b": b.get("mfe"),
                    "mae_a": a.get("mae"),
                    "mae_b": b.get("mae"),
                    "status_a": a.get("measurement_status"),
                    "status_b": b.get("measurement_status"),
                })

    return out


def family_combo(rows):
    return "+".join(sorted({r["_family_short"] for r in rows}))


def exact_clusters(events):
    grouped = defaultdict(list)
    for r in events:
        grouped[
            (
                r["session_date"],
                r["direction"],
                r["entry_timestamp"],
            )
        ].append(r)

    out = []
    for (session, direction, ts), rows in sorted(grouped.items()):
        combo = family_combo(rows)

        out.append({
            "session_date": session,
            "direction": direction,
            "entry_timestamp": ts,
            "family_combo": combo,
            "family_count": len(set(r["_family_short"] for r in rows)),
            "event_row_count": len(rows),
            "families": ",".join(
                sorted(r["_family_short"] for r in rows)
            ),
            "measurement_statuses": ",".join(
                sorted(set(r.get("measurement_status", "") for r in rows))
            ),
            "entry_close": next(
                (r.get("entry_close") for r in rows if r.get("entry_close")),
                "",
            ),
            "mfe_values": ",".join(
                str(r.get("mfe")) for r in rows
            ),
            "mae_values": ",".join(
                str(r.get("mae")) for r in rows
            ),
        })

    return out


def near_cluster_counts(pairs, max_gap):
    """
    Counts unique cross-family pair relationships within max_gap.
    This intentionally does not merge transitive clusters; it is a
    transparent pair-level overlap diagnostic.
    """
    counts = Counter()

    for p in pairs:
        if float(p["gap_minutes"]) <= max_gap:
            combo = "+".join(sorted((p["family_a"], p["family_b"])))
            counts[combo] += 1

    return counts


def main():
    events = load_events()
    pairs = pair_rows(events)
    clusters = exact_clusters(events)

    exact_multi = [r for r in clusters if int(r["family_count"]) > 1]
    unmeasured = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in events
        if r.get("measurement_status") != "OK"
    ]

    write_csv(PAIRS_CSV, pairs)
    write_csv(CLUSTERS_CSV, clusters)
    write_csv(UNMEASURED_CSV, unmeasured)

    family_counts = Counter(r["_family_short"] for r in events)
    exact_combo_counts = Counter(r["family_combo"] for r in clusters)

    lines = []
    lines.append("MIDPOINT + VWAP — 60-SESSION OVERLAP / LIFECYCLE AUDIT V1")
    lines.append("=" * 108)
    lines.append("Research only. No event-definition changes.")
    lines.append("")
    lines.append(f"input events                 = {len(events)}")
    lines.append(
        "family rows                  = "
        + ", ".join(f"{k}={family_counts[k]}" for k in ("B", "C", "D"))
    )
    lines.append(f"exact timestamp clusters     = {len(clusters)}")
    lines.append(f"exact multi-family clusters  = {len(exact_multi)}")
    lines.append(f"unmeasured rows              = {len(unmeasured)}")
    lines.append("")

    lines.append("EXACT EVENT CLASSIFICATION")
    lines.append("-" * 108)
    for combo in ("B", "C", "D", "B+C", "B+D", "C+D", "B+C+D"):
        lines.append(f"{combo:<8} clusters = {exact_combo_counts.get(combo, 0):3d}")
    lines.append("")

    lines.append("CROSS-FAMILY PAIR OVERLAPS")
    lines.append("-" * 108)
    for gap in WINDOWS:
        c = near_cluster_counts(pairs, gap)
        title = "EXACT" if gap == 0 else f"WITHIN ±{gap}m"
        lines.append(
            f"{title:<12} "
            f"B+C={c.get('B+C', 0):3d} "
            f"B+D={c.get('B+D', 0):3d} "
            f"C+D={c.get('C+D', 0):3d}"
        )
    lines.append("")

    lines.append("EXACT MULTI-FAMILY CLUSTERS")
    lines.append("-" * 108)
    if not exact_multi:
        lines.append("NONE")
    else:
        for r in exact_multi:
            lines.append(
                f"{r['session_date']} {r['entry_timestamp']} "
                f"{r['direction']:<7} combo={r['family_combo']}"
            )
    lines.append("")

    lines.append("UNMEASURED EVENTS")
    lines.append("-" * 108)
    if not unmeasured:
        lines.append("NONE")
    else:
        for r in unmeasured:
            lines.append(
                f"{r.get('session_date')} {r.get('entry_timestamp')} "
                f"{r.get('direction')} family={FAMILIES.get(r.get('family'), r.get('family'))} "
                f"status={r.get('measurement_status')} "
                f"invalidation={r.get('structural_invalidation_timestamp')}"
            )
    lines.append("")

    lines.append("25 AUG 2026")
    lines.append("-" * 108)
    aug = [
        r for r in events
        if r["session_date"] == "2026-08-25"
    ]
    for r in sorted(aug, key=lambda x: (x["entry_timestamp"], x["_family_short"])):
        lines.append(
            f"{r['entry_timestamp']} {r['direction']:<7} "
            f"{r['_family_short']} "
            f"entry={r.get('entry_close')} "
            f"MFE={r.get('mfe')} MAE={r.get('mae')} "
            f"invalidation={r.get('structural_invalidation_timestamp')}"
        )
    lines.append("")

    aug_exact = [
        r for r in exact_multi
        if r["session_date"] == "2026-08-25"
    ]
    if aug_exact:
        lines.append("25 AUG EXACT OVERLAP")
        for r in aug_exact:
            lines.append(
                f"  {r['entry_timestamp']} {r['direction']} -> {r['family_combo']}"
            )
        lines.append("")

    lines.append("TAXONOMY AUDIT NOTES")
    lines.append("-" * 108)
    lines.append(
        "B is a VWAP-delayed confirmation family and can legitimately coexist "
        "near another structural family; overlap must be measured, not assumed away."
    )
    lines.append(
        "C is intended to represent same-direction continuation/re-entry after a "
        "midpoint reclaim failure."
    )
    lines.append(
        "D is intended to represent an opposite-direction full-range regime reversal."
    )
    lines.append(
        "Do NOT apply hierarchy/priority in this audit. First quantify exact and near "
        "overlap. Any later taxonomy priority must be frozen only after reviewing these results."
    )
    lines.append("")

    lines.append("OUTPUTS")
    lines.append("-" * 108)
    lines.append(f"CLUSTERS CSV   = {CLUSTERS_CSV}")
    lines.append(f"PAIRS CSV      = {PAIRS_CSV}")
    lines.append(f"UNMEASURED CSV = {UNMEASURED_CSV}")
    lines.append(f"SUMMARY        = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
