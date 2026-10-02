#!/usr/bin/env python3
"""
B FAMILY — FIVE-DAY VALIDATION V2

Adds:
- entry time
- best favorable point level
- timestamp when MFE / best favorable level was achieved, if present in source CSV
- structural invalidation time
- points at structural invalidation

Research only. Underlying NIFTY points, not option-premium P&L.
"""

import csv
import glob
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path("data/historical-evidence")
EVENTS = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1-1"
    / "setup-family-events-v1-1.csv"
)
UNDERLYING_GLOB = str(ROOT / "underlying-ohlc-*.csv")

DAYS = [
    "2026-06-17",
    "2026-06-22",
    "2026-06-30",
    "2026-07-13",
    "2026-07-14",
]

HORIZONS = (1, 3, 5, 10, 15)

def num(v):
    try:
        return float(v)
    except Exception:
        return None

def first(r, *keys):
    for k in keys:
        if r.get(k) not in (None, ""):
            return r[k]
    return ""

def dmove(direction, entry, later):
    if entry is None or later is None:
        return None
    return later - entry if direction == "BULLISH" else entry - later

def load_underlying():
    out = {}
    for p in sorted(glob.glob(UNDERLYING_GLOB)):
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                s, t = r.get("session_date"), r.get("timestamp")
                if not s or not t:
                    continue
                vals = {}
                for k in ("open", "high", "low", "close"):
                    vals[k] = num(r.get(k))
                if vals["close"] is None:
                    continue
                out.setdefault(s, {})[t] = vals
    return out

def find_mfe_time(direction, entry_ts, entry, bars, stop_ts=None):
    """
    Reconstruct first timestamp where maximum favorable excursion occurred,
    using exact underlying 1m highs/lows after the entry candle.
    Stops before structural invalidation candle when stop_ts exists, matching
    the causal MFE convention used by the research.
    """
    if not entry_ts or entry is None:
        return None, None, None

    candidates = []
    for ts, bar in sorted(bars.items()):
        if ts <= entry_ts:
            continue
        if stop_ts and ts >= stop_ts:
            continue
        if ts[11:16] > "15:14":
            continue
        candidates.append((ts, bar))

    if not candidates:
        return None, None, None

    if direction == "BULLISH":
        ts, bar = max(candidates, key=lambda x: x[1]["high"] if x[1]["high"] is not None else float("-inf"))
        level = bar["high"]
        pts = None if level is None else level - entry
    else:
        ts, bar = min(candidates, key=lambda x: x[1]["low"] if x[1]["low"] is not None else float("inf"))
        level = bar["low"]
        pts = None if level is None else entry - level

    return ts, level, pts

rows = list(csv.DictReader(open(EVENTS, newline="")))
underlying = load_underlying()
b_rows = [r for r in rows if r.get("family") == "B_DELAYED_FULL_CANDIDATE_A"]

print("B FAMILY — FIVE-DAY VALIDATION V2")
print("=" * 132)
print("Underlying NIFTY points only. 'Best exit time' = timestamp of maximum favorable excursion, not a frozen exit rule.")
print()

for day in DAYS:
    rs = sorted(
        [r for r in b_rows if r.get("session_date") == day],
        key=lambda x: x.get("entry_timestamp", ""),
    )

    print("=" * 132)
    print(f"{day} | TOTAL B EVENTS = {len(rs)}")
    print("=" * 132)

    bars = underlying.get(day, {})

    for i, r in enumerate(rs, 1):
        direction = r.get("direction")
        entry_ts = r.get("entry_timestamp")
        entry = num(r.get("entry_close"))
        fv = num(first(r, "entry_fut_vwap", "fut_vwap", "entry_futures_vwap_diff"))
        mfe = num(r.get("mfe"))
        mae = num(r.get("mae"))
        inv = first(
            r,
            "structural_invalidation_timestamp",
            "invalidation_timestamp",
            "invalidation",
        )

        # Prefer an existing MFE timestamp from source, otherwise reconstruct from 1m bars.
        source_mfe_ts = first(
            r,
            "mfe_timestamp",
            "best_favorable_timestamp",
            "maximum_favorable_timestamp",
        )

        best_ts = source_mfe_ts or None
        best_level = None
        reconstructed_mfe = None

        if best_ts and best_ts in bars:
            if direction == "BULLISH":
                best_level = bars[best_ts]["high"]
                reconstructed_mfe = None if best_level is None else best_level - entry
            else:
                best_level = bars[best_ts]["low"]
                reconstructed_mfe = None if best_level is None else entry - best_level
        else:
            best_ts, best_level, reconstructed_mfe = find_mfe_time(
                direction, entry_ts, entry, bars, inv or None
            )

        print(f"B{i} {direction}")
        print(f"  entry time                    = {entry_ts}")
        print(f"  entry NIFTY                   = {entry}")
        print(f"  FUT-VWAP                      = {fv}")

        for h in HORIZONS:
            val = None
            for k in (f"move_{h}m", f"directional_move_{h}m", f"move_{h}m_directional"):
                if r.get(k) not in (None, ""):
                    val = num(r[k])
                    break
            if val is None and entry_ts and entry is not None:
                target = (datetime.fromisoformat(entry_ts) + timedelta(minutes=h)).isoformat()
                if target in bars:
                    val = dmove(direction, entry, bars[target]["close"])
            print(f"  +{h:>2}m directional points    = {val}")

        print(f"  MFE points                    = {mfe}")
        print(f"  MFE/best exit time            = {best_ts or 'NOT AVAILABLE'}")
        print(f"  best favorable NIFTY level    = {best_level}")
        if reconstructed_mfe is not None:
            print(f"  reconstructed favorable pts   = {reconstructed_mfe:+.2f}")

        print(f"  MAE points                    = {mae}")
        print(f"  structural invalidation time  = {inv or 'NONE'}")

        if inv and inv in bars and entry is not None:
            inv_close = bars[inv]["close"]
            inv_pts = dmove(direction, entry, inv_close)
            print(f"  invalidation close            = {inv_close}")
            print(f"  entry->invalidation points    = {inv_pts:+.2f}")
        else:
            print("  entry->invalidation points    = unavailable/no invalidation")

        print()

print("NOTE")
print("- MFE/best exit time is hindsight descriptive evidence only.")
print("- It is NOT a recommended live exit.")
print("- Structural invalidation is the current causal lifecycle boundary.")
