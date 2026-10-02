#!/usr/bin/env python3
"""
B FAMILY — LIFECYCLE-CONSISTENT RISK COMPARISON V8.2

Why V8.2 exists
---------------
V8.1 exposed an unfair comparison: fixed/ATR models could survive beyond the
canonical B structural invalidation and continue to 15:14, while STRUCTURAL
and HYBRID respected B lifecycle termination.

V8.2 fixes that.

Every model now uses the same canonical B lifecycle:
  entry -> risk handling -> canonical structural invalidation -> session close

No model may earn points after canonical B invalidation.

Models
------
1) FIXED_15_LIFECYCLE
   -15 NIFTY point emergency stop.
   Otherwise canonical structural invalidation.
   Otherwise 15:14 close.

2) ATR_1.00_LIFECYCLE
   1.0 x causal 1m Wilder ATR(14) emergency stop.
   Otherwise canonical structural invalidation.
   Otherwise 15:14 close.
   ATR unavailable => event excluded from this model.

3) STRUCTURAL
   Canonical structural invalidation only.
   Otherwise 15:14 close.

4) HYBRID_FIXED15_BE20
   Before first +20 favorable excursion:
       fixed -15 emergency stop.
   After +20 is proven:
       breakeven floor at entry.
       structural invalidation may exit while still profitable.
   Otherwise 15:14 close.

5) HYBRID_MIN15_ATR1_BE20
   Before first +20:
       emergency risk = min(15 points, 1.0 x ATR).
   After +20:
       breakeven floor + structural invalidation.
   ATR unavailable => event excluded.

Comparison sets
---------------
- FULL_45 where model is eligible.
- COMMON_ATR_ELIGIBLE only: identical ATR-available events across ALL models.
- Development vs Older validation.
- Bull vs Bear.

Intrabar handling
-----------------
1m OHLC does not reveal high/low ordering.
If the pre-proof emergency stop and +20 proof are both touched in the same bar,
the hybrid event is AMBIGUOUS and is excluded from clean expectancy statistics.

After +20 proof:
- a later touch of entry exits at breakeven.
- on the proof candle itself, if entry is also touched and close remains above
  entry, high/low order is ambiguous; mark AMBIGUOUS.
- if proof occurs and that candle closes through entry, a post-proof crossing
  of entry is guaranteed, so breakeven is used.

Research only. Underlying NIFTY points are NOT CE/PE premium P&L.
"""

from __future__ import annotations

import csv
import importlib.util
from collections import Counter
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
    / "b-family-risk-model-comparison-v8-2"
)
EVENT_CSV = OUT / "b-family-risk-model-events-v8-2.csv"
SUMMARY_TXT = OUT / "b-family-risk-model-summary-v8-2.txt"

ATR_PERIOD = 14
FIXED_STOP = 15.0
PROVE_LEVEL = 20.0
TRUSTED_END = "15:14"
LEVELS = (30, 50, 75, 100)


def load_canonical():
    spec = importlib.util.spec_from_file_location("bcanon_v1_1", CANON)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def num(v):
    if v in (None, ""):
        return None
    return float(v)


def dmove(direction, entry, later):
    return later - entry if direction == "BULLISH" else entry - later


def favorable_hit(direction, entry, bar, points):
    if direction == "BULLISH":
        return bar["high"] >= entry + points
    return bar["low"] <= entry - points


def adverse_hit(direction, entry, bar, points):
    if direction == "BULLISH":
        return bar["low"] <= entry - points
    return bar["high"] >= entry + points


def breakeven_touched(direction, entry, bar):
    if direction == "BULLISH":
        return bar["low"] <= entry
    return bar["high"] >= entry


def known_latest60_keys():
    with open(KNOWN, newline="") as f:
        rows = list(csv.DictReader(f))
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
        b = m.family_b_for_event(
            e,
            underlying.get(day, {}),
            futures.get(day, {}),
        )
        if not b:
            continue

        ev = m.measure_event(dict(b), underlying.get(day, {}))
        ev["sample"] = (
            "DEVELOPMENT_LATEST60"
            if day in latest60
            else "OLDER_120"
        )
        events.append(ev)

    events.sort(
        key=lambda r: (
            r["session_date"],
            r["entry_timestamp"],
            r["direction"],
        )
    )

    dev_keys = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in events
        if r["sample"] == "DEVELOPMENT_LATEST60"
    }

    return (
        events,
        underlying,
        dup_conflicts,
        dev_keys == known_latest60_keys(),
    )


def true_range(bar, prev_close):
    h, l = bar["high"], bar["low"]
    if prev_close is None:
        return h - l
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


def causal_atr_1m(daybars, entry_ts, period=ATR_PERIOD):
    stamps = sorted(
        ts
        for ts in daybars
        if ts < entry_ts and "09:15" <= ts[11:16] <= TRUSTED_END
    )
    if len(stamps) < period:
        return None

    trs = []
    prev_close = None
    for ts in stamps:
        bar = daybars[ts]
        trs.append(true_range(bar, prev_close))
        prev_close = bar["close"]

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = ((period - 1) * atr + tr) / period
    return atr


def lifecycle_bars(ev, daybars):
    """Bars after entry through invalidation candle, otherwise through 15:14."""
    invalid = ev.get("structural_invalidation_timestamp") or ""
    out = []
    for ts, bar in sorted(daybars.items()):
        if ts <= ev["entry_timestamp"] or ts[11:16] > TRUSTED_END:
            continue
        if invalid and ts > invalid:
            break
        out.append((ts, bar))
    return out


def session_exit(ev, daybars):
    stamps = sorted(
        ts
        for ts in daybars
        if ts > ev["entry_timestamp"] and ts[11:16] <= TRUSTED_END
    )
    if not stamps:
        return None, None, "NO_EXIT_DATA"
    ts = stamps[-1]
    entry = num(ev["entry_close"])
    return (
        ts,
        dmove(ev["direction"], entry, daybars[ts]["close"]),
        "SESSION_EXIT",
    )


def risk_then_structural(ev, daybars, risk_points):
    """Emergency stop; otherwise structural invalidation; otherwise session exit."""
    if risk_points is None:
        return None, None, "INELIGIBLE_NO_RISK"

    direction = ev["direction"]
    entry = num(ev["entry_close"])
    invalid = ev.get("structural_invalidation_timestamp") or ""

    for ts, bar in lifecycle_bars(ev, daybars):
        if adverse_hit(direction, entry, bar, risk_points):
            return ts, -float(risk_points), "EMERGENCY_STOP"

        if invalid and ts == invalid:
            return (
                ts,
                dmove(direction, entry, bar["close"]),
                "STRUCTURAL_EXIT",
            )

    return session_exit(ev, daybars)


def structural_result(ev, daybars):
    direction = ev["direction"]
    entry = num(ev["entry_close"])
    invalid = ev.get("structural_invalidation_timestamp") or ""

    if invalid and invalid in daybars:
        return (
            invalid,
            dmove(direction, entry, daybars[invalid]["close"]),
            "STRUCTURAL_EXIT",
        )

    return session_exit(ev, daybars)


def hybrid_result(ev, daybars, initial_risk):
    if initial_risk is None:
        return None, None, "INELIGIBLE_NO_RISK"

    direction = ev["direction"]
    entry = num(ev["entry_close"])
    invalid = ev.get("structural_invalidation_timestamp") or ""
    proved = False

    for ts, bar in lifecycle_bars(ev, daybars):
        stop_hit = adverse_hit(direction, entry, bar, initial_risk)
        prove_hit = favorable_hit(direction, entry, bar, PROVE_LEVEL)

        if not proved:
            if stop_hit and prove_hit:
                return ts, None, "AMBIGUOUS_STOP_AND_PROVE_SAME_BAR"

            if stop_hit:
                return ts, -float(initial_risk), "EMERGENCY_STOP"

            if prove_hit:
                proved = True

                # On the proof bar itself, entry may also have been touched.
                # If close crosses through entry after reaching +20, BE is guaranteed.
                close_points = dmove(direction, entry, bar["close"])
                if close_points <= 0:
                    return ts, 0.0, "BREAKEVEN_ON_PROOF_BAR"

                # If entry was touched somewhere in the same proof candle but the
                # candle closes positive, order of high/low is unknown.
                if breakeven_touched(direction, entry, bar):
                    return ts, None, "AMBIGUOUS_PROOF_AND_BE_SAME_BAR"

                if invalid and ts == invalid:
                    return ts, close_points, "STRUCTURAL_EXIT_AFTER_PROOF"

                continue

            if invalid and ts == invalid:
                return (
                    ts,
                    dmove(direction, entry, bar["close"]),
                    "STRUCTURAL_EXIT_BEFORE_PROOF",
                )

        else:
            # Once proved on an earlier candle, entry is a hard BE floor.
            if breakeven_touched(direction, entry, bar):
                return ts, 0.0, "BREAKEVEN_AFTER_PROOF"

            if invalid and ts == invalid:
                return (
                    ts,
                    dmove(direction, entry, bar["close"]),
                    "STRUCTURAL_EXIT_AFTER_PROOF",
                )

    ts, points, reason = session_exit(ev, daybars)
    if ts is None:
        return ts, points, reason
    return ts, points, (
        "SESSION_EXIT_AFTER_PROOF"
        if proved else
        "SESSION_EXIT_BEFORE_PROOF"
    )


def first_level_time(ev, daybars, level):
    """
    Canonical opportunity: only bars strictly before structural invalidation,
    matching canonical MFE measurement semantics.
    """
    direction = ev["direction"]
    entry = num(ev["entry_close"])
    invalid = ev.get("structural_invalidation_timestamp") or ""

    for ts, bar in sorted(daybars.items()):
        if ts <= ev["entry_timestamp"] or ts[11:16] > TRUSTED_END:
            continue
        if invalid and ts >= invalid:
            break
        if favorable_hit(direction, entry, bar, level):
            return ts
    return None


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


def fmt(v):
    return "-" if v is None else f"{v:+.2f}"


def summarize(label, rows):
    clean = [r for r in rows if r["points"] is not None]
    ambiguous = [r for r in rows if r["eligible"] and r["points"] is None]
    ineligible = [r for r in rows if not r["eligible"]]

    pts = [r["points"] for r in clean]
    wins = [p for p in pts if p > 0]
    losses = [p for p in pts if p < 0]
    flats = [p for p in pts if p == 0]

    lines = [label, "-" * 118]
    lines.append(
        f"rows={len(rows)} clean={len(clean)} ambiguous={len(ambiguous)} "
        f"ineligible={len(ineligible)} wins={len(wins)} losses={len(losses)} flats={len(flats)}"
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

    for level in LEVELS:
        opp = [r for r in rows if r["eligible"] and r[f"level_{level}_timestamp"]]
        preserved = [
            r for r in opp
            if r["points"] is not None
            and (
                r["exit_timestamp"] is None
                or r["exit_timestamp"] >= r[f"level_{level}_timestamp"]
            )
        ]
        amb = [r for r in opp if r["points"] is None]
        lines.append(
            f"preserve +{level} canonical opportunity: "
            f"{len(preserved)}/{len(opp)} ambiguous={len(amb)}"
        )

    return lines


def make_row(ev, daybars, atr, model, eligible, risk_points, result):
    exit_ts, points, reason = result
    row = {
        "sample": ev["sample"],
        "session_date": ev["session_date"],
        "direction": ev["direction"],
        "entry_timestamp": ev["entry_timestamp"],
        "entry_close": num(ev["entry_close"]),
        "model": model,
        "eligible": eligible,
        "atr_1m": atr,
        "risk_points": risk_points,
        "exit_timestamp": exit_ts,
        "exit_reason": reason,
        "points": points,
        "source_mfe": num(ev.get("mfe")),
        "source_mae": num(ev.get("mae")),
        "structural_invalidation_timestamp": ev.get(
            "structural_invalidation_timestamp"
        ),
    }

    for level in LEVELS:
        row[f"level_{level}_timestamp"] = first_level_time(
            ev, daybars, level
        )

    return row


def main():
    m = load_canonical()
    events, underlying, dup_conflicts, parity = canonical_events(m)

    print("B FAMILY — LIFECYCLE-CONSISTENT RISK COMPARISON V8.2")
    print("=" * 118)
    print("Canonical events :", len(events))
    print("Development      :", sum(r["sample"] == "DEVELOPMENT_LATEST60" for r in events))
    print("Older            :", sum(r["sample"] == "OLDER_120" for r in events))
    print("Latest60 parity  :", parity)
    print("Duplicate conflicts:", dup_conflicts)

    if not parity:
        raise SystemExit("ABORT: canonical latest60 parity failed.")

    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    atr_available_keys = set()

    for ev in events:
        daybars = underlying.get(ev["session_date"], {})
        atr = causal_atr_1m(daybars, ev["entry_timestamp"])

        event_key = (
            ev["session_date"],
            ev["direction"],
            ev["entry_timestamp"],
        )
        if atr is not None:
            atr_available_keys.add(event_key)

        # 1. Fixed 15 + lifecycle
        rows.append(
            make_row(
                ev, daybars, atr,
                "FIXED_15_LIFECYCLE",
                True,
                FIXED_STOP,
                risk_then_structural(ev, daybars, FIXED_STOP),
            )
        )

        # 2. ATR1.0 + lifecycle
        if atr is None:
            atr_result = (None, None, "INELIGIBLE_NO_ATR")
        else:
            atr_result = risk_then_structural(ev, daybars, atr)

        rows.append(
            make_row(
                ev, daybars, atr,
                "ATR_1.00_LIFECYCLE",
                atr is not None,
                atr,
                atr_result,
            )
        )

        # 3. Structural only
        rows.append(
            make_row(
                ev, daybars, atr,
                "STRUCTURAL",
                True,
                None,
                structural_result(ev, daybars),
            )
        )

        # 4. Hybrid fixed15 -> BE after +20
        rows.append(
            make_row(
                ev, daybars, atr,
                "HYBRID_FIXED15_BE20",
                True,
                FIXED_STOP,
                hybrid_result(ev, daybars, FIXED_STOP),
            )
        )

        # 5. Hybrid min(15, ATR1.0) -> BE after +20
        hybrid_risk = min(FIXED_STOP, atr) if atr is not None else None
        if hybrid_risk is None:
            h2_result = (None, None, "INELIGIBLE_NO_ATR")
        else:
            h2_result = hybrid_result(ev, daybars, hybrid_risk)

        rows.append(
            make_row(
                ev, daybars, atr,
                "HYBRID_MIN15_ATR1_BE20",
                atr is not None,
                hybrid_risk,
                h2_result,
            )
        )

    # Common ATR-eligible marker.
    for r in rows:
        key = (r["session_date"], r["direction"], r["entry_timestamp"])
        r["common_atr_eligible"] = key in atr_available_keys

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
        "FIXED_15_LIFECYCLE",
        "ATR_1.00_LIFECYCLE",
        "STRUCTURAL",
        "HYBRID_FIXED15_BE20",
        "HYBRID_MIN15_ATR1_BE20",
    ]

    lines = [
        "B FAMILY — LIFECYCLE-CONSISTENT RISK COMPARISON V8.2",
        "=" * 118,
        "Canonical detector parity: PASS",
        f"Canonical events: {len(events)}",
        f"ATR-eligible common events: {len(atr_available_keys)}",
        "",
    ]

    for model in models:
        mr = [r for r in rows if r["model"] == model]
        lines.append(f"MODEL: {model}")
        lines.append("=" * 118)

        groups = [
            ("FULL_UNIVERSE", lambda r: True),
            ("DEVELOPMENT", lambda r: r["sample"] == "DEVELOPMENT_LATEST60"),
            ("OLDER", lambda r: r["sample"] == "OLDER_120"),
            ("BULLISH", lambda r: r["direction"] == "BULLISH"),
            ("BEARISH", lambda r: r["direction"] == "BEARISH"),
            (
                "COMMON_ATR_ELIGIBLE",
                lambda r: r["common_atr_eligible"],
            ),
            (
                "COMMON_ATR_ELIGIBLE_DEVELOPMENT",
                lambda r: r["common_atr_eligible"]
                and r["sample"] == "DEVELOPMENT_LATEST60",
            ),
            (
                "COMMON_ATR_ELIGIBLE_OLDER",
                lambda r: r["common_atr_eligible"]
                and r["sample"] == "OLDER_120",
            ),
        ]

        for label, selector in groups:
            g = [r for r in mr if selector(r)]
            lines.extend(summarize(label, g))
            lines.append("")

    lines.append("EVENT DETAIL")
    lines.append("=" * 118)
    for r in rows:
        lines.append(
            f"{r['model']} {r['sample']} {r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp'][11:16]} "
            f"ATR={r['atr_1m']} risk={r['risk_points']} "
            f"invalid={(r['structural_invalidation_timestamp'][11:16] if r['structural_invalidation_timestamp'] else '-')} "
            f"exit={(r['exit_timestamp'][11:16] if r['exit_timestamp'] else '-')} "
            f"reason={r['exit_reason']} points={r['points']} "
            f"MFE={r['source_mfe']} MAE={r['source_mae']}"
        )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- No model can earn points after canonical B structural invalidation.")
    lines.append("- ATR1.0 uses causal 1m Wilder ATR(14) strictly before entry.")
    lines.append("- ATR-unavailable events are explicitly ineligible, not silently replaced.")
    lines.append("- COMMON_ATR_ELIGIBLE compares all models on the identical event subset.")
    lines.append("- Hybrid proof is +20; after proof, entry becomes a breakeven floor.")
    lines.append("- Same-candle stop/proof or proof/BE order uncertainty is marked ambiguous.")
    lines.append("- Underlying NIFTY points are not CE/PE option-premium P&L.")
    lines.append("- V8.2 compares models; it does not freeze a production risk rule.")

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print()
    print(summary)
    print()
    print("EVENT CSV:", EVENT_CSV)
    print("SUMMARY  :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
