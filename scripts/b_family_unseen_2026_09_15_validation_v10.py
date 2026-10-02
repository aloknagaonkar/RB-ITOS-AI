#!/usr/bin/env python3
"""
B FAMILY — 2026-09-15 UNSEEN VALIDATION V10

Goal
----
Run the frozen opening-midpoint framework and frozen Family-B detector on the
first clean post-2026-09-08 session for which we already have:
  - NIFTY underlying 1m OHLC
  - NIFTY futures 1m close + session VWAP

This is an evaluation-only adapter.

IMPORTANT
---------
- Does NOT modify opening_candle_midpoint_framework_v1.py.
- Does NOT modify Family B.
- Evidence / positioning are NOT used to determine midpoint/boundary breaks.
  In the frozen framework they are attached only to snapshot context.
- This adapter suppresses contextual enrichment by monkeypatching
  attach_context() to return {}. Structural event logic is untouched.
- No strategy/runtime/order settings are changed.
- Underlying NIFTY points only; not option-premium P&L.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

from market_lab import opening_candle_midpoint_framework_v1 as framework

SESSION = "2026-09-15"

UNDERLYING_CSV = Path(
    "data/historical-evidence/intraday-validation/underlying-2026-09-15.csv"
)
FUTURES_CSV = Path(
    "data/historical-evidence/intraday-validation/futures-vwap-2026-09-15.csv"
)
CANON_B = Path(
    "scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py"
)
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")

OUTDIR = (
    Path("data/historical-evidence")
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-unseen-validation-v10-2026-09-15"
)
FRAMEWORK_JSON = OUTDIR / "framework-2026-09-15.json"
EVENTS_CSV = OUTDIR / "b-events-2026-09-15.csv"
SUMMARY_TXT = OUTDIR / "summary-2026-09-15.txt"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def f(v):
    if v in (None, ""):
        return None
    return float(v)


def build_underlying():
    # Use the frozen framework's own CSV loader / parser.
    rows = framework.load_csv(UNDERLYING_CSV)
    by_session = framework.underlying_by_session(rows)
    if SESSION not in by_session:
        raise RuntimeError(
            f"{SESSION} not produced by frozen underlying_by_session(); "
            f"available={sorted(by_session)}"
        )
    return by_session[SESSION]


def build_framework_events(minute_rows):
    # Structural logic in build_event() depends on underlying bars.
    # Evidence/positioning are only contextual snapshot enrichment.
    original_attach_context = framework.attach_context
    framework.attach_context = lambda session_date, ts, evidence_idx, atm_idx: {}
    try:
        bars = framework.aggregate_5m(minute_rows)
        red = framework.select_reference_bar(bars, "RED")
        green = framework.select_reference_bar(bars, "GREEN")

        events = []
        if red is not None:
            events.append(
                framework.build_event(
                    block="POST_08SEP_UNSEEN",
                    session_date=SESSION,
                    minute_rows=minute_rows,
                    bar=red,
                    colour="RED",
                    evidence_idx={},
                    atm_idx={},
                )
            )
        if green is not None:
            events.append(
                framework.build_event(
                    block="POST_08SEP_UNSEEN",
                    session_date=SESSION,
                    minute_rows=minute_rows,
                    bar=green,
                    colour="GREEN",
                    evidence_idx={},
                    atm_idx={},
                )
            )
        return events
    finally:
        framework.attach_context = original_attach_context


def build_underlying_index(minute_rows):
    out = {}
    for r in minute_rows:
        ts = r.get("timestamp")
        if hasattr(ts, "isoformat"):
            key = ts.isoformat()
        else:
            key = str(ts)
        out[key] = {
            "open": f(r.get("open")),
            "high": f(r.get("high")),
            "low": f(r.get("low")),
            "close": f(r.get("close")),
            "volume": f(r.get("volume")),
        }
    return out


def build_futures_index():
    out = {}
    with FUTURES_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            ts = r.get("timestamp")
            close = f(r.get("close"))
            vwap = f(r.get("session_vwap") or r.get("vwap"))
            if not ts or close is None or vwap is None:
                continue
            out[ts] = {
                "close": close,
                "vwap": vwap,
                "diff": close - vwap,
            }
    return out


def dump_framework(events):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "research_version": "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1",
        "evaluation_adapter": "POST_08SEP_UNSEEN_CONTEXT_FREE_V10",
        "session_date": SESSION,
        "context_enrichment": "SUPPRESSED_NOT_USED_FOR_STRUCTURAL_EVENT",
        "events": events,
    }
    FRAMEWORK_JSON.write_text(json.dumps(payload, indent=2, default=str))


def event_summary(e):
    return (
        f"{e.get('setup_type')} status={e.get('status')} "
        f"ref={e.get('reference_start')}..{e.get('reference_end')} "
        f"H={e.get('reference_high')} L={e.get('reference_low')} "
        f"M={e.get('reference_midpoint')} "
        f"midBreak={e.get('midpoint_break_timestamp')} "
        f"boundaryBreak={e.get('boundary_break_timestamp')} "
        f"primary={e.get('primary_outcome')}"
    )


def write_csv(rows):
    if not rows:
        EVENTS_CSV.write_text("")
        return
    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with EVENTS_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    print("B FAMILY — 2026-09-15 UNSEEN VALIDATION V10")
    print("=" * 118)
    print("Session:", SESSION)
    print("Underlying:", UNDERLYING_CSV)
    print("Futures/VWAP:", FUTURES_CSV)
    print()

    for p in (UNDERLYING_CSV, FUTURES_CSV, CANON_B, V8_2):
        if not p.exists():
            raise SystemExit(f"MISSING REQUIRED FILE: {p}")

    bmod = load_module(CANON_B, "frozen_family_b_v1_1")
    risk = load_module(V8_2, "risk_v8_2")

    minute_rows = build_underlying()
    u = build_underlying_index(minute_rows)
    fut = build_futures_index()

    print("Underlying minute rows:", len(minute_rows))
    print("Underlying indexed rows:", len(u))
    print("Futures/VWAP rows:", len(fut))
    print()

    fw_events = build_framework_events(minute_rows)
    dump_framework(fw_events)

    print("FROZEN FRAMEWORK EVENTS")
    print("-" * 118)
    for e in fw_events:
        print(event_summary(e))
    if not fw_events:
        print("NONE")
    print()

    b_events = []
    for e in fw_events:
        b = bmod.family_b_for_event(e, u, fut)
        if b:
            measured = bmod.measure_event(dict(b), u)
            b_events.append(measured)

    print("FROZEN FAMILY-B EVENTS")
    print("-" * 118)
    if not b_events:
        print("NO_B_EVENT")
    else:
        for ev in b_events:
            print(
                f"{ev['direction']} entry={ev['entry_timestamp']} "
                f"origin={ev['origin_timestamp']} delay={ev['delay_minutes']} "
                f"entry_close={ev.get('entry_close')} "
                f"fut_vwap_diff={ev.get('entry_fut_vwap')} "
                f"MFE={ev.get('mfe')} MAE={ev.get('mae')} "
                f"invalid={ev.get('structural_invalidation_timestamp')}"
            )
    print()

    out_rows = []
    lines = [
        "B FAMILY — 2026-09-15 UNSEEN VALIDATION V10",
        "=" * 118,
        f"session={SESSION}",
        f"framework_events={len(fw_events)}",
        f"b_events={len(b_events)}",
        "",
    ]

    if not b_events:
        lines.append("RESULT: NO_B_EVENT")
        lines.append(
            "This is a valid untouched-session result. No risk-model P&L is fabricated."
        )
    else:
        for ev in b_events:
            atr = risk.causal_atr_1m(u, ev["entry_timestamp"])
            models = [
                (
                    "FIXED_15_LIFECYCLE",
                    15.0,
                    True,
                    risk.risk_then_structural(ev, u, 15.0),
                ),
                (
                    "ATR_1.00_LIFECYCLE",
                    atr,
                    atr is not None,
                    (
                        risk.risk_then_structural(ev, u, atr)
                        if atr is not None
                        else (None, None, "INELIGIBLE_NO_ATR")
                    ),
                ),
                (
                    "STRUCTURAL",
                    None,
                    True,
                    risk.structural_result(ev, u),
                ),
                (
                    "HYBRID_FIXED15_BE20",
                    15.0,
                    True,
                    risk.hybrid_result(ev, u, 15.0),
                ),
                (
                    "HYBRID_MIN15_ATR1_BE20",
                    min(15.0, atr) if atr is not None else None,
                    atr is not None,
                    (
                        risk.hybrid_result(ev, u, min(15.0, atr))
                        if atr is not None
                        else (None, None, "INELIGIBLE_NO_ATR")
                    ),
                ),
            ]

            lines.append(
                f"EVENT {ev['direction']} entry={ev['entry_timestamp']} "
                f"origin={ev['origin_timestamp']} delay={ev['delay_minutes']} "
                f"ATR1m={atr}"
            )

            for model, rp, eligible, result in models:
                exit_ts, points, reason = result
                row = {
                    "session_date": SESSION,
                    "direction": ev["direction"],
                    "entry_timestamp": ev["entry_timestamp"],
                    "origin_timestamp": ev["origin_timestamp"],
                    "delay_minutes": ev["delay_minutes"],
                    "entry_close": ev.get("entry_close"),
                    "entry_fut_vwap": ev.get("entry_fut_vwap"),
                    "mfe": ev.get("mfe"),
                    "mae": ev.get("mae"),
                    "structural_invalidation_timestamp": ev.get(
                        "structural_invalidation_timestamp"
                    ),
                    "atr_1m": atr,
                    "model": model,
                    "eligible": eligible,
                    "risk_points": rp,
                    "exit_timestamp": exit_ts,
                    "exit_reason": reason,
                    "points": points,
                }
                out_rows.append(row)
                lines.append(
                    f"  {model:<30} eligible={eligible} "
                    f"risk={rp} exit={exit_ts} reason={reason} points={points}"
                )
            lines.append("")

    write_csv(out_rows)

    lines += [
        "",
        "IMPORTANT",
        "- This session is post-2026-09-08 and was not part of the canonical 45-event B sample.",
        "- Frozen midpoint structural functions are imported directly.",
        "- Frozen family_b_for_event() and measure_event() are imported directly.",
        "- Evidence/positioning snapshot context is suppressed; it does not drive structural midpoint/boundary detection.",
        "- V8.2 risk functions are imported unchanged.",
        "- Underlying NIFTY points only; not CE/PE premium P&L.",
        "- No production/runtime/order settings are changed.",
    ]

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print(summary)
    print()
    print("FRAMEWORK JSON:", FRAMEWORK_JSON)
    print("EVENTS CSV    :", EVENTS_CSV)
    print("SUMMARY       :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
