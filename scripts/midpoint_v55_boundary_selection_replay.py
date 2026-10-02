#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path

from market_lab.midpoint_strategy.boundary_classifier import (
    MidpointBoundaryClassifierV55,
)
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.structure import ReferenceStructure

V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
LIVE_AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-boundary-classifier-v55"
)
CSV_OUT = OUTDIR / "ownership-v55.csv"
JSON_OUT = OUTDIR / "report-v55.json"
TXT_OUT = OUTDIR / "summary-v55.txt"

EXPECTED = {
    "B1_2024-08-16_to_2025-02-05": {"E": 51, "B": 30, "OTHER_FRESH_A": 101},
    "B2_2025-02-06_to_2025-07-16": {"E": 61, "B": 41, "OTHER_FRESH_A": 70},
    "B3_2025-07-17_to_2025-12-11": {"E": 56, "B": 39, "OTHER_FRESH_A": 82},
    "B4_2025-12-12_to_2026-09-08": {"E": 103, "B": 78, "OTHER_FRESH_A": 148},
}


def import_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def history_for_event(session, t0, u, fut):
    rows = []
    for ts in sorted(fut):
        if ts > t0:
            break
        if ts not in u:
            continue
        f = fut[ts]
        rows.append(
            FamilyBObservation(
                timestamp=ts,
                close=float(u[ts]["close"]),
                futures_price=float(f["close"]),
                futures_vwap=float(f["vwap"]),
            )
        )
    return rows


def ref_from_event(ev):
    return ReferenceStructure(
        session_date=ev["session_date"],
        reference_type="RED" if ev["direction"] == "BEARISH" else "GREEN",
        start_timestamp=ev.get("reference_start_timestamp") or ev["boundary_break_timestamp"],
        end_timestamp=ev.get("reference_end_timestamp") or ev["boundary_break_timestamp"],
        high=float(ev["reference_high"]),
        low=float(ev["reference_low"]),
    )


def load_block(block, v52, canon):
    if block["manifest"] is None:
        _, uraw, conflicts = canon.load_underlying()
        if conflicts:
            raise SystemExit(f"STOP: canonical underlying conflicts={conflicts}")
        fraw = canon.load_futures()
        u = {
            d: dict(x) for d, x in uraw.items()
            if block["start"] <= d <= block["end"]
        }
        fut = {
            d: dict(x) for d, x in fraw.items()
            if block["start"] <= d <= block["end"]
        }
        framework = []
        for d in sorted(u):
            framework.extend(v52.build_framework_for_session(d, u[d]))
        return u, fut, framework

    sessions = v52.load_manifest_sessions(block["manifest"])
    ss = set(sessions)
    u, uc = v52.load_explicit_underlying(block["underlying"], ss)
    fut, fc = v52.load_explicit_futures(block["futures"], ss)
    if uc or fc:
        raise SystemExit(
            f"STOP: {block['name']} conflicts underlying={uc} futures={fc}"
        )
    framework = []
    for d in sessions:
        framework.extend(v52.build_framework_for_session(d, u[d]))
    return u, fut, framework


def replay_live_audit():
    if not LIVE_AUDIT.exists():
        return {"available": False}

    rows = [
        json.loads(line)
        for line in LIVE_AUDIT.read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if r.get("session_date") == "2026-09-28"]

    out = []
    for b in [r for r in rows if r.get("event_type") == "BOUNDARY_BREAK"]:
        watch = next(
            (
                r for r in rows
                if r.get("event_type") == "B_WATCH_STARTED"
                and r.get("event_timestamp") == b.get("event_timestamp")
                and r.get("direction") == b.get("direction")
            ),
            None,
        )
        original_a_false = bool(
            watch
            and (
                watch.get("reason") == "ORIGINAL_EVENT_CANDIDATE_A_FALSE"
                or (watch.get("evidence") or {}).get("original_full_candidate_a") is False
            )
        )
        raw = float(b["futures_price"]) - float(b["futures_vwap"])
        direction = b["direction"]

        if not original_a_false:
            owner = "OTHER_OR_UNRESOLVED"
            reason = "LIVE_AUDIT_DOES_NOT_PROVE_ORIGINAL_A_FALSE"
        elif (direction == "BEARISH" and raw < -5) or (direction == "BULLISH" and raw > 5):
            owner = "E"
            reason = "MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY"
        else:
            owner = "B"
            reason = "DELAYED_CONFIRMATION_WATCH"

        out.append({
            "timestamp": b["event_timestamp"],
            "direction": direction,
            "raw_diff": raw,
            "original_a_false": original_a_false,
            "owner": owner,
            "reason": reason,
        })
    return {"available": True, "events": out}


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
    v52 = import_module(V52, "v52_for_v55")
    canon = import_module(CANON, "canon_for_v55")
    classifier = MidpointBoundaryClassifierV55()

    print("MIDPOINT V55 — B/E BOUNDARY CLASSIFIER + REPLAY PARITY")
    print("=" * 100)
    print("NOT WIRED TO LIVE COORDINATOR")
    print()

    rows = []
    block_results = {}

    for block in v52.BLOCKS:
        u, fut, framework = load_block(block, v52, canon)
        counts = Counter()

        for ev in framework:
            d = ev["session_date"]
            t0 = ev["boundary_break_timestamp"]
            if d not in u or d not in fut or t0 not in u[d] or t0 not in fut[d]:
                raise SystemExit(f"STOP: missing exact event data {d} {t0}")

            history = history_for_event(d, t0, u[d], fut[d])
            boundary = history[-1]
            decision = classifier.classify(
                reference=ref_from_event(ev),
                boundary_observation=boundary,
                history=history,
            )
            counts[decision.owner] += 1
            rows.append({
                "block": block["name"],
                "session_date": d,
                "direction": ev["direction"],
                "boundary_break_timestamp": t0,
                "owner": decision.owner,
                "reason": decision.reason,
                "candidate_a_at_boundary": decision.candidate_a_at_boundary,
                "raw_futures_vwap_diff": decision.raw_futures_vwap_diff,
                "directional_vwap_diff": decision.directional_vwap_diff,
            })

        actual = {
            "E": counts["E"],
            "B": counts["B"],
            "OTHER_FRESH_A": counts["OTHER_FRESH_A"],
        }
        expected = EXPECTED[block["name"]]
        parity = actual == expected
        block_results[block["name"]] = {
            "framework_events": len(framework),
            "actual": actual,
            "expected": expected,
            "parity": parity,
        }

        print(block["name"])
        print("  framework =", len(framework))
        print("  actual    =", actual)
        print("  expected  =", expected)
        print("  parity    =", "PASS" if parity else "FAIL")
        print()

        if not parity:
            raise SystemExit(f"STOP: V53/V55 ownership parity failed for {block['name']}")

    live = replay_live_audit()
    if live.get("available"):
        expected_live = {
            ("2026-09-28T09:26:00+05:30", "BEARISH"): "E",
            ("2026-09-28T09:58:00+05:30", "BULLISH"): "B",
        }
        for e in live["events"]:
            key = (e["timestamp"], e["direction"])
            if key in expected_live and e["owner"] != expected_live[key]:
                raise SystemExit(f"STOP: live replay parity failed {e}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(CSV_OUT, rows)

    report = {
        "model": "MIDPOINT_BOUNDARY_CLASSIFIER_V55",
        "live_wired": False,
        "family_e_live_enabled": False,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "block_results": block_results,
        "live_replay_2026_09_28": live,
    }
    JSON_OUT.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT V55 — B/E BOUNDARY CLASSIFIER + REPLAY PARITY")
    lines.append("=" * 100)
    lines.append("Pure classifier only; not wired to live coordinator.")
    lines.append("")
    for name, r in block_results.items():
        lines.append(
            f"{name}: parity=PASS actual={r['actual']} expected={r['expected']}"
        )
    lines.append("")
    lines.append("2026-09-28 replay")
    if live.get("available"):
        for e in live["events"]:
            lines.append(
                f"{e['timestamp']} {e['direction']} raw={e['raw_diff']:.2f} "
                f"A_false={e['original_a_false']} => {e['owner']} {e['reason']}"
            )
    else:
        lines.append("live audit unavailable")
    lines.append("")
    lines.append("Safety: E remains live-disabled; no orders; no quantity.")
    lines.append("NEXT: V56 wires this classifier into live-shadow coordinator behind explicit enablement.")
    lines.append("")
    lines.append(f"CSV    = {CSV_OUT}")
    lines.append(f"JSON   = {JSON_OUT}")
    lines.append(f"SUMMARY= {TXT_OUT}")

    TXT_OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
