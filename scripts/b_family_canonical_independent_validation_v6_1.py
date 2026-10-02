#!/usr/bin/env python3
"""
B FAMILY — CANONICAL INDEPENDENT HISTORICAL VALIDATION V6.1

Uses the repository's canonical V1.1 setup-family implementation directly.
No B reconstruction is duplicated here.

Stages
------
1) Import canonical:
   scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py

2) Detect B across all framework events using canonical family_b_for_event().

3) PARITY GATE:
   latest 60 canonical detections must exactly match the frozen
   setup-family-events-v1-1.csv B rows (date/direction/entry timestamp).

4) Older validation:
   evaluate the 27 B events outside latest60 using:
   - canonical measure_event() for MFE/MAE/invalidation
   - unchanged WARNING / RECOVERY diagnostics from prior B research

Research only. No production/runtime/execution changes.
"""

from __future__ import annotations

import csv
import importlib.util
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path("data/historical-evidence")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
KNOWN = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1-1"
    / "setup-family-events-v1-1.csv"
)

OUT = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-canonical-independent-validation-v6-1"
)
PARITY_CSV = OUT / "b-family-canonical-parity-v6-1.csv"
EVENT_CSV = OUT / "b-family-canonical-older-events-v6-1.csv"
SUMMARY_TXT = OUT / "b-family-canonical-independent-summary-v6-1.txt"


def load_canonical():
    spec = importlib.util.spec_from_file_location("bcanon_v1_1", CANON)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def minutes(a, b):
    if not a or not b:
        return None
    return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() // 60)


def dmove(direction, entry, later):
    if entry is None or later is None:
        return None
    return later - entry if direction == "BULLISH" else entry - later


def med(vals):
    vals = [x for x in vals if x is not None]
    return median(vals) if vals else None


def known_latest60_b():
    rows = list(csv.DictReader(open(KNOWN, newline="")))
    out = []
    for r in rows:
        if r.get("family") != "B_DELAYED_FULL_CANDIDATE_A":
            continue
        out.append({
            "session_date": r["session_date"],
            "direction": r["direction"],
            "entry_timestamp": r["entry_timestamp"],
        })
    return sorted(out, key=lambda r:(r["session_date"], r["direction"], r["entry_timestamp"]))


def parity_rows(canonical_latest60, known):
    a = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in canonical_latest60
    }
    b = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in known
    }

    rows = []
    for x in sorted(b - a):
        rows.append(("MISSING_FROM_CANONICAL",) + x)
    for x in sorted(a - b):
        rows.append(("EXTRA_IN_CANONICAL",) + x)
    if not rows:
        rows.append(("PASS", "", "", ""))
    return rows, (a == b)


def warning_recovery(ev, u, fut):
    direction = ev["direction"]
    entry_ts = ev["entry_timestamp"]
    entry = num(ev.get("entry_close"))
    high = num(ev.get("reference_high"))
    low = num(ev.get("reference_low"))
    mid = num(ev.get("reference_midpoint"))
    invalid = ev.get("structural_invalidation_timestamp") or ""

    warning = None
    warning_reason = None
    warning_points = None
    recovery = None
    recovery_points = None

    stamps = sorted(
        ts for ts in set(u).intersection(fut)
        if ts > entry_ts
        and ts[11:16] <= "15:14"
        and (not invalid or ts < invalid)
    )

    for ts in stamps:
        close = u[ts]["close"]
        diff = fut[ts]["diff"]

        if direction == "BULLISH":
            boundary_held = close > high
            vwap_side = diff > 0
        else:
            boundary_held = close < low
            vwap_side = diff < 0

        if warning is None and (not boundary_held or not vwap_side):
            warning = ts
            reasons = []
            if not boundary_held:
                reasons.append("BOUNDARY_RECLAIM")
            if not vwap_side:
                reasons.append("VWAP_SIDE_LOST")
            warning_reason = "+".join(reasons)
            warning_points = dmove(direction, entry, close)
            continue

        if warning is not None and recovery is None:
            if direction == "BULLISH":
                recovered = close > high and diff > 0
            else:
                recovered = close < low and diff < 0
            if recovered:
                recovery = ts
                recovery_points = dmove(direction, entry, close)

    invalid_points = None
    if invalid and invalid in u:
        invalid_points = dmove(direction, entry, u[invalid]["close"])

    e2w = minutes(entry_ts, warning) if warning else None
    w2r = minutes(warning, recovery) if warning and recovery else None
    w2i = minutes(warning, invalid) if warning and invalid else None

    if warning is None:
        cls = "HEALTHY_NO_WARNING"
    elif recovery and invalid:
        cls = "WARNING_RECOVERED_THEN_INVALIDATED"
    elif recovery and not invalid:
        cls = "WARNING_RECOVERED_NO_INVALIDATION"
    elif invalid:
        cls = "WARNING_THEN_INVALIDATED"
    else:
        cls = "WARNING_NO_RECOVERY_NO_INVALIDATION"

    return {
        "first_warning_timestamp": warning,
        "first_warning_reason": warning_reason,
        "entry_to_warning_min": e2w,
        "warning_points": warning_points,
        "first_recovery_timestamp": recovery,
        "warning_to_recovery_min": w2r,
        "recovery_points": recovery_points,
        "warning_to_invalidation_min": w2i,
        "invalidation_points": invalid_points,
        "recovered_within_3m": bool(w2r is not None and w2r <= 3),
        "health_class": cls,
    }


def enrich_canonical_event(m, b, u):
    # Canonical measurement mutates a copy.
    ev = dict(b)
    ev = m.measure_event(ev, u)
    return ev


def summarize_group(name, rows):
    warns = [r for r in rows if r.get("first_warning_timestamp")]
    recovered = [r for r in warns if r.get("first_recovery_timestamp")]
    norec = [r for r in warns if not r.get("first_recovery_timestamp")]
    profitable_warn = [
        r for r in warns
        if r.get("warning_points") is not None and r["warning_points"] > 0
    ]
    nonprof_warn = [
        r for r in warns
        if r.get("warning_points") is not None and r["warning_points"] <= 0
    ]

    lines = []
    lines.append(name)
    lines.append("-" * 118)
    lines.append(f"events: {len(rows)}")
    lines.append(f"BULLISH: {sum(r['direction']=='BULLISH' for r in rows)}")
    lines.append(f"BEARISH: {sum(r['direction']=='BEARISH' for r in rows)}")
    lines.append(f"warnings: {len(warns)}")
    lines.append(f"eventual recoveries: {len(recovered)}")
    lines.append(f"no recovery: {len(norec)}")
    lines.append(f"recoveries within 3m: {sum(r.get('recovered_within_3m') for r in warns)}")
    lines.append(f"median entry->warning min: {med([r.get('entry_to_warning_min') for r in warns])}")
    lines.append(f"median warning points: {med([r.get('warning_points') for r in warns])}")
    lines.append(f"median warning->recovery min: {med([r.get('warning_to_recovery_min') for r in recovered])}")
    lines.append(f"median warning->invalidation min: {med([r.get('warning_to_invalidation_min') for r in warns])}")
    lines.append(f"median MFE: {med([r.get('mfe') for r in rows])}")
    lines.append(f"median MAE: {med([r.get('mae') for r in rows])}")
    lines.append(
        f"NONPROFIT_AT_WARNING: n={len(nonprof_warn)} "
        f"recover<=3m={sum(r.get('recovered_within_3m') for r in nonprof_warn)} "
        f"medianWarnPts={med([r.get('warning_points') for r in nonprof_warn])}"
    )
    lines.append(
        f"PROFITABLE_AT_WARNING: n={len(profitable_warn)} "
        f"recover<=3m={sum(r.get('recovered_within_3m') for r in profitable_warn)} "
        f"medianWarnPts={med([r.get('warning_points') for r in profitable_warn])}"
    )
    lines.append("health classes:")
    for k,v in sorted(Counter(r["health_class"] for r in rows).items()):
        lines.append(f"  {k}: {v}")
    return lines


def main():
    m = load_canonical()

    framework_files, framework = m.load_framework()
    underlying_files, underlying, dup_conflicts = m.load_underlying()
    futures = m.load_futures()

    sessions = sorted({e["session_date"] for e in framework})
    latest60 = set(sessions[-60:])

    detected = []
    for e in framework:
        day = e["session_date"]
        b = m.family_b_for_event(
            e,
            underlying.get(day, {}),
            futures.get(day, {}),
        )
        if b:
            detected.append(b)

    detected = sorted(
        detected,
        key=lambda r:(r["session_date"], r["entry_timestamp"], r["direction"])
    )

    dev = [r for r in detected if r["session_date"] in latest60]
    older = [r for r in detected if r["session_date"] not in latest60]
    known = known_latest60_b()

    OUT.mkdir(parents=True, exist_ok=True)

    prows, parity_ok = parity_rows(dev, known)
    with open(PARITY_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["status","session_date","direction","entry_timestamp"])
        w.writerows(prows)

    print("B FAMILY — CANONICAL INDEPENDENT HISTORICAL VALIDATION V6.1")
    print("=" * 118)
    print("Framework sessions:", len(sessions))
    print("Canonical B total :", len(detected))
    print("Canonical B latest60:", len(dev))
    print("Known frozen B latest60:", len(known))
    print("Canonical B older :", len(older))
    print("Parity exact      :", parity_ok)
    print("Duplicate conflicts:", dup_conflicts)

    if not parity_ok:
        print("ABORTED: canonical latest60 parity mismatch.")
        print("Parity CSV:", PARITY_CSV)
        raise SystemExit(2)

    # Measure dev and older with canonical measurement, then same health diagnostics.
    def prepare(rows):
        out = []
        for b in rows:
            day = b["session_date"]
            ev = enrich_canonical_event(m, b, underlying.get(day, {}))
            health = warning_recovery(
                ev,
                underlying.get(day, {}),
                futures.get(day, {}),
            )
            out.append({**ev, **health})
        return out

    dev_m = prepare(dev)
    older_m = prepare(older)

    fields = []
    for r in older_m:
        for k in r:
            if k not in fields:
                fields.append(k)

    with open(EVENT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(older_m)

    lines = []
    lines.append("B FAMILY — CANONICAL INDEPENDENT HISTORICAL VALIDATION V6.1")
    lines.append("=" * 118)
    lines.append("PARITY GATE: PASS")
    lines.append(f"Framework sessions: {len(sessions)}")
    lines.append(f"Canonical B total: {len(detected)}")
    lines.append(f"Latest60 canonical B: {len(dev_m)}")
    lines.append(f"Older canonical B: {len(older_m)}")
    lines.append("")
    lines.extend(summarize_group("DEVELOPMENT / LATEST 60", dev_m))
    lines.append("")
    lines.extend(summarize_group("OLDER / INDEPENDENT-FROM-B-MANAGEMENT-TUNING", older_m))
    lines.append("")
    lines.append("OLDER EVENT DETAIL")
    lines.append("=" * 118)

    for r in older_m:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp'][11:16]} "
            f"origin={r['origin_timestamp'][11:16]} "
            f"delay={r['delay_minutes']} "
            f"warn={(r['first_warning_timestamp'][11:16] if r.get('first_warning_timestamp') else '-')} "
            f"age={r.get('entry_to_warning_min')} "
            f"warnPts={r.get('warning_points')} "
            f"recovery={(r['first_recovery_timestamp'][11:16] if r.get('first_recovery_timestamp') else '-')} "
            f"w2r={r.get('warning_to_recovery_min')} "
            f"invalid={(r['structural_invalidation_timestamp'][11:16] if r.get('structural_invalidation_timestamp') else '-')} "
            f"MFE={r.get('mfe')} MAE={r.get('mae')} "
            f"recover3m={r.get('recovered_within_3m')} "
            f"class={r.get('health_class')}"
        )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- B detection is imported directly from the canonical V1.1 setup-family script.")
    lines.append("- No B reconstruction logic is duplicated.")
    lines.append("- Latest60 parity must remain exact before older results are accepted.")
    lines.append("- Older sample is independent of B management tuning, but not globally pristine from all earlier Candidate-A research.")
    lines.append("- 3-minute recovery window is evaluated unchanged; no threshold is tuned here.")
    lines.append("- Underlying NIFTY points are not CE/PE option-premium P&L.")

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print()
    print(summary)
    print()
    print("PARITY CSV:", PARITY_CSV)
    print("OLDER EVENT CSV:", EVENT_CSV)
    print("SUMMARY:", SUMMARY_TXT)


if __name__ == "__main__":
    main()
