#!/usr/bin/env python3
"""
MIDPOINT + VWAP SETUP-FAMILY VALIDATION — LATEST 60 SESSIONS — V1.1

Research only. No production strategy/runtime changes.

Families measured:
B) DELAYED_FULL_CANDIDATE_A
C) FAILED_MIDPOINT_RECLAIM_REBREAK
D) FULL_RANGE_OPPOSITE_RECOVERY_REBREAK

Study universe:
- latest 60 distinct sessions present in the opening-candle midpoint framework
- 15:15 onward excluded from all event discovery and outcome measurement
- chronological blocks: first 20 / middle 20 / last 20

Important:
- Original Candidate A is NOT changed.
- No threshold optimization is performed.
- Setup-family definitions are fixed in this script.
- MFE/MAE starts on the minute AFTER the completed entry candle.
- MFE/MAE stops BEFORE the first structural midpoint invalidation candle.
"""

from __future__ import annotations

import csv
import glob
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")

FRAMEWORK_FILES = [
    ROOT / "opening-candle-midpoint-framework-v1-1-development.json",
    ROOT / "opening-candle-midpoint-framework-v1-1-oos-efg.json",
    ROOT / "opening-candle-midpoint-framework-v1-1-oos-h.json",
]

FUTURES_CSV = ROOT / "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
UNDERLYING_GLOB = str(ROOT / "underlying-ohlc-*.csv")

OUTDIR = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1-1"
)

EVENTS_CSV = OUTDIR / "setup-family-events-v1-1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1-1.txt"
SESSION_CSV = OUTDIR / "session-summary-v1-1.csv"

TRUSTED_END = "15:14"
VWAP_THRESHOLD = 5.0
DELAY_MAX_MINUTES = 10
HORIZONS = (1, 3, 5, 10, 15)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def parse_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def hhmm(ts: str) -> str:
    return ts[11:16]


def minute_key(dt: datetime) -> str:
    return dt.isoformat()


def add_minutes(ts: str, n: int) -> str:
    return minute_key(parse_dt(ts) + timedelta(minutes=n))


def is_trusted(ts: str) -> bool:
    return hhmm(ts) <= TRUSTED_END


def fnum(v):
    if v in (None, ""):
        return None
    return float(v)


def describe(values):
    xs = [float(x) for x in values if x is not None]
    if not xs:
        return "n=0"
    xs.sort()
    def q(p):
        return xs[round((len(xs) - 1) * p)]
    return (
        f"n={len(xs)} mean={mean(xs):+.2f} median={median(xs):+.2f} "
        f"p25={q(.25):+.2f} p75={q(.75):+.2f} "
        f"min={xs[0]:+.2f} max={xs[-1]:+.2f}"
    )


# ---------------------------------------------------------------------------
# Framework loading
# ---------------------------------------------------------------------------

def walk_framework(obj):
    if isinstance(obj, dict):
        if obj.get("session_date") and obj.get("setup_type") in {
            "RED_BREAK", "GREEN_BREAK"
        }:
            yield obj
        for v in obj.values():
            yield from walk_framework(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_framework(v)


def event_key(e):
    return (
        e.get("session_date"),
        e.get("setup_type"),
        e.get("reference_start"),
        e.get("reference_end"),
        e.get("reference_high"),
        e.get("reference_low"),
        e.get("reference_midpoint"),
        e.get("midpoint_break_timestamp"),
        e.get("boundary_break_timestamp"),
    )


def load_framework():
    events = []
    seen = set()
    files_used = []

    for p in FRAMEWORK_FILES:
        if not p.exists():
            continue
        files_used.append(p)
        with p.open() as f:
            obj = json.load(f)
        for e in walk_framework(obj):
            k = event_key(e)
            if k in seen:
                continue
            seen.add(k)
            events.append(e)

    if not events:
        raise FileNotFoundError(
            "No opening-candle midpoint framework events found."
        )

    events.sort(
        key=lambda e: (
            e.get("session_date") or "",
            e.get("boundary_break_timestamp")
            or e.get("midpoint_break_timestamp")
            or "",
            e.get("setup_type") or "",
        )
    )

    return files_used, events


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def load_underlying():
    files = sorted(glob.glob(UNDERLYING_GLOB))
    if not files:
        raise FileNotFoundError(UNDERLYING_GLOB)

    by_session = defaultdict(dict)
    duplicate_conflicts = 0

    for p in files:
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                session = row.get("session_date")
                ts = row.get("timestamp")
                if not session or not ts or not is_trusted(ts):
                    continue

                rec = {
                    "open": fnum(row.get("open")),
                    "high": fnum(row.get("high")),
                    "low": fnum(row.get("low")),
                    "close": fnum(row.get("close")),
                }
                if None in rec.values():
                    continue

                old = by_session[session].get(ts)
                if old is not None and old != rec:
                    duplicate_conflicts += 1
                    continue
                by_session[session][ts] = rec

    return files, by_session, duplicate_conflicts


def load_futures():
    if not FUTURES_CSV.exists():
        raise FileNotFoundError(FUTURES_CSV)

    by_session = defaultdict(dict)

    with FUTURES_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            session = row.get("session_date")
            ts = row.get("timestamp")
            if not session or not ts or not is_trusted(ts):
                continue

            close = fnum(row.get("close"))
            vwap = fnum(row.get("session_vwap") or row.get("vwap"))
            if close is None or vwap is None:
                continue

            by_session[session][ts] = {
                "close": close,
                "vwap": vwap,
                "diff": close - vwap,
            }

    return by_session


# ---------------------------------------------------------------------------
# Common structure
# ---------------------------------------------------------------------------

def direction_for(e):
    return "BEARISH" if e["setup_type"] == "RED_BREAK" else "BULLISH"


def setup_levels(e):
    return {
        "high": float(e["reference_high"]),
        "mid": float(e["reference_midpoint"]),
        "low": float(e["reference_low"]),
    }


def candidate_a(direction, at_ts, fut):
    cur = fut.get(at_ts)
    if not cur:
        return None

    dt = parse_dt(at_ts)
    vals = []
    for i in range(5, -1, -1):
        row = fut.get(minute_key(dt - timedelta(minutes=i)))
        if row:
            vals.append(row["diff"])

    if not vals:
        return None

    d = cur["diff"]

    if direction == "BEARISH":
        return d < -VWAP_THRESHOLD and any(x >= -VWAP_THRESHOLD for x in vals)

    return d > VWAP_THRESHOLD and any(x <= VWAP_THRESHOLD for x in vals)


def structurally_valid(direction, close, midpoint):
    if direction == "BEARISH":
        return close <= midpoint
    return close >= midpoint


def beyond_boundary(direction, close, levels):
    if direction == "BEARISH":
        return close < levels["low"]
    return close > levels["high"]


def adverse_midpoint_close(direction, close, midpoint):
    if direction == "BEARISH":
        return close > midpoint
    return close < midpoint


def directional_move(direction, entry, later):
    return later - entry if direction == "BULLISH" else entry - later


# ---------------------------------------------------------------------------
# Family B — delayed full Candidate A
# ---------------------------------------------------------------------------

def family_b_for_event(e, u, fut):
    t0 = e.get("boundary_break_timestamp")
    if not t0 or not is_trusted(t0):
        return None

    direction = direction_for(e)
    levels = setup_levels(e)

    a0 = candidate_a(direction, t0, fut)
    if a0 is not False:
        return None

    dt0 = parse_dt(t0)

    for m in range(1, DELAY_MAX_MINUTES + 1):
        ts = minute_key(dt0 + timedelta(minutes=m))
        if not is_trusted(ts):
            break

        bar = u.get(ts)
        if not bar:
            break

        if not structurally_valid(direction, bar["close"], levels["mid"]):
            return None

        if not beyond_boundary(direction, bar["close"], levels):
            continue

        if candidate_a(direction, ts, fut) is True:
            return {
                "family": "B_DELAYED_FULL_CANDIDATE_A",
                "session_date": e["session_date"],
                "direction": direction,
                "entry_timestamp": ts,
                "origin_timestamp": t0,
                "delay_minutes": m,
                "reference_high": levels["high"],
                "reference_midpoint": levels["mid"],
                "reference_low": levels["low"],
                "entry_fut_vwap": fut.get(ts, {}).get("diff"),
                "source_setup_type": e["setup_type"],
            }

    return None


# ---------------------------------------------------------------------------
# Family C — failed midpoint reclaim + fresh boundary rebreak
#
# Frozen definition:
# - starts from an original structural boundary break
# - later price touches the setup midpoint
# - price CLOSES across midpoint against original direction (temporary reclaim)
# - later CLOSES back on original side (failed reclaim)
# - price has returned inside the original boundary
# - later makes a fresh CLOSE through the original boundary
#
# TOUCH_REJECTION without an actual temporary reclaim is deliberately excluded.
# ---------------------------------------------------------------------------

def crossed_against(direction, close, midpoint):
    if direction == "BEARISH":
        return close > midpoint
    return close < midpoint


def returned_original_side(direction, close, midpoint):
    if direction == "BEARISH":
        return close < midpoint
    return close > midpoint


def returned_inside_boundary(direction, close, levels):
    if direction == "BEARISH":
        return close >= levels["low"]
    return close <= levels["high"]


def fresh_break(direction, close, levels):
    if direction == "BEARISH":
        return close < levels["low"]
    return close > levels["high"]


def midpoint_touched(bar, midpoint):
    return bar["low"] <= midpoint <= bar["high"]


def opposite_structure_termination(direction, close, opposite_levels):
    # Structural lifecycle termination added in V1.1.
    #
    # GREEN-origin / bullish C dies if price closes below the RED low.
    # RED-origin / bearish C dies if price closes above the GREEN high.
    #
    # This is deliberately structural and symmetric: no elapsed-time limit,
    # no VWAP threshold, and no MFE/MAE tuning.
    if not opposite_levels:
        return False

    if direction == "BULLISH":
        return close < opposite_levels["low"]

    return close > opposite_levels["high"]


def family_c_for_event(e, opposite_e, u, fut):
    t0 = e.get("boundary_break_timestamp")
    if not t0 or not is_trusted(t0):
        return None

    direction = direction_for(e)
    levels = setup_levels(e)
    opposite_levels = setup_levels(opposite_e) if opposite_e else None

    retest = None
    reclaim = None
    failed = None
    reset = None

    for ts in sorted(u):
        if ts <= t0 or not is_trusted(ts):
            continue

        bar = u[ts]
        close = bar["close"]

        # V1.1 lifecycle guard:
        # once the opposite opening structure is decisively broken, this
        # same-direction continuation lifecycle is dead. A later full-range
        # recovery belongs to Family D rather than a stale Family C chain.
        if opposite_structure_termination(direction, close, opposite_levels):
            return None

        if retest is None:
            if midpoint_touched(bar, levels["mid"]):
                retest = ts
                if crossed_against(direction, close, levels["mid"]):
                    reclaim = ts
            continue

        if reclaim is None:
            if crossed_against(direction, close, levels["mid"]):
                reclaim = ts
            continue

        if failed is None:
            if returned_original_side(direction, close, levels["mid"]):
                failed = ts

        if reset is None and returned_inside_boundary(direction, close, levels):
            reset = ts

        if (
            failed is not None
            and reset is not None
            and ts > max(failed, reset)
            and fresh_break(direction, close, levels)
        ):
            return {
                "family": "C_FAILED_MIDPOINT_RECLAIM_REBREAK",
                "session_date": e["session_date"],
                "direction": direction,
                "entry_timestamp": ts,
                "origin_timestamp": t0,
                "retest_timestamp": retest,
                "temporary_reclaim_timestamp": reclaim,
                "failed_reclaim_timestamp": failed,
                "boundary_reset_timestamp": reset,
                "reference_high": levels["high"],
                "reference_midpoint": levels["mid"],
                "reference_low": levels["low"],
                "entry_fut_vwap": fut.get(ts, {}).get("diff"),
                "source_setup_type": e["setup_type"],
            }

    return None


# ---------------------------------------------------------------------------
# Family D — full-range opposite-direction recovery/rebreak
#
# Frozen 25-Aug-derived structural definition, with no numeric tuning:
#
# BULLISH D:
#   - the session has both RED and GREEN opening structures
#   - after RED boundary break, price has closed below GREEN low
#   - later price closes back above GREEN low
#   - later closes above GREEN midpoint
#   - later closes above BOTH GREEN high and RED high
#   - entry = that first full-range close
#
# BEARISH D is the exact mirror:
#   - after GREEN boundary break, price has closed above RED high
#   - later closes below RED high
#   - later closes below RED midpoint
#   - later closes below BOTH RED low and GREEN low
#
# A midpoint pullback is recorded as a feature but is NOT required; requiring it
# would overfit the single 25-Aug example.
# ---------------------------------------------------------------------------

def family_d_for_session(session, red, green, u, fut):
    out = []

    if not red or not green:
        return out

    red_levels = setup_levels(red)
    green_levels = setup_levels(green)

    red_t0 = red.get("boundary_break_timestamp")
    green_t0 = green.get("boundary_break_timestamp")

    # D-BULL after bearish RED break.
    if red_t0 and is_trusted(red_t0):
        seen_below_green_low = False
        recovered_green_low = None
        recovered_green_mid = None
        pullback_below_mid = None

        for ts in sorted(u):
            if ts <= red_t0 or not is_trusted(ts):
                continue
            c = u[ts]["close"]

            if c < green_levels["low"]:
                seen_below_green_low = True

            if seen_below_green_low and recovered_green_low is None and c > green_levels["low"]:
                recovered_green_low = ts

            if recovered_green_low and recovered_green_mid is None and c > green_levels["mid"]:
                recovered_green_mid = ts
                continue

            if recovered_green_mid and pullback_below_mid is None and c < green_levels["mid"]:
                pullback_below_mid = ts

            if (
                recovered_green_mid
                and c > green_levels["high"]
                and c > red_levels["high"]
            ):
                out.append({
                    "family": "D_FULL_RANGE_OPPOSITE_RECOVERY_REBREAK",
                    "session_date": session,
                    "direction": "BULLISH",
                    "entry_timestamp": ts,
                    "origin_timestamp": red_t0,
                    "recovered_opposite_low_timestamp": recovered_green_low,
                    "recovered_opposite_mid_timestamp": recovered_green_mid,
                    "midpoint_pullback_timestamp": pullback_below_mid,
                    "reference_high": green_levels["high"],
                    "reference_midpoint": green_levels["mid"],
                    "reference_low": green_levels["low"],
                    "other_range_high": red_levels["high"],
                    "other_range_midpoint": red_levels["mid"],
                    "other_range_low": red_levels["low"],
                    "entry_fut_vwap": fut.get(ts, {}).get("diff"),
                    "source_setup_type": "RED_TO_GREEN_FULL_RANGE",
                })
                break

    # D-BEAR after bullish GREEN break.
    if green_t0 and is_trusted(green_t0):
        seen_above_red_high = False
        recovered_red_high_down = None
        recovered_red_mid_down = None
        pullback_above_mid = None

        for ts in sorted(u):
            if ts <= green_t0 or not is_trusted(ts):
                continue
            c = u[ts]["close"]

            if c > red_levels["high"]:
                seen_above_red_high = True

            if seen_above_red_high and recovered_red_high_down is None and c < red_levels["high"]:
                recovered_red_high_down = ts

            if recovered_red_high_down and recovered_red_mid_down is None and c < red_levels["mid"]:
                recovered_red_mid_down = ts
                continue

            if recovered_red_mid_down and pullback_above_mid is None and c > red_levels["mid"]:
                pullback_above_mid = ts

            if (
                recovered_red_mid_down
                and c < red_levels["low"]
                and c < green_levels["low"]
            ):
                out.append({
                    "family": "D_FULL_RANGE_OPPOSITE_RECOVERY_REBREAK",
                    "session_date": session,
                    "direction": "BEARISH",
                    "entry_timestamp": ts,
                    "origin_timestamp": green_t0,
                    "recovered_opposite_high_timestamp": recovered_red_high_down,
                    "recovered_opposite_mid_timestamp": recovered_red_mid_down,
                    "midpoint_pullback_timestamp": pullback_above_mid,
                    "reference_high": red_levels["high"],
                    "reference_midpoint": red_levels["mid"],
                    "reference_low": red_levels["low"],
                    "other_range_high": green_levels["high"],
                    "other_range_midpoint": green_levels["mid"],
                    "other_range_low": green_levels["low"],
                    "entry_fut_vwap": fut.get(ts, {}).get("diff"),
                    "source_setup_type": "GREEN_TO_RED_FULL_RANGE",
                })
                break

    return out


# ---------------------------------------------------------------------------
# Outcome measurement
# ---------------------------------------------------------------------------

def first_midpoint_invalidation(ev, u):
    entry = ev["entry_timestamp"]
    direction = ev["direction"]
    midpoint = float(ev["reference_midpoint"])

    for ts in sorted(u):
        if ts <= entry or not is_trusted(ts):
            continue
        c = u[ts]["close"]
        if direction == "BEARISH" and c > midpoint:
            return ts
        if direction == "BULLISH" and c < midpoint:
            return ts

    return None


def measure_event(ev, u):
    entry_ts = ev["entry_timestamp"]
    if entry_ts not in u:
        ev["measurement_status"] = "MISSING_ENTRY_UNDERLYING"
        return ev

    entry_close = u[entry_ts]["close"]
    invalidation = first_midpoint_invalidation(ev, u)
    start_ts = add_minutes(entry_ts, 1)

    ev["entry_close"] = entry_close
    ev["post_entry_start"] = start_ts
    ev["structural_invalidation_timestamp"] = invalidation
    ev["measurement_end_reason"] = (
        "MIDPOINT_INVALIDATION" if invalidation else "TRUSTED_CUTOFF_1514"
    )

    # Fixed-horizon close-to-close moves.
    for h in HORIZONS:
        ts = add_minutes(entry_ts, h)
        if (
            ts in u
            and is_trusted(ts)
            and (invalidation is None or ts < invalidation)
        ):
            ev[f"move_{h}m"] = directional_move(
                ev["direction"], entry_close, u[ts]["close"]
            )
        else:
            ev[f"move_{h}m"] = None

    # Causal MFE/MAE after signal candle, before invalidation.
    window = []
    for ts, bar in sorted(u.items()):
        if ts < start_ts:
            continue
        if invalidation is not None and ts >= invalidation:
            break
        if not is_trusted(ts):
            break
        window.append((ts, bar))

    if not window:
        ev["mfe"] = None
        ev["mae"] = None
        ev["mfe_timestamp"] = None
        ev["mae_timestamp"] = None
        ev["measurement_status"] = "NO_POST_ENTRY_WINDOW"
        return ev

    if ev["direction"] == "BULLISH":
        bt, bb = max(window, key=lambda x: x[1]["high"])
        wt, wb = min(window, key=lambda x: x[1]["low"])
        ev["mfe"] = bb["high"] - entry_close
        ev["mae"] = wb["low"] - entry_close
    else:
        bt, bb = min(window, key=lambda x: x[1]["low"])
        wt, wb = max(window, key=lambda x: x[1]["high"])
        ev["mfe"] = entry_close - bb["low"]
        ev["mae"] = entry_close - wb["high"]

    ev["mfe_timestamp"] = bt
    ev["mae_timestamp"] = wt
    ev["measurement_status"] = "OK"
    return ev


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

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


def block_name(session, sessions):
    i = sessions.index(session)
    if i < 20:
        return "BLOCK_1_FIRST20"
    if i < 40:
        return "BLOCK_2_MIDDLE20"
    return "BLOCK_3_LAST20"


def family_summary(rows, title):
    lines = []
    lines.append(title)
    lines.append("-" * 110)

    for direction in ("BEARISH", "BULLISH", "COMBINED"):
        subset = (
            rows if direction == "COMBINED"
            else [r for r in rows if r["direction"] == direction]
        )
        ok = [r for r in subset if r.get("measurement_status") == "OK"]

        lines.append(
            f"{direction:<9} events={len(subset):3d} measured={len(ok):3d} "
            f"MFE[{describe(r.get('mfe') for r in ok)}] "
            f"MAE[{describe(r.get('mae') for r in ok)}]"
        )

        for h in HORIZONS:
            vals = [r.get(f"move_{h}m") for r in ok if r.get(f"move_{h}m") is not None]
            lines.append(f"  +{h:2d}m directional move: {describe(vals)}")

    return lines


def main():
    framework_files, all_framework = load_framework()
    underlying_files, underlying, dup_conflicts = load_underlying()
    futures = load_futures()

    all_sessions = sorted({e["session_date"] for e in all_framework})
    sessions = all_sessions[-60:]

    framework = [e for e in all_framework if e["session_date"] in sessions]

    by_session = defaultdict(list)
    for e in framework:
        by_session[e["session_date"]].append(e)

    events = []

    # Families B and C are event-based.
    for e in framework:
        session = e["session_date"]
        u = underlying.get(session, {})
        fut = futures.get(session, {})
        if not u:
            continue

        b = family_b_for_event(e, u, fut)
        if b:
            events.append(b)

        session_events = by_session.get(session, [])
        if e["setup_type"] == "RED_BREAK":
            opposite_e = next(
                (x for x in session_events if x["setup_type"] == "GREEN_BREAK"),
                None,
            )
        else:
            opposite_e = next(
                (x for x in session_events if x["setup_type"] == "RED_BREAK"),
                None,
            )

        c = family_c_for_event(e, opposite_e, u, fut)
        if c:
            events.append(c)

    # Family D is session-pair based.
    for session in sessions:
        evs = by_session.get(session, [])
        red = next((e for e in evs if e["setup_type"] == "RED_BREAK"), None)
        green = next((e for e in evs if e["setup_type"] == "GREEN_BREAK"), None)
        if not red or not green:
            continue
        events.extend(
            family_d_for_session(
                session,
                red,
                green,
                underlying.get(session, {}),
                futures.get(session, {}),
            )
        )

    # De-duplicate exact family/session/direction/entry tuples.
    dedup = {}
    for ev in events:
        k = (
            ev["family"],
            ev["session_date"],
            ev["direction"],
            ev["entry_timestamp"],
        )
        dedup[k] = ev
    events = list(dedup.values())

    # Measure.
    measured = []
    for ev in events:
        ev = measure_event(ev, underlying.get(ev["session_date"], {}))
        ev["block"] = block_name(ev["session_date"], sessions)
        measured.append(ev)

    measured.sort(
        key=lambda r: (
            r["session_date"],
            r["entry_timestamp"],
            r["family"],
            r["direction"],
        )
    )

    write_csv(EVENTS_CSV, measured)

    # Session summary.
    session_rows = []
    for s in sessions:
        sr = {"session_date": s, "block": block_name(s, sessions)}
        for family in (
            "B_DELAYED_FULL_CANDIDATE_A",
            "C_FAILED_MIDPOINT_RECLAIM_REBREAK",
            "D_FULL_RANGE_OPPOSITE_RECOVERY_REBREAK",
        ):
            sub = [r for r in measured if r["session_date"] == s and r["family"] == family]
            sr[f"{family}_count"] = len(sub)
        session_rows.append(sr)
    write_csv(SESSION_CSV, session_rows)

    lines = []
    lines.append("MIDPOINT + VWAP SETUP-FAMILY VALIDATION — LATEST 60 SESSIONS — V1.1")
    lines.append("=" * 110)
    lines.append("Research only. No runtime/execution/Candidate-A changes.")
    lines.append("15:15 onward excluded.")
    lines.append("No threshold search.")
    lines.append(
        "V1.1 taxonomy change: Family C terminates when the opposite "
        "opening structure is decisively broken before the C rebreak."
    )
    lines.append("")
    lines.append(f"framework files used         = {len(framework_files)}")
    for p in framework_files:
        lines.append(f"  {p}")
    lines.append(f"all framework sessions       = {len(all_sessions)}")
    lines.append(f"selected latest sessions     = {len(sessions)}")
    lines.append(f"first selected session       = {sessions[0]}")
    lines.append(f"last selected session        = {sessions[-1]}")
    lines.append(f"25 Aug included              = {'2026-08-25' in sessions}")
    lines.append(f"framework events selected    = {len(framework)}")
    lines.append(f"underlying source files      = {len(underlying_files)}")
    lines.append(f"underlying duplicate conflicts = {dup_conflicts}")
    lines.append(f"total detected family events = {len(measured)}")
    lines.append("")

    for family, title in (
        ("B_DELAYED_FULL_CANDIDATE_A", "FAMILY B — DELAYED FULL CANDIDATE A"),
        ("C_FAILED_MIDPOINT_RECLAIM_REBREAK", "FAMILY C — FAILED MIDPOINT RECLAIM + REBREAK"),
        ("D_FULL_RANGE_OPPOSITE_RECOVERY_REBREAK", "FAMILY D — FULL-RANGE OPPOSITE RECOVERY / REBREAK"),
    ):
        rows = [r for r in measured if r["family"] == family]
        lines.extend(family_summary(rows, title))
        lines.append("")

        lines.append("CHRONOLOGICAL BLOCK COUNTS")
        for block in ("BLOCK_1_FIRST20", "BLOCK_2_MIDDLE20", "BLOCK_3_LAST20"):
            b = [r for r in rows if r["block"] == block]
            bear = sum(r["direction"] == "BEARISH" for r in b)
            bull = sum(r["direction"] == "BULLISH" for r in b)
            lines.append(
                f"  {block:<20} events={len(b):3d} bear={bear:3d} bull={bull:3d}"
            )
        lines.append("")

    # 25 Aug audit.
    lines.append("25 AUG 2026 — DETECTED EVENTS")
    lines.append("-" * 110)
    aug25 = [r for r in measured if r["session_date"] == "2026-08-25"]
    if not aug25:
        lines.append("NO EVENTS DETECTED")
    else:
        for r in aug25:
            lines.append(
                f"{r['entry_timestamp']} {r['direction']:<7} "
                f"{r['family']} "
                f"entry={r.get('entry_close')} "
                f"fut_vwap={r.get('entry_fut_vwap')} "
                f"MFE={r.get('mfe')} MAE={r.get('mae')} "
                f"invalidation={r.get('structural_invalidation_timestamp')}"
            )

    lines.append("")
    lines.append("EXPECTED 25 AUG REFERENCE")
    lines.append("  Family B bearish near 09:42")
    lines.append("  Family C bearish near 12:00")
    lines.append("  Family D bullish near 14:31")
    lines.append("  15:15 onward excluded")
    lines.append("")
    lines.append("INTERPRETATION GUARD")
    lines.append(
        "This run measures occurrence and descriptive behavior after the single V1.1 structural lifecycle correction. "
        "Do not convert any block result, MFE/MAE statistic, horizon, "
        "or VWAP value into a production threshold from this run."
    )
    lines.append("")
    lines.append(f"EVENTS CSV  = {EVENTS_CSV}")
    lines.append(f"SESSION CSV = {SESSION_CSV}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
