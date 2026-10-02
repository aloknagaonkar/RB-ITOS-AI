#!/usr/bin/env python3
"""
B FAMILY — RISK MODEL COMPARISON V8.1

Purpose
-------
Compare four risk-management models on the same 45 canonical B events:

A) FIXED_15
   Fixed 15-point NIFTY stop.

B) ATR
   Small predeclared ATR set:
      0.5 ATR, 0.75 ATR, 1.0 ATR
   ATR is computed causally from underlying 1m bars strictly before B entry.

C) STRUCTURAL
   Exit on canonical parent midpoint invalidation.

D) HYBRID
   Emergency fixed-15 cap until trade first reaches +20 favorable points.
   After +20, emergency cap is retired and the trade uses structural exit.
   This is intentionally simple and predeclared; it is NOT optimized.

Outcome comparison
------------------
All models use the same entry.
No fixed profit target is imposed in this V8 pass.
If a model survives without stop/invalidation, exit at 15:14 close.

Metrics
-------
- win rate
- avg / median winner
- avg / median loser
- expectancy per trade
- total points
- max consecutive losses
- max drawdown
- preservation of +30 / +50 / +75 / +100 opportunity events
- development 18 vs older 27 vs combined
- bull / bear splits

Important
---------
Underlying NIFTY points only. Not option-premium P&L.
ATR choices are a small predeclared research set, not an optimization grid.
"""

from __future__ import annotations

import csv
import importlib.util
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

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
    / "b-family-risk-model-comparison-v8-1"
)
EVENT_CSV = OUT / "b-family-risk-model-events-v8-1.csv"
SUMMARY_TXT = OUT / "b-family-risk-model-summary-v8-1.txt"

ATR_MULTIPLIERS = (0.5, 0.75, 1.0)
ATR_PERIOD = 14
FIXED_STOP = 15.0
HYBRID_PROVE_LEVEL = 20.0
TRUSTED_END = "15:14"


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


def dmove(direction, entry, later):
    return later - entry if direction == "BULLISH" else entry - later


def known_latest60_keys():
    rows = list(csv.DictReader(open(KNOWN, newline="")))
    return {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in rows
        if r.get("family") == "B_DELAYED_FULL_CANDIDATE_A"
    }


def canonical_events(m):
    _, framework = m.load_framework()
    _, underlying, dup_conflicts = m.load_underlying()
    futures = m.load_futures()

    sessions = sorted({e["session_date"] for e in framework})
    latest60 = set(sessions[-60:])

    events = []
    for e in framework:
        day = e["session_date"]
        b = m.family_b_for_event(e, underlying.get(day, {}), futures.get(day, {}))
        if not b:
            continue
        ev = m.measure_event(dict(b), underlying.get(day, {}))
        ev["sample"] = "DEVELOPMENT_LATEST60" if day in latest60 else "OLDER_120"
        events.append(ev)

    events.sort(key=lambda r:(r["session_date"], r["entry_timestamp"], r["direction"]))

    dev_keys = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in events if r["sample"] == "DEVELOPMENT_LATEST60"
    }
    return events, underlying, dup_conflicts, (dev_keys == known_latest60_keys())


def parse_dt(s):
    return datetime.fromisoformat(s)


def true_range(bar, prev_close):
    h, l = bar["high"], bar["low"]
    if prev_close is None:
        return h - l
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


def causal_atr_1m(daybars, entry_ts, period=ATR_PERIOD):
    stamps = sorted(ts for ts in daybars if ts < entry_ts and ts[11:16] >= "09:15")
    if len(stamps) < period:
        return None

    trs = []
    prev_close = None
    for ts in stamps:
        bar = daybars[ts]
        tr = true_range(bar, prev_close)
        trs.append(tr)
        prev_close = bar["close"]

    # Wilder ATR over available causal bars; seed with first `period`.
    if len(trs) < period:
        return None

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = ((period - 1) * atr + tr) / period
    return atr


def post_entry_bars(ev, daybars, include_invalidation=True):
    entry_ts = ev["entry_timestamp"]
    invalid = ev.get("structural_invalidation_timestamp") or ""
    out = []
    for ts, bar in sorted(daybars.items()):
        if ts <= entry_ts or ts[11:16] > TRUSTED_END:
            continue
        if invalid:
            if include_invalidation and ts > invalid:
                break
            if not include_invalidation and ts >= invalid:
                break
        out.append((ts, bar))
    return out


def fixed_stop_result(ev, daybars, stop_points):
    direction = ev["direction"]
    entry = num(ev["entry_close"])

    for ts, bar in post_entry_bars(ev, daybars, include_invalidation=True):
        if direction == "BULLISH":
            hit = bar["low"] <= entry - stop_points
        else:
            hit = bar["high"] >= entry + stop_points
        if hit:
            return ts, -float(stop_points), "STOP"

    stamps = [ts for ts in daybars if ts > ev["entry_timestamp"] and ts[11:16] <= TRUSTED_END]
    if not stamps:
        return None, None, "NO_EXIT_DATA"
    ts = sorted(stamps)[-1]
    return ts, dmove(direction, entry, daybars[ts]["close"]), "SESSION_EXIT"


def structural_result(ev, daybars):
    direction = ev["direction"]
    entry = num(ev["entry_close"])
    invalid = ev.get("structural_invalidation_timestamp") or ""

    if invalid and invalid in daybars:
        return invalid, dmove(direction, entry, daybars[invalid]["close"]), "STRUCTURAL_EXIT"

    stamps = [ts for ts in daybars if ts > ev["entry_timestamp"] and ts[11:16] <= TRUSTED_END]
    if not stamps:
        return None, None, "NO_EXIT_DATA"
    ts = sorted(stamps)[-1]
    return ts, dmove(direction, entry, daybars[ts]["close"]), "SESSION_EXIT"


def hybrid_result(ev, daybars):
    """
    Emergency fixed-15 until trade first proves itself by reaching +20.
    After proof, use structural exit only.
    Same-bar stop+proof is ambiguous and excluded from clean stats.
    """
    direction = ev["direction"]
    entry = num(ev["entry_close"])
    invalid = ev.get("structural_invalidation_timestamp") or ""
    proved = False

    for ts, bar in sorted(daybars.items()):
        if ts <= ev["entry_timestamp"] or ts[11:16] > TRUSTED_END:
            continue

        if invalid and ts > invalid:
            break

        if direction == "BULLISH":
            stop_hit = bar["low"] <= entry - FIXED_STOP
            prove_hit = bar["high"] >= entry + HYBRID_PROVE_LEVEL
        else:
            stop_hit = bar["high"] >= entry + FIXED_STOP
            prove_hit = bar["low"] <= entry - HYBRID_PROVE_LEVEL

        if not proved:
            if stop_hit and prove_hit:
                return ts, None, "AMBIGUOUS_STOP_AND_PROVE_SAME_BAR"
            if stop_hit:
                return ts, -FIXED_STOP, "EMERGENCY_STOP"
            if prove_hit:
                proved = True

        if invalid and ts == invalid:
            return ts, dmove(direction, entry, bar["close"]), "STRUCTURAL_EXIT_AFTER_PROOF" if proved else "STRUCTURAL_EXIT"

    stamps = [ts for ts in daybars if ts > ev["entry_timestamp"] and ts[11:16] <= TRUSTED_END]
    if not stamps:
        return None, None, "NO_EXIT_DATA"
    ts = sorted(stamps)[-1]
    return ts, dmove(direction, entry, daybars[ts]["close"]), "SESSION_EXIT_AFTER_PROOF" if proved else "SESSION_EXIT"


def max_consecutive_losses(points):
    best = cur = 0
    for p in points:
        if p is not None and p < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def max_drawdown(points):
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for p in points:
        if p is None:
            continue
        equity += p
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd


def fmt(v):
    return "-" if v is None else f"{v:+.2f}"


def summarize(name, rows):
    clean = [r for r in rows if r["points"] is not None]
    pts = [r["points"] for r in clean]
    wins = [p for p in pts if p > 0]
    losses = [p for p in pts if p < 0]
    flats = [p for p in pts if p == 0]

    lines = []
    lines.append(name)
    lines.append("-" * 118)
    lines.append(
        f"events={len(rows)} clean={len(clean)} ambiguous={len(rows)-len(clean)} "
        f"wins={len(wins)} losses={len(losses)} flats={len(flats)}"
    )
    if clean:
        lines.append(
            f"winRate={100*len(wins)/len(clean):.1f}% "
            f"avgWin={fmt(mean(wins) if wins else None)} "
            f"medianWin={fmt(median(wins) if wins else None)} "
            f"avgLoss={fmt(mean(losses) if losses else None)} "
            f"medianLoss={fmt(median(losses) if losses else None)}"
        )
        lines.append(
            f"expectancy={fmt(mean(pts))} total={fmt(sum(pts))} "
            f"maxConsecutiveLosses={max_consecutive_losses(pts)} "
            f"maxDrawdown={fmt(max_drawdown(pts))}"
        )

    for level in (30,50,75,100):
        opp = [r for r in rows if r["source_mfe"] is not None and r["source_mfe"] >= level]
        preserved = [
            r for r in opp
            if r["points"] is not None and r.get(f"exit_before_{level}") is False
        ]
        ambiguous = [
            r for r in opp
            if r["points"] is None
        ]
        lines.append(
            f"preserve +{level} opportunity: {len(preserved)}/{len(opp)} "
            f"ambiguous={len(ambiguous)}"
        )
    return lines


def first_level_time(ev, daybars, level):
    direction = ev["direction"]
    entry = num(ev["entry_close"])
    for ts, bar in sorted(daybars.items()):
        if ts <= ev["entry_timestamp"] or ts[11:16] > TRUSTED_END:
            continue
        if direction == "BULLISH":
            if bar["high"] >= entry + level:
                return ts
        else:
            if bar["low"] <= entry - level:
                return ts
    return None


def main():
    m = load_canonical()
    events, underlying, dup_conflicts, parity = canonical_events(m)

    print("B FAMILY — RISK MODEL COMPARISON V8.1")
    print("=" * 118)
    print("Canonical events :", len(events))
    print("Development      :", sum(r["sample"]=="DEVELOPMENT_LATEST60" for r in events))
    print("Older            :", sum(r["sample"]=="OLDER_120" for r in events))
    print("Latest60 parity  :", parity)
    print("Duplicate conflicts:", dup_conflicts)

    if not parity:
        raise SystemExit("ABORT: canonical parity failed.")

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []

    for ev in events:
        day = ev["session_date"]
        daybars = underlying.get(day, {})
        atr = causal_atr_1m(daybars, ev["entry_timestamp"])

        model_specs = [("FIXED_15", FIXED_STOP)]

        if atr is not None:
            for mult in ATR_MULTIPLIERS:
                model_specs.append((f"ATR_{mult:.2f}", atr * mult))

        for model, risk in model_specs:
            if model == "FIXED_15":
                exit_ts, points, reason = fixed_stop_result(ev, daybars, risk)
            else:
                exit_ts, points, reason = fixed_stop_result(ev, daybars, risk)

            rec = {
                "sample": ev["sample"],
                "session_date": day,
                "direction": ev["direction"],
                "entry_timestamp": ev["entry_timestamp"],
                "entry_close": num(ev["entry_close"]),
                "model": model,
                "risk_points": risk,
                "atr_1m": atr,
                "exit_timestamp": exit_ts,
                "exit_reason": reason,
                "points": points,
                "source_mfe": num(ev.get("mfe")),
                "source_mae": num(ev.get("mae")),
            }

            for level in (30,50,75,100):
                t = first_level_time(ev, daybars, level)
                rec[f"level_{level}_timestamp"] = t
                rec[f"exit_before_{level}"] = bool(exit_ts and t and exit_ts < t)

            rows.append(rec)

        # Structural
        exit_ts, points, reason = structural_result(ev, daybars)
        rec = {
            "sample": ev["sample"],
            "session_date": day,
            "direction": ev["direction"],
            "entry_timestamp": ev["entry_timestamp"],
            "entry_close": num(ev["entry_close"]),
            "model": "STRUCTURAL",
            "risk_points": None,
            "atr_1m": atr,
            "exit_timestamp": exit_ts,
            "exit_reason": reason,
            "points": points,
            "source_mfe": num(ev.get("mfe")),
            "source_mae": num(ev.get("mae")),
        }
        for level in (30,50,75,100):
            t = first_level_time(ev, daybars, level)
            rec[f"level_{level}_timestamp"] = t
            rec[f"exit_before_{level}"] = bool(exit_ts and t and exit_ts < t)
        rows.append(rec)

        # Hybrid
        exit_ts, points, reason = hybrid_result(ev, daybars)
        rec = {
            "sample": ev["sample"],
            "session_date": day,
            "direction": ev["direction"],
            "entry_timestamp": ev["entry_timestamp"],
            "entry_close": num(ev["entry_close"]),
            "model": "HYBRID_15_THEN_STRUCTURAL_AFTER_20",
            "risk_points": FIXED_STOP,
            "atr_1m": atr,
            "exit_timestamp": exit_ts,
            "exit_reason": reason,
            "points": points,
            "source_mfe": num(ev.get("mfe")),
            "source_mae": num(ev.get("mae")),
        }
        for level in (30,50,75,100):
            t = first_level_time(ev, daybars, level)
            rec[f"level_{level}_timestamp"] = t
            rec[f"exit_before_{level}"] = bool(exit_ts and t and exit_ts < t)
        rows.append(rec)

    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)

    with open(EVENT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    models = [
        "FIXED_15",
        "ATR_0.50",
        "ATR_0.75",
        "ATR_1.00",
        "STRUCTURAL",
        "HYBRID_15_THEN_STRUCTURAL_AFTER_20",
    ]

    lines = []
    lines.append("B FAMILY — RISK MODEL COMPARISON V8.1")
    lines.append("=" * 118)
    lines.append("Canonical detector parity: PASS")
    lines.append(f"Events: {len(events)}")
    lines.append("")

    for model in models:
        model_rows = [r for r in rows if r["model"] == model]
        if not model_rows:
            continue
        lines.append(f"MODEL: {model}")
        lines.append("=" * 118)

        for label, selector in (
            ("COMBINED_45", lambda r: True),
            ("DEVELOPMENT_18", lambda r: r["sample"]=="DEVELOPMENT_LATEST60"),
            ("OLDER_27", lambda r: r["sample"]=="OLDER_120"),
            ("BULLISH", lambda r: r["direction"]=="BULLISH"),
            ("BEARISH", lambda r: r["direction"]=="BEARISH"),
        ):
            g = [r for r in model_rows if selector(r)]
            lines.extend(summarize(label, g))
            lines.append("")

    lines.append("EVENT DETAIL")
    lines.append("=" * 118)
    for r in rows:
        lines.append(
            f"{r['model']} {r['sample']} {r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp'][11:16]} "
            f"ATR={r['atr_1m']} risk={r['risk_points']} "
            f"exit={(r['exit_timestamp'][11:16] if r['exit_timestamp'] else '-')} "
            f"reason={r['exit_reason']} points={r['points']} "
            f"MFE={r['source_mfe']} MAE={r['source_mae']}"
        )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- V8 compares risk models; it does not freeze one.")
    lines.append("- ATR is causal 1m Wilder ATR(14) from bars strictly before B entry.")
    lines.append("- ATR multipliers are predeclared: 0.5 / 0.75 / 1.0 only.")
    lines.append("- Hybrid is predeclared: fixed-15 emergency cap until +20, then structural exit.")
    lines.append("- If stop and +20 proof occur in same 1m candle, hybrid marks the event ambiguous.")
    lines.append("- Underlying NIFTY points are not CE/PE option-premium P&L.")

    text = "\n".join(lines)
    SUMMARY_TXT.write_text(text)

    print()
    print(text)
    print()
    print("EVENT CSV:", EVENT_CSV)
    print("SUMMARY  :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
