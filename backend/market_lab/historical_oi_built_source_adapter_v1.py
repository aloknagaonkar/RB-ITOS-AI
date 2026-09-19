from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path("data/historical-evidence/historical-oi-build")
MODEL = "HISTORICAL_OI_BUILT_SOURCE_ADAPTER_V1"

def _load(session_date: str) -> dict[str, Any]:
    p = ROOT / session_date / "positioning.json"
    if not p.exists():
        raise KeyError(f"No built historical OI data for {session_date}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    sessions = payload.get("sessions") or []
    if len(sessions) != 1:
        raise ValueError(f"Expected one built session for {session_date}")
    s = sessions[0]
    if s.get("status") != "AVAILABLE":
        raise ValueError(f"Built session {session_date} is not AVAILABLE")
    return s

def _num(v):
    if v in (None, ""): return None
    try: return float(v)
    except (TypeError, ValueError): return None

def _sum(rows, key):
    vals=[_num(r.get(key)) for r in rows]
    if not vals or any(v is None for v in vals): return None
    return float(sum(vals))

def _pct(delta, previous):
    return None if delta is None or previous in (None,0) else delta/previous*100.0

def _pcr(pe, ce):
    return None if pe is None or ce in (None,0) else pe/ce

def _pattern(ce, pe):
    m={
      ("SHORT_BUILDUP","LONG_BUILDUP"):"BEARISH_CE_SB_PLUS_PE_LB",
      ("LONG_BUILDUP","SHORT_BUILDUP"):"BULLISH_CE_LB_PLUS_PE_SB",
      ("SHORT_COVERING","LONG_UNWINDING"):"BULLISH_CE_SC_PLUS_PE_LU",
      ("LONG_UNWINDING","SHORT_COVERING"):"BEARISH_CE_LU_PLUS_PE_SC",
    }
    return m.get((ce,pe), f"ATM_{ce or 'UNAVAILABLE'}__{pe or 'UNAVAILABLE'}")

def built_inventory():
    rows=[]
    if ROOT.exists():
        for child in sorted(ROOT.iterdir(), reverse=True):
            if not child.is_dir(): continue
            sp=child/"build-status.json"
            dp=child/"positioning.json"
            if not sp.exists() or not dp.exists(): continue
            try: status=json.loads(sp.read_text())
            except Exception: continue
            if status.get("status")!="COMPLETE": continue
            try: s=_load(child.name)
            except Exception: continue
            rows.append({
              "session_date":child.name,
              "expiry":s.get("expiry"),
              "rows":74,
              "raw_positioning_rows":s.get("row_count"),
              "source":"BUILT",
            })
    return {"model":MODEL,"source":"BUILT","session_count":len(rows),"sessions":rows}

def build_checkpoint_rows(session_date: str):
    s=_load(session_date)
    raw=s.get("rows") or []
    by_ts=defaultdict(list)
    for r in raw:
        by_ts[datetime.fromisoformat(str(r["timestamp"]))].append(r)
    if not by_ts: raise ValueError("No positioning rows")

    first=min(by_ts)
    start=first.replace(hour=9,minute=20,second=0,microsecond=0)
    end=start.replace(hour=15,minute=25)
    checkpoints=[]
    t=start
    while t<=end:
        checkpoints.append(t); t+=timedelta(minutes=5)

    fixed_atm=None
    fixed_strikes=[]
    if by_ts.get(start):
        fixed_atm=_num(by_ts[start][0].get("moving_atm"))
        fixed_strikes=sorted(float(r["strike"]) for r in by_ts[start])

    out=[]
    for ts in checkpoints:
        current=sorted(by_ts.get(ts,[]), key=lambda r: float(r["strike"]))
        if len(current)!=11: continue
        strikes=[float(r["strike"]) for r in current]
        spot=_num(current[0].get("spot"))
        atm=_num(current[0].get("moving_atm"))
        ce=_sum(current,"ce_open_interest")
        pe=_sum(current,"pe_open_interest")

        prev_map={float(r["strike"]):r for r in by_ts.get(ts-timedelta(minutes=5),[])}
        prev=[prev_map[x] for x in strikes if x in prev_map]
        prev_ce=_sum(prev,"ce_open_interest") if len(prev)==11 else None
        prev_pe=_sum(prev,"pe_open_interest") if len(prev)==11 else None
        ce_d=ce-prev_ce if ce is not None and prev_ce is not None else None
        pe_d=pe-prev_pe if pe is not None and prev_pe is not None else None
        cp=_pcr(pe,ce); pp=_pcr(prev_pe,prev_ce)
        pc=cp-pp if cp is not None and pp is not None else None

        atm_row=min(current,key=lambda r:abs(float(r["strike"])-float(atm or r["strike"])))
        ces=atm_row.get("ce_5m_state"); pes=atm_row.get("pe_5m_state")

        amap={float(r["strike"]):r for r in by_ts.get(ts,[])}
        fixed=[amap[x] for x in fixed_strikes if x in amap]
        fce=_sum(fixed,"ce_open_interest") if len(fixed)==len(fixed_strikes) else None
        fpe=_sum(fixed,"pe_open_interest") if len(fixed)==len(fixed_strikes) else None

        def fwd(minutes):
            later=by_ts.get(ts+timedelta(minutes=minutes),[])
            if not later or spot is None:return None
            ls=_num(later[0].get("spot"))
            return None if ls is None else ls-spot

        out.append({
          "block":"BUILT","source":"BUILT","session_date":session_date,
          "timestamp":ts.isoformat(),"time":ts.strftime("%H:%M"),
          "spot":spot,"moving_atm":atm,"fixed_atm":fixed_atm,
          "m_ce_oi":ce,"m_pe_oi":pe,"m_ce_delta":ce_d,"m_pe_delta":pe_d,
          "m_ce_pct":_pct(ce_d,prev_ce),"m_pe_pct":_pct(pe_d,prev_pe),
          "m_activity":None if ce_d is None or pe_d is None else abs(ce_d)+abs(pe_d),
          "m_pcr_previous":pp,"m_pcr":cp,"m_pcr_change":pc,
          "m_common_strikes":str(strikes),
          "atm_ce_price_pct":_num(atm_row.get("ce_5m_premium_change_pct")),
          "atm_pe_price_pct":_num(atm_row.get("pe_5m_premium_change_pct")),
          "ce_state":ces,"pe_state":pes,
          "f_ce_delta":None,"f_pe_delta":None,"f_activity":None,"f_pcr":_pcr(fpe,fce),
          "forward_5m_points":fwd(5),"forward_10m_points":fwd(10),"forward_15m_points":fwd(15),
          "pattern_family":_pattern(ces,pes),
        })
    return {"model":MODEL,"source":"BUILT","session_date":session_date,"expiry":s.get("expiry"),
            "row_count":len(out),"raw_positioning_rows":s.get("row_count"),"rows":out}
