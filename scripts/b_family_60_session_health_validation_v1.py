#!/usr/bin/env python3
import csv, glob, json
from collections import Counter
from pathlib import Path

ROOT=Path("data/historical-evidence")
EVENTS=ROOT/"hilega-pcr-oi-support-research-v1"/"midpoint-vwap-setup-family-60-session-validation-v1-1"/"setup-family-events-v1-1.csv"
FUT=ROOT/"midpoint-v2-nifty-futures-vwap-v1-all180.csv"
FRAME=ROOT/"opening-candle-midpoint-framework-v1-1-development.json"
OUT=ROOT/"hilega-pcr-oi-support-research-v1"/"b-family-60-session-health-validation-v1"

def num(v):
    try:return float(v)
    except:return None

def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from walk(v)
    elif isinstance(x,list):
        for v in x: yield from walk(v)

def dmove(direction,entry,later):
    if entry is None or later is None:return None
    return later-entry if direction=="BULLISH" else entry-later

# underlying
under={}
for p in sorted(glob.glob(str(ROOT/"**"/"underlying-ohlc-*.csv"),recursive=True)):
    try:
        for r in csv.DictReader(open(p,newline="")):
            d,t=r.get("session_date"),r.get("timestamp"); c=num(r.get("close"))
            if d and t and c is not None:
                under.setdefault(d,{})[t]=c
    except: pass

# futures vwap
fut={}
for r in csv.DictReader(open(FUT,newline="")):
    d,t=r.get("session_date"),r.get("timestamp")
    c=num(r.get("close")); v=num(r.get("session_vwap") or r.get("vwap"))
    if d and t and c is not None and v is not None:
        fut.setdefault(d,{})[t]=c-v

# opening structures
framework={}
data=json.loads(FRAME.read_text())
for r in walk(data):
    d=r.get("session_date"); typ=r.get("setup_type")
    if not d or typ not in ("GREEN_BREAK","RED_BREAK"): continue
    direction="BULLISH" if typ=="GREEN_BREAK" else "BEARISH"
    hi=num(r.get("reference_high")); lo=num(r.get("reference_low")); mid=num(r.get("reference_midpoint"))
    bb=r.get("boundary_break_timestamp")
    if hi is None or lo is None or mid is None or not bb: continue
    framework.setdefault((d,direction),[]).append((bb,hi,lo,mid))

events=list(csv.DictReader(open(EVENTS,newline="")))
bs=[r for r in events if r.get("family")=="B_DELAYED_FULL_CANDIDATE_A"]

rows=[]
for ev in sorted(bs,key=lambda r:(r.get("session_date",""),r.get("entry_timestamp",""))):
    day=ev["session_date"]; direction=ev["direction"]; ets=ev["entry_timestamp"]; entry=num(ev.get("entry_close"))
    parents=[x for x in framework.get((day,direction),[]) if x[0] <= ets]
    if not parents:
        rows.append(dict(session_date=day,direction=direction,entry_timestamp=ets,entry_close=entry,
                         final_class="NO_PARENT_STRUCTURE"))
        continue
    bb,hi,lo,mid=sorted(parents,key=lambda x:x[0])[-1]
    boundary=hi if direction=="BULLISH" else lo
    common=sorted(t for t in set(under.get(day,{})) & set(fut.get(day,{})) if t>ets and t[11:16]<="15:14")
    warning=None; reason=None; recovery=None; invalid=None
    warn_pts=rec_pts=inv_pts=None
    for t in common:
        c=under[day][t]; diff=fut[day][t]
        bhold = c>hi if direction=="BULLISH" else c<lo
        mintact = c>=mid if direction=="BULLISH" else c<=mid
        vside = diff>0 if direction=="BULLISH" else diff<0

        if not mintact:
            invalid=t; inv_pts=dmove(direction,entry,c); break

        if warning is None and (not bhold or not vside):
            warning=t
            parts=[]
            if not bhold: parts.append("BOUNDARY_RECLAIM")
            if not vside: parts.append("VWAP_SIDE_LOST")
            reason="+".join(parts)
            warn_pts=dmove(direction,entry,c)
            continue

        if warning and recovery is None:
            rec = (c>hi and diff>0) if direction=="BULLISH" else (c<lo and diff<0)
            if rec:
                recovery=t; rec_pts=dmove(direction,entry,c)

    if invalid:
        cls="WARNING_RECOVERED_THEN_INVALIDATED" if warning and recovery else ("WARNING_THEN_INVALIDATED" if warning else "DIRECT_MIDPOINT_INVALIDATION")
    else:
        cls="WARNING_RECOVERED_NO_INVALIDATION" if warning and recovery else ("WARNING_NO_RECOVERY_NO_INVALIDATION" if warning else "HEALTHY_NO_WARNING")

    rows.append({
        "session_date":day,"direction":direction,"entry_timestamp":ets,"entry_close":entry,
        "boundary":boundary,"midpoint":mid,"boundary_break_timestamp":bb,
        "first_warning_timestamp":warning,"first_warning_reason":reason,"warning_move_points":warn_pts,
        "first_recovery_timestamp":recovery,"recovery_move_points":rec_pts,
        "midpoint_invalidation_timestamp":invalid,"invalidation_move_points":inv_pts,
        "mfe":num(ev.get("mfe")),"mae":num(ev.get("mae")),"final_class":cls
    })

OUT.mkdir(parents=True,exist_ok=True)
csv_path=OUT/"b-family-health-events-v1.csv"
fields=sorted({k for r in rows for k in r.keys()})
with open(csv_path,"w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

counts=Counter(r["final_class"] for r in rows)
summary=[
"B FAMILY — 60-SESSION HEALTH VALIDATION V1",
"="*100,
f"Total B events: {len(rows)}",
f"BULLISH: {sum(r.get('direction')=='BULLISH' for r in rows)}",
f"BEARISH: {sum(r.get('direction')=='BEARISH' for r in rows)}",
"",
"FINAL CLASS COUNTS",
]
summary += [f"{k}: {v}" for k,v in sorted(counts.items())]
summary += ["","EVENTS","-"*100]
for r in rows:
    summary.append(
        f"{r.get('session_date')} {r.get('direction')} "
        f"entry={r.get('entry_timestamp','')[11:16]} "
        f"warn={(r.get('first_warning_timestamp') or '-')[11:16] if r.get('first_warning_timestamp') else '-'} "
        f"reason={r.get('first_warning_reason') or '-'} "
        f"recovery={(r.get('first_recovery_timestamp') or '-')[11:16] if r.get('first_recovery_timestamp') else '-'} "
        f"invalid={(r.get('midpoint_invalidation_timestamp') or '-')[11:16] if r.get('midpoint_invalidation_timestamp') else '-'} "
        f"MFE={r.get('mfe')} class={r.get('final_class')}"
    )
summary += [
"",
"Research only. Frozen B entry unchanged.",
"Warning is NOT automatically an exit.",
"Underlying NIFTY points are not option-premium P&L.",
]
txt="\n".join(summary)
txt_path=OUT/"b-family-health-summary-v1.txt"; txt_path.write_text(txt)
print(txt)
print("\nCSV:",csv_path)
print("TXT:",txt_path)
