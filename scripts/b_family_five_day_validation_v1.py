#!/usr/bin/env python3
import csv, glob
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path("data/historical-evidence")
EVENTS = ROOT/"hilega-pcr-oi-support-research-v1"/"midpoint-vwap-setup-family-60-session-validation-v1-1"/"setup-family-events-v1-1.csv"
UNDERLYING_GLOB = str(ROOT/"underlying-ohlc-*.csv")

DAYS = ["2026-06-17","2026-06-22","2026-06-30","2026-07-13","2026-07-14"]
H = (1,3,5,10,15)

def num(v):
    try: return float(v)
    except: return None

def dmove(direction, entry, later):
    if entry is None or later is None: return None
    return later-entry if direction=="BULLISH" else entry-later

def load_underlying():
    out={}
    for p in sorted(glob.glob(UNDERLYING_GLOB)):
        with open(p,newline="") as f:
            for r in csv.DictReader(f):
                s,t=r.get("session_date"),r.get("timestamp")
                c=num(r.get("close"))
                if s and t and c is not None:
                    out.setdefault(s,{})[t]=c
    return out

def first(r,*keys):
    for k in keys:
        if r.get(k) not in (None,""): return r[k]
    return ""

rows=list(csv.DictReader(open(EVENTS,newline="")))
bars=load_underlying()
b=[r for r in rows if r.get("family")=="B_DELAYED_FULL_CANDIDATE_A"]

print("B FAMILY — FIVE-DAY VALIDATION")
print("="*110)
print("Underlying NIFTY points only; not option-premium profit.")

grand=0
for day in DAYS:
    rs=sorted([r for r in b if r.get("session_date")==day], key=lambda x:x.get("entry_timestamp",""))
    grand += len(rs)
    print("\n"+"="*110)
    print(day, "TOTAL B EVENTS =", len(rs))
    print("="*110)
    for i,r in enumerate(rs,1):
        direction=r.get("direction")
        ts=r.get("entry_timestamp")
        entry=num(r.get("entry_close"))
        fv=num(first(r,"entry_fut_vwap","fut_vwap","entry_futures_vwap_diff"))
        mfe=num(r.get("mfe")); mae=num(r.get("mae"))
        inv=first(r,"structural_invalidation_timestamp","invalidation_timestamp","invalidation")

        print(f"B{i}: {direction}  entry={ts} @ {entry}  FUT-VWAP={fv}")
        for h in H:
            val=None
            for k in (f"move_{h}m",f"directional_move_{h}m",f"move_{h}m_directional"):
                if r.get(k) not in (None,""):
                    val=num(r[k]); break
            if val is None and ts and entry is not None:
                target=(datetime.fromisoformat(ts)+timedelta(minutes=h)).isoformat()
                if target in bars.get(day,{}):
                    val=dmove(direction,entry,bars[day][target])
            print(f"  +{h:>2}m points = {val}")

        print(f"  MFE = {mfe}")
        print(f"  MAE = {mae}")
        print(f"  invalidation = {inv or 'NONE'}")

        if inv and inv in bars.get(day,{}) and entry is not None:
            ic=bars[day][inv]
            pts=dmove(direction,entry,ic)
            print(f"  invalidation close = {ic}")
            print(f"  entry->invalidation points = {pts:+.2f}")
        else:
            print("  entry->invalidation points = unavailable/no invalidation")

        if mfe is not None and entry is not None:
            best=entry+mfe if direction=="BULLISH" else entry-mfe
            print(f"  best favorable NIFTY level ≈ {best:.2f}")
        if mae is not None and entry is not None:
            worst=entry+mae if direction=="BULLISH" else entry-mae
            print(f"  worst adverse NIFTY level ≈ {worst:.2f}")

print("\nTOTAL B EVENTS ACROSS FIVE DAYS =", grand)
