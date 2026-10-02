#!/usr/bin/env python3
"""
B FAMILY — FIVE-SESSION POST-08-SEP UNSEEN BATCH VALIDATION V11

Untouched sessions:
  2026-09-10
  2026-09-11
  2026-09-15
  2026-09-17
  2026-09-18

Inputs
------
Underlying:
  data/historical-evidence/hilega-directional-parity-trace-2026-09-25/
    underlying-cache/<DATE>.json

Futures:
  data/live-observation/replay-cache/<DATE>/futures-1m.json

Methodology
-----------
- Frozen opening_candle_midpoint_framework_v1 structural functions.
- Context enrichment (evidence/positioning) suppressed only because it does not
  determine midpoint/boundary/reclaim structure.
- Frozen family_b_for_event() and measure_event().
- Frozen prospective session VWAP implementation imported directly from
  midpoint_v2_nifty_futures_vwap_v1.add_session_vwap().
- Unchanged V8.2 risk functions.

No parameter tuning. No production/runtime/order changes.
Underlying NIFTY points only; not option premium P&L.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from market_lab import opening_candle_midpoint_framework_v1 as framework
from market_lab.midpoint_v2_nifty_futures_vwap_v1 import add_session_vwap

SESSIONS = (
    "2026-09-10",
    "2026-09-11",
    "2026-09-15",
    "2026-09-17",
    "2026-09-18",
)

UNDERLYING_DIR = Path(
    "data/historical-evidence/"
    "hilega-directional-parity-trace-2026-09-25/underlying-cache"
)
FUTURES_ROOT = Path("data/live-observation/replay-cache")

CANON_B = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")

OUTDIR = (
    Path("data/historical-evidence")
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-unseen-validation-v11-post-08sep"
)
FRAMEWORK_JSON = OUTDIR / "framework-events-v11.json"
B_EVENTS_CSV = OUTDIR / "b-events-v11.csv"
MODEL_EVENTS_CSV = OUTDIR / "risk-model-events-v11.csv"
SUMMARY_TXT = OUTDIR / "summary-v11.txt"

MODELS = (
    "FIXED_15_LIFECYCLE",
    "ATR_1.00_LIFECYCLE",
    "STRUCTURAL",
    "HYBRID_FIXED15_BE20",
    "HYBRID_MIN15_ATR1_BE20",
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def f(v):
    if v in (None, ""):
        return None
    return float(v)


def load_json(path: Path):
    return json.loads(path.read_text())


def underlying_rows(session):
    path = UNDERLYING_DIR / f"{session}.json"
    if not path.exists():
        raise FileNotFoundError(path)

    obj = load_json(path)
    candles = obj.get("candles")
    if not isinstance(candles, list) or not candles:
        raise RuntimeError(f"No candles in {path}")

    rows = []
    for c in candles:
        ts = c.get("timestamp")
        if not ts:
            raise RuntimeError(f"Missing timestamp in {path}")
        rows.append(
            {
                "session_date": session,
                "timestamp": ts,
                "open": c.get("open"),
                "high": c.get("high"),
                "low": c.get("low"),
                "close": c.get("close"),
                "volume": c.get("volume", 0),
                "open_interest": c.get("open_interest", 0),
            }
        )

    by_session = framework.underlying_by_session(rows)
    if session not in by_session:
        raise RuntimeError(f"Frozen underlying parser did not produce {session}")
    return path, by_session[session]


def underlying_index(minute_rows):
    out = {}
    for r in minute_rows:
        ts = r.get("timestamp")
        key = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        out[key] = {
            "open": f(r.get("open")),
            "high": f(r.get("high")),
            "low": f(r.get("low")),
            "close": f(r.get("close")),
            "volume": f(r.get("volume")),
        }
    return out


def futures_index(session):
    path = FUTURES_ROOT / session / "futures-1m.json"
    if not path.exists():
        raise FileNotFoundError(path)

    obj = load_json(path)
    candles = obj.get("candles")
    if not isinstance(candles, list) or not candles:
        raise RuntimeError(f"No candles in {path}")

    raw = []
    for c in candles:
        raw.append(
            {
                "timestamp": c["timestamp"],
                "open": f(c["open"]),
                "high": f(c["high"]),
                "low": f(c["low"]),
                "close": f(c["close"]),
                "volume": int(c["volume"]) if c.get("volume") is not None else None,
                "open_interest": (
                    int(c["open_interest"])
                    if c.get("open_interest") is not None
                    else None
                ),
            }
        )

    raw.sort(key=lambda r: r["timestamp"])

    # Import the exact frozen prospective VWAP implementation.
    enriched = add_session_vwap(raw)

    out = {}
    for r in enriched:
        if r["session_vwap"] is None:
            continue
        out[r["timestamp"]] = {
            "close": r["close"],
            "vwap": r["session_vwap"],
            "diff": r["close"] - r["session_vwap"],
            "volume": r["volume"],
        }

    return path, out, enriched


def build_framework_events(session, minute_rows):
    original_attach = framework.attach_context
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
                    session_date=session,
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
                    session_date=session,
                    minute_rows=minute_rows,
                    bar=green,
                    colour="GREEN",
                    evidence_idx={},
                    atm_idx={},
                )
            )
        return events
    finally:
        framework.attach_context = original_attach


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def fmt(v):
    return "-" if v is None else f"{v:+.2f}"


def max_consecutive_losses(points):
    best = cur = 0
    for p in points:
        if p < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def max_drawdown(points):
    equity = peak = 0.0
    worst = 0.0
    for p in points:
        equity += p
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def model_summary(rows):
    clean = [r for r in rows if r["eligible"] and r["points"] is not None]
    amb = [r for r in rows if r["eligible"] and r["points"] is None]
    ineligible = [r for r in rows if not r["eligible"]]
    pts = [r["points"] for r in clean]
    wins = [p for p in pts if p > 0]
    losses = [p for p in pts if p < 0]
    flats = [p for p in pts if p == 0]

    out = (
        f"events={len(rows)} clean={len(clean)} ambiguous={len(amb)} "
        f"ineligible={len(ineligible)} wins={len(wins)} "
        f"losses={len(losses)} flats={len(flats)}"
    )
    if clean:
        out += (
            f" winRate={100*len(wins)/len(clean):.1f}%"
            f" expectancy={fmt(mean(pts))}"
            f" total={fmt(sum(pts))}"
            f" avgWin={fmt(mean(wins) if wins else None)}"
            f" avgLoss={fmt(mean(losses) if losses else None)}"
            f" maxCL={max_consecutive_losses(pts)}"
            f" maxDD={fmt(max_drawdown(pts))}"
        )
    return out


def main():
    print("B FAMILY — FIVE-SESSION POST-08-SEP UNSEEN BATCH VALIDATION V11")
    print("=" * 118)
    print("Sessions:", ", ".join(SESSIONS))
    print("No threshold tuning. Frozen B + frozen VWAP + unchanged V8.2 risk.")
    print()

    if not CANON_B.exists():
        raise SystemExit(f"MISSING: {CANON_B}")
    if not V8_2.exists():
        raise SystemExit(f"MISSING: {V8_2}")

    bmod = load_module(CANON_B, "frozen_family_b_v1_1")
    risk = load_module(V8_2, "risk_v8_2")

    all_framework = []
    all_b = []
    all_models = []
    session_stats = []

    for session in SESSIONS:
        print("=" * 118)
        print("SESSION", session)

        upath, minute_rows = underlying_rows(session)
        u = underlying_index(minute_rows)

        fpath, fut, fut_rows = futures_index(session)

        print("Underlying file :", upath)
        print("Underlying SHA  :", sha256(upath))
        print("Underlying rows :", len(minute_rows))
        print("Futures file    :", fpath)
        print("Futures SHA     :", sha256(fpath))
        print("Futures rows    :", len(fut_rows))
        print("VWAP rows       :", len(fut))

        fw_events = build_framework_events(session, minute_rows)

        for e in fw_events:
            e2 = dict(e)
            e2["_session"] = session
            all_framework.append(e2)

        print("Framework events:")
        for e in fw_events:
            print(
                f"  {e.get('setup_type')} status={e.get('status')} "
                f"ref={str(e.get('reference_start'))[11:16]}-"
                f"{str(e.get('reference_end'))[11:16]} "
                f"midBreak={str(e.get('midpoint_break_timestamp'))[11:16] if e.get('midpoint_break_timestamp') else '-'} "
                f"boundaryBreak={str(e.get('boundary_break_timestamp'))[11:16] if e.get('boundary_break_timestamp') else '-'} "
                f"primary={e.get('primary_outcome')}"
            )

        b_events = []
        for e in fw_events:
            b = bmod.family_b_for_event(e, u, fut)
            if b:
                measured = bmod.measure_event(dict(b), u)
                b_events.append(measured)
                all_b.append(measured)

        if not b_events:
            print("Family B: NO_B_EVENT")
        else:
            print("Family B:")
            for ev in b_events:
                print(
                    f"  {ev['direction']} entry={ev['entry_timestamp'][11:16]} "
                    f"origin={ev['origin_timestamp'][11:16]} "
                    f"delay={ev['delay_minutes']} "
                    f"entry={ev.get('entry_close')} "
                    f"VWAPdiff={ev.get('entry_fut_vwap')} "
                    f"MFE={ev.get('mfe')} MAE={ev.get('mae')} "
                    f"invalid={str(ev.get('structural_invalidation_timestamp'))[11:16] if ev.get('structural_invalidation_timestamp') else '-'}"
                )

        model_count_before = len(all_models)

        for ev in b_events:
            atr = risk.causal_atr_1m(u, ev["entry_timestamp"])

            model_results = [
                (
                    "FIXED_15_LIFECYCLE",
                    True,
                    15.0,
                    risk.risk_then_structural(ev, u, 15.0),
                ),
                (
                    "ATR_1.00_LIFECYCLE",
                    atr is not None,
                    atr,
                    (
                        risk.risk_then_structural(ev, u, atr)
                        if atr is not None
                        else (None, None, "INELIGIBLE_NO_ATR")
                    ),
                ),
                (
                    "STRUCTURAL",
                    True,
                    None,
                    risk.structural_result(ev, u),
                ),
                (
                    "HYBRID_FIXED15_BE20",
                    True,
                    15.0,
                    risk.hybrid_result(ev, u, 15.0),
                ),
                (
                    "HYBRID_MIN15_ATR1_BE20",
                    atr is not None,
                    min(15.0, atr) if atr is not None else None,
                    (
                        risk.hybrid_result(ev, u, min(15.0, atr))
                        if atr is not None
                        else (None, None, "INELIGIBLE_NO_ATR")
                    ),
                ),
            ]

            for model, eligible, risk_points, result in model_results:
                exit_ts, points, reason = result
                row = {
                    "session_date": session,
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
                    "risk_points": risk_points,
                    "exit_timestamp": exit_ts,
                    "exit_reason": reason,
                    "points": points,
                }
                all_models.append(row)

        if len(all_models) > model_count_before:
            print("Risk results:")
            for r in all_models[model_count_before:]:
                print(
                    f"  {r['model']:<29} risk={r['risk_points']} "
                    f"exit={str(r['exit_timestamp'])[11:16] if r['exit_timestamp'] else '-'} "
                    f"reason={r['exit_reason']} points={r['points']}"
                )

        session_stats.append(
            {
                "session_date": session,
                "framework_events": len(fw_events),
                "b_events": len(b_events),
            }
        )
        print()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    FRAMEWORK_JSON.write_text(
        json.dumps(
            {
                "research_version": "B_FAMILY_POST_08SEP_UNSEEN_BATCH_V11",
                "sessions": SESSIONS,
                "context_enrichment": "SUPPRESSED_NOT_STRUCTURAL",
                "events": all_framework,
            },
            indent=2,
            default=str,
        )
    )
    write_csv(B_EVENTS_CSV, all_b)
    write_csv(MODEL_EVENTS_CSV, all_models)

    lines = [
        "B FAMILY — FIVE-SESSION POST-08-SEP UNSEEN BATCH VALIDATION V11",
        "=" * 118,
        f"sessions={len(SESSIONS)}",
        f"framework_events={len(all_framework)}",
        f"b_events={len(all_b)}",
        "",
        "SESSION COUNTS",
        "-" * 118,
    ]

    for s in session_stats:
        lines.append(
            f"{s['session_date']} framework={s['framework_events']} B={s['b_events']}"
        )

    lines += ["", "B EVENTS", "-" * 118]
    if not all_b:
        lines.append("NO B EVENTS ACROSS THE FIVE UNSEEN SESSIONS")
    else:
        for ev in all_b:
            lines.append(
                f"{ev['session_date']} {ev['direction']} "
                f"entry={ev['entry_timestamp']} origin={ev['origin_timestamp']} "
                f"delay={ev['delay_minutes']} entry_close={ev.get('entry_close')} "
                f"vwap_diff={ev.get('entry_fut_vwap')} "
                f"MFE={ev.get('mfe')} MAE={ev.get('mae')} "
                f"invalid={ev.get('structural_invalidation_timestamp')}"
            )

    lines += ["", "RISK MODEL SUMMARY", "-" * 118]
    for model in MODELS:
        rows = [r for r in all_models if r["model"] == model]
        lines.append(f"{model:<29} {model_summary(rows)}")

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- 15 Sep NO_B_EVENT is retained; zero-event sessions are not discarded.",
        "- These sessions are all after the canonical 45-event sample ending 2026-09-08.",
        "- Session VWAP is the frozen prospective cumulative typical-price*volume implementation.",
        "- No parameter is changed after observing these sessions.",
        "- Small unseen sample: descriptive validation only; do not freeze production risk yet.",
        "- Underlying NIFTY points only; not CE/PE option-premium P&L.",
        "- No runtime/execution/order code is changed.",
    ]

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print()
    print(summary)
    print()
    print("FRAMEWORK JSON :", FRAMEWORK_JSON)
    print("B EVENTS CSV   :", B_EVENTS_CSV)
    print("MODEL CSV      :", MODEL_EVENTS_CSV)
    print("SUMMARY        :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
