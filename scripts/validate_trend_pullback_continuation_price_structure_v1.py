from __future__ import annotations

import argparse, csv, json, statistics
from collections import defaultdict
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any

MODEL = "TREND_PULLBACK_CONTINUATION_PRICE_STRUCTURE_V1"
VARIANTS = ("A_TREND_RESUME", "B_CONTROLLED_PULLBACK", "C_EMA10_RECLAIM", "D_STRUCTURE_HOLD")
HORIZONS = (5, 10, 15, 30)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8"); return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def load_session(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sessions = doc.get("sessions") or []
    if len(sessions) != 1 or sessions[0].get("status") != "AVAILABLE":
        raise ValueError(f"{path}: expected one AVAILABLE session")
    return sessions[0]


def minute_spot_index(session: dict[str, Any]) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for r in session.get("rows") or []:
        ts = datetime.fromisoformat(str(r["timestamp"])).replace(second=0, microsecond=0)
        if ts in out: continue
        if r.get("spot") is None: continue
        out[ts] = float(r["spot"])
    return out


def ema(values: list[float], period: int) -> list[float]:
    if not values: return []
    a = 2.0 / (period + 1.0); out = [float(values[0])]
    for v in values[1:]: out.append(a * float(v) + (1-a) * out[-1])
    return out


def build_5m_series(spots: dict[datetime, float]) -> list[tuple[datetime, float]]:
    if not spots: return []
    first = min(spots); ds = first.date(); tz = first.tzinfo
    t = datetime.combine(ds, time(9,20), tzinfo=tz)
    end = datetime.combine(ds, time(15,25), tzinfo=tz)
    out=[]
    while t <= end:
        if t in spots: out.append((t, spots[t]))
        t += timedelta(minutes=5)
    return out


def direction_value(direction: str, value: float) -> float:
    return value if direction == "BULLISH" else -value


def trend_state(i:int, closes:list[float], e3:list[float], e10:list[float], e21:list[float]) -> str | None:
    if i < 3: return None
    slope = e21[i] - e21[i-3]
    if e3[i] > e10[i] > e21[i] and slope > 0: return "BULLISH"
    if e3[i] < e10[i] < e21[i] and slope < 0: return "BEARISH"
    return None


def conditions_at(i:int, closes:list[float], e3:list[float], e10:list[float], e21:list[float]) -> dict[str, tuple[bool,str|None]]:
    out = {v:(False,None) for v in VARIANTS}
    if i < 8: return out
    # trend must have existed before the trigger bar; candidate direction is based on i-1 context
    d = trend_state(i-1, closes, e3, e10, e21)
    if d is None: return out
    s = 1 if d == "BULLISH" else -1
    # at least one counter-trend close change in the previous 3 completed 5m bars
    changes = [closes[j]-closes[j-1] for j in range(i-3, i)]
    had_pullback = any(s*x < 0 for x in changes)
    resume_break = s*(closes[i] - (max(closes[i-2:i]) if s>0 else min(closes[i-2:i]))) > 0
    a = had_pullback and resume_break
    out["A_TREND_RESUME"] = (a,d)

    # Controlled pullback: during previous 3 bars price does not close through EMA21.
    hold21 = all((closes[j] >= e21[j] if s>0 else closes[j] <= e21[j]) for j in range(i-3, i))
    b = a and hold21
    out["B_CONTROLLED_PULLBACK"] = (b,d)

    # EMA10 reclaim: pullback reaches/touches the EMA10 zone, trigger closes back on trend side of EMA3.
    touched10 = any((closes[j] <= e10[j] if s>0 else closes[j] >= e10[j]) for j in range(i-3, i))
    reclaim3 = (closes[i] > e3[i] if s>0 else closes[i] < e3[i])
    c = b and touched10 and reclaim3
    out["C_EMA10_RECLAIM"] = (c,d)

    # Close-structure hold: pullback extreme holds above/below the earlier 4-bar structural extreme.
    recent = closes[i-3:i]
    prior = closes[i-7:i-3]
    structure_hold = (min(recent) > min(prior)) if s>0 else (max(recent) < max(prior))
    dcond = b and structure_hold
    out["D_STRUCTURE_HOLD"] = (dcond,d)
    return out


def move_start_map(path: Path | None) -> dict[str,str]:
    if path is None or not path.exists(): return {}
    doc=json.loads(path.read_text(encoding="utf-8")); out={}
    for r in doc.get("rows") or []:
        if r.get("session_date") and r.get("move_start_time"): out.setdefault(str(r["session_date"]), str(r["move_start_time"]))
    return out


def resolve_move_start(ds:str, raw:str, ref:datetime) -> datetime:
    if "T" in raw: return datetime.fromisoformat(raw)
    off=ref.strftime("%z"); off=f"{off[:3]}:{off[3:]}" if off else ""
    return datetime.fromisoformat(f"{ds}T{raw}:00{off}")


def evaluate_candidate(ds:str, variant:str, direction:str, ts:datetime, spot:float, spots:dict[datetime,float], known_dir:str|None, move_start:str|None) -> dict[str,Any]:
    s = 1 if direction=="BULLISH" else -1
    row={"session_date":ds,"variant":variant,"direction":direction,"trigger_time":ts.isoformat(),"trigger_spot":spot,
         "known_session_direction":known_dir,"near_known_move_start_same_direction":False}
    if move_start and known_dir == direction:
        ms=resolve_move_start(ds, move_start, ts); row["near_known_move_start_same_direction"] = abs((ts-ms).total_seconds()/60.0) <= 15
    vals=[]
    for h in HORIZONS:
        v=spots.get(ts+timedelta(minutes=h)); mv=None if v is None else s*(v-spot); row[f"move_{h}m"]=mv
        if mv is not None: vals.append(mv)
    path=[]
    for m in range(1,31):
        v=spots.get(ts+timedelta(minutes=m))
        if v is None: path=[]; break
        path.append(s*(v-spot))
    row["mfe_30m"] = max(path) if path else None; row["mae_30m"] = min(path) if path else None
    return row


def summarize(rows:list[dict[str,Any]]) -> list[dict[str,Any]]:
    out=[]
    for v in VARIANTS:
      for d in ("BULLISH","BEARISH"):
        xs=[r for r in rows if r["variant"]==v and r["direction"]==d]
        def med(k):
            a=[float(r[k]) for r in xs if r.get(k) not in (None,"")]; return statistics.median(a) if a else None
        def hit(k):
            a=[float(r[k]) for r in xs if r.get(k) not in (None,"")]; return 100*sum(x>0 for x in a)/len(a) if a else None
        out.append({"variant":v,"direction":d,"events":len(xs),"sessions":len({r['session_date'] for r in xs}),"signals_per_session":len(xs)/len({r['session_date'] for r in xs}) if xs else None,
                    "near_move_count":sum(bool(r.get("near_known_move_start_same_direction")) for r in xs),
                    "median_5m":med("move_5m"),"median_10m":med("move_10m"),"median_15m":med("move_15m"),"median_30m":med("move_30m"),
                    "hit15_pct":hit("move_15m"),"hit30_pct":hit("move_30m"),"median_mfe30":med("mfe_30m"),"median_mae30":med("mae_30m")})
    return out


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--inventory",default="data/historical-evidence/control-failure-expiry-aware-v6-2/expiry-aware-inventory-v6-2.csv")
    ap.add_argument("--positioning-root",default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--move-start-replay",default="data/historical-evidence/trend-day-move-start-oi-replay-v1.json")
    ap.add_argument("--output-dir",default="data/historical-evidence/trend-pullback-continuation-price-v1")
    args=ap.parse_args()
    inv=load_csv(Path(args.inventory)); available=[r for r in inv if r.get("status")=="AVAILABLE"]
    move_starts=move_start_map(Path(args.move_start_replay)); candidates=[]; errors=[]
    for ir in available:
        ds=ir["session_date"]; known=ir.get("known_direction") or ir.get("direction")
        try:
            sess=load_session(Path(args.positioning_root)/ds/"positioning.json"); spots=minute_spot_index(sess); series=build_5m_series(spots)
            times=[t for t,_ in series]; closes=[x for _,x in series]; e3=ema(closes,3); e10=ema(closes,10); e21=ema(closes,21)
            prev_active={v:False for v in VARIANTS}
            for i,(ts,close) in enumerate(series):
                conds=conditions_at(i,closes,e3,e10,e21)
                for v,(active,direction) in conds.items():
                    # Edge-trigger only: first bar where the structure becomes true.
                    if active and not prev_active[v] and direction:
                        candidates.append(evaluate_candidate(ds,v,direction,ts,close,spots,known,move_starts.get(ds)))
                    prev_active[v]=active
        except Exception as exc:
            errors.append({"session_date":ds,"error":f"{type(exc).__name__}:{exc}"})
    summary=summarize(candidates); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    write_csv(out/"price-structure-candidates-v1.csv",candidates); write_csv(out/"price-structure-summary-v1.csv",summary); write_csv(out/"price-structure-errors-v1.csv",errors)
    (out/"price-structure-summary-v1.json").write_text(json.dumps({"model":MODEL,"price_only":True,"oi_pcr_used_for_signal":False,"available_sessions":len(available),"candidates":len(candidates),"errors":errors,"variants":VARIANTS,"summary":summary},indent=2)+"\n",encoding="utf-8")
    print(f"model={MODEL} available_sessions={len(available)} candidates={len(candidates)} errors={len(errors)}")
    print("\n=== BRANCH B PRICE-STRUCTURE DISCOVERY ===")
    for r in summary:
        print(f"{r['variant']} {r['direction']}: events={r['events']} sessions={r['sessions']} sig/session={r['signals_per_session']} near_move={r['near_move_count']} med15={r['median_15m']} med30={r['median_30m']} hit15={r['hit15_pct']}% hit30={r['hit30_pct']}% MFE30={r['median_mfe30']} MAE30={r['median_mae30']}")
    print("\nPrice structure only. OI/PCR are not used in candidate generation.")
    print(f"CANDIDATES_CSV: {out/'price-structure-candidates-v1.csv'}")
    print(f"SUMMARY_CSV: {out/'price-structure-summary-v1.csv'}")
    print(f"ERRORS_CSV: {out/'price-structure-errors-v1.csv'}")
    return 0

if __name__=="__main__": raise SystemExit(main())
