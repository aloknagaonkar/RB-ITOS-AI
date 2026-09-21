"""Read-only UI projection for the fixed-session anchor."""
from __future__ import annotations
import json
from datetime import datetime,timedelta
from pathlib import Path
from typing import Any
from .domain import IST,Snapshot

MODEL="LIVE_FIXED_SESSION_UI_PROJECTION_V1"
DEFAULT_ANCHOR_JOURNAL=Path("data/live-observation/shadow-v1/fixed-anchor.jsonl")
HORIZONS=(300,900,1800)

def _num(v):
    try:return None if v is None else float(v)
    except (TypeError,ValueError):return None

def _pct(cur,base):
    return None if cur is None or base in (None,0) else (float(cur)-float(base))/float(base)*100.0

def _pcr(pe,ce):
    return None if pe is None or ce in (None,0) else float(pe)/float(ce)

def load_fixed_anchor_index(path=DEFAULT_ANCHOR_JOURNAL):
    p=Path(path);out={}
    if not p.exists():return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        try:item=json.loads(raw)
        except Exception:continue
        if not isinstance(item,dict) or item.get("status")!="AVAILABLE":continue
        k=(str(item.get("session_date") or ""),str(item.get("underlying") or ""),str(item.get("expiry") or ""))
        if all(k):out[k]=item
    return out

def _fixed_result(evaluation):
    return next((r for r in evaluation.get("results",[]) if isinstance(r,dict) and r.get("mode")=="fixed"),None)

def _anchor_rows(anchor):
    rows={}
    for leg in anchor.get("legs") or []:
        if not isinstance(leg,dict):continue
        try:strike=float(leg["strike"]);oi=int(leg["open_interest"])
        except Exception:continue
        side=str(leg.get("side") or "").upper();key=str(leg.get("instrument_key") or "")
        if side in {"CE","PE"} and key:rows.setdefault(strike,{})[side]={"instrument_key":key,"baseline_oi":oi}
    return rows

def project_fixed_session_ui(snapshot_payload,evaluation_payload,*,anchor_index=None,anchor_journal=DEFAULT_ANCHOR_JOURNAL):
    try:snapshot=Snapshot.model_validate(snapshot_payload)
    except Exception:return None
    session_date=snapshot.received_at.astimezone(IST).date().isoformat()
    idx=anchor_index if anchor_index is not None else load_fixed_anchor_index(anchor_journal)
    anchor=idx.get((session_date,snapshot.underlying,snapshot.expiry.isoformat()))
    if anchor is None:return None
    try:
        checkpoint=datetime.fromisoformat(str(anchor["checkpoint_time"])).astimezone(IST)
    except Exception:return None
    if snapshot.received_at.astimezone(IST)<checkpoint:return None
    by_quote={q.key:q for q in snapshot.quotes}
    pairs=_anchor_rows(anchor);strikes=tuple(sorted(pairs))
    if not strikes:return None
    rows=[];missing=[];ce_now_total=pe_now_total=ce_base_total=pe_base_total=0;keys=[]
    for strike in strikes:
        pair=pairs[strike]
        if "CE" not in pair or "PE" not in pair:return None
        ce,pe=pair["CE"],pair["PE"];ce_key,pe_key=ce["instrument_key"],pe["instrument_key"];keys.extend((ce_key,pe_key))
        ce_base,pe_base=int(ce["baseline_oi"]),int(pe["baseline_oi"]);ce_base_total+=ce_base;pe_base_total+=pe_base
        ce_q,pe_q=by_quote.get(ce_key),by_quote.get(pe_key)
        ce_now=int(ce_q.oi) if ce_q is not None and ce_q.oi is not None else None
        pe_now=int(pe_q.oi) if pe_q is not None and pe_q.oi is not None else None
        if ce_now is None:missing.append(ce_key)
        else:ce_now_total+=ce_now
        if pe_now is None:missing.append(pe_key)
        else:pe_now_total+=pe_now
        rows.append({"strike":strike,"ce_instrument_key":ce_key,"pe_instrument_key":pe_key,
                     "call_baseline_oi":ce_base,"put_baseline_oi":pe_base,"call_oi":ce_now,"put_oi":pe_now,
                     "call_change_oi":None if ce_now is None else ce_now-ce_base,
                     "put_change_oi":None if pe_now is None else pe_now-pe_base,
                     "call_change_pct":_pct(ce_now,ce_base),"put_change_pct":_pct(pe_now,pe_base),
                     "strike_pcr":_pcr(pe_now,ce_now)})
    complete=not missing
    cur_ce=ce_now_total if complete else None;cur_pe=pe_now_total if complete else None
    ce_delta=None if not complete else ce_now_total-ce_base_total;pe_delta=None if not complete else pe_now_total-pe_base_total
    current_pcr=_pcr(cur_pe,cur_ce);baseline_pcr=_pcr(pe_base_total,ce_base_total)
    provenance=str(anchor.get("provenance") or "ANCHOR_MISSING")
    recovered=provenance=="ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M";label="RECOVERED ANCHOR" if recovered else "LIVE ANCHOR"
    display=dict(_fixed_result(evaluation_payload) or {"mode":"fixed"})
    display.update({"mode":"fixed","atm":anchor.get("atm"),"strikes":list(strikes),"contract_keys":keys,
                    "expected":len(keys),"received":len(keys)-len(set(missing)),"put_oi":cur_pe,"call_oi":cur_ce,
                    "put_prev_oi":pe_base_total,"call_prev_oi":ce_base_total,"put_change_oi":pe_delta,"call_change_oi":ce_delta,
                    "put_change_pct":_pct(cur_pe,pe_base_total),"call_change_pct":_pct(cur_ce,ce_base_total),"pcr":current_pcr,
                    "issues":[] if complete and provenance=="ANCHOR_LIVE" else
                             (["recovered_anchor_upstox_intraday_1m"] if complete and recovered else ["fixed_session_current_snapshot_incomplete"])})
    return {"model":MODEL,"status":"AVAILABLE" if complete else "INCOMPLETE","provenance":provenance,"label":label,
            "source_semantics":anchor.get("source_semantics"),"source_candle_time":anchor.get("source_candle_time"),
            "checkpoint_time":anchor.get("checkpoint_time"),"source_received_at":snapshot.received_at.astimezone(IST).isoformat(),
            "atm":anchor.get("atm"),"strikes":list(strikes),"contract_count":len(keys),"missing_instrument_keys":sorted(set(missing)),
            "baseline_ce_oi":ce_base_total,"baseline_pe_oi":pe_base_total,"current_ce_oi":cur_ce,"current_pe_oi":cur_pe,
            "ce_delta":ce_delta,"pe_delta":pe_delta,"imbalance":None if ce_delta is None or pe_delta is None else pe_delta-ce_delta,
            "baseline_pcr":baseline_pcr,"current_pcr":current_pcr,
            "pcr_change":None if current_pcr is None or baseline_pcr is None else current_pcr-baseline_pcr,
            "rows":rows,"display_result":display}

def attach_fixed_session_trends(history,*,tolerance_seconds=60,flat_threshold=0.01):
    pts=[]
    for item in history:
        ui=item.get("fixed_session_ui")
        if not isinstance(ui,dict) or ui.get("status")!="AVAILABLE":continue
        pcr=_num(ui.get("current_pcr"));ts_text=ui.get("source_received_at");session_key=str(ui.get("checkpoint_time") or "")[:10]
        if pcr is None or not ts_text or not session_key:continue
        try:ts=datetime.fromisoformat(str(ts_text)).astimezone(IST)
        except ValueError:continue
        pts.append((item,ts,pcr,session_key))
    for item,cur_ts,cur_pcr,session_key in pts:
        trends={}
        for h in HORIZONS:
            target=cur_ts-timedelta(seconds=h);cand=[]
            for _,prior_ts,prior_pcr,prior_session in pts:
                if prior_session!=session_key or prior_ts>=cur_ts:continue
                err=abs((prior_ts-target).total_seconds())
                if err<=tolerance_seconds:cand.append((err,prior_ts,prior_pcr))
            if not cand:
                trends[str(h)]={"requested_horizon_seconds":h,"absolute_pcr_change":None,"classification":"UNAVAILABLE","source":"FIXED_SESSION_ANCHOR_UI_PROJECTION"};continue
            _,prior_ts,prior_pcr=min(cand,key=lambda x:(x[0],x[1]));chg=cur_pcr-prior_pcr
            cls="FLAT" if abs(chg)<=flat_threshold else ("RISING" if chg>0 else "FALLING")
            trends[str(h)]={"requested_horizon_seconds":h,"absolute_pcr_change":chg,"classification":cls,
                            "source_timestamp":prior_ts.isoformat(),"source":"FIXED_SESSION_ANCHOR_UI_PROJECTION"}
        item["fixed_session_trends"]=trends
