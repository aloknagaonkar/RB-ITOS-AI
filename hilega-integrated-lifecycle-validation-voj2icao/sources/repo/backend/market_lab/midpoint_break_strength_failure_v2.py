"""Sequential midpoint break-strength and failure research V2."""
from __future__ import annotations
import argparse, json, math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2"
SOURCE_VERSION = "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1"
ALLOWED_BLOCKS = {"TRAIN","OOS_A","OOS_B","OOS_C","OOS_D"}
CHECKPOINTS = (0,1,3)
VALID_OI_STATES = {"LONG_BUILDUP","SHORT_BUILDUP","LONG_UNWINDING","SHORT_COVERING"}

ALIASES = {
    "momentum_5m": ("directional_momentum_5m","spot_momentum_5m"),
    "acceptance_pct": ("directional_acceptance_pct","post_break_acceptance_pct","acceptance_pct","close_acceptance_pct"),
    "consecutive_closes": ("consecutive_closes_beyond_boundary","consecutive_closes_below_low","consecutive_closes_above_high","post_break_consecutive_closes"),
    "extreme_count": ("new_directional_close_extreme_count","new_close_extreme_count","new_lower_close_count","new_higher_close_count"),
    "progress_points": ("directional_progress_points","progress_points","downside_progress_points","upside_progress_points"),
    "velocity": ("directional_velocity_points_per_minute","velocity_points_per_minute","downside_velocity_points_per_minute","upside_velocity_points_per_minute"),
    "rebound_points": ("directional_rebound_points","maximum_rebound_from_low_close_points","maximum_pullback_from_high_close_points","maximum_rebound_points"),
    "midpoint_cross_count": ("midpoint_cross_count","post_break_midpoint_cross_count"),
}
FEATURE_DIRECTIONS = {
    "momentum_5m":"HIGHER","acceptance_pct":"HIGHER","consecutive_closes":"HIGHER",
    "extreme_count":"HIGHER","progress_points":"HIGHER","velocity":"HIGHER",
    "rebound_points":"LOWER","midpoint_cross_count":"LOWER",
}

def load_json(path: Path) -> dict[str,Any]:
    x=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x,dict): raise ValueError("JSON root must be an object")
    return x

def num(v):
    if v is None or isinstance(v,bool): return None
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None

def first_num(row,names):
    for n in names:
        if n in row:
            x=num(row.get(n))
            if x is not None: return x
    return None

def first_text(row,names):
    for n in names:
        v=row.get(n)
        if v is not None and str(v).strip(): return str(v)
    return None

def validate_framework(f):
    if f.get("research_version") != SOURCE_VERSION:
        raise ValueError(f"expected {SOURCE_VERSION}, got {f.get('research_version')!r}")
    g=f.get("leakage_guard") or {}
    if g.get("oos_e_f_g_h_used") is not False or g.get("oos_h_used") is not False:
        raise ValueError("source leakage guard failed")
    blocks={str(e.get("block")) for e in f.get("events",[])}
    bad=blocks-ALLOWED_BLOCKS
    if bad: raise ValueError(f"forbidden blocks present: {sorted(bad)}")

def direction_for_event(e):
    s=str(e.get("setup_type") or "")
    if s.startswith("RED"): return "BEARISH"
    if s.startswith("GREEN"): return "BULLISH"
    return None

def outcome_for_event(e):
    return first_text(e,("primary_outcome","outcome","classification","primary_classification"))

def outcome_label(direction,outcome):
    if not outcome: return "UNRESOLVED"
    if direction=="BEARISH":
        if outcome in {"RED_BEARISH_BREAK_AND_GO","RED_BEARISH_BASE_THEN_GO"}: return "CONTINUATION"
        if outcome=="RED_BREAK_BULLISH_RECLAIM": return "REVERSAL"
    else:
        if outcome in {"GREEN_BULLISH_BREAK_AND_GO","GREEN_BULLISH_BASE_THEN_GO"}: return "CONTINUATION"
        if outcome=="GREEN_BREAK_BEARISH_RECLAIM": return "REVERSAL"
    return "UNRESOLVED" if "UNRESOLVED" in outcome else "OTHER"

def snapshot_at(e,offset):
    xs=e.get("snapshots") or e.get("evidence_snapshots") or []
    label_map={"T0":0,"T_PLUS_1":1,"T+1":1,"T_PLUS_3":3,"T+3":3}
    for s in xs:
        if not isinstance(s,dict): continue
        v=s.get("offset_minutes",s.get("minutes_since_boundary_break"))
        if v is None: v=label_map.get(str(s.get("offset_label") or s.get("checkpoint") or ""))
        try:
            if v is not None and int(v)==offset: return s
        except (TypeError,ValueError): pass
    return None

def oi_state(s,side):
    sl=side.lower()
    v=first_text(s,(f"{sl}_5m_state",f"{sl}_state",f"{side}_5m_state",f"{side}_state"))
    return v if v in VALID_OI_STATES else None

def classify_oi_pair(direction,ce,pe):
    if ce is None or pe is None:
        return {"combined_state":"UNAVAILABLE","support_level":"UNAVAILABLE","supportive":None,"reversal_warning":None}
    pair=(ce,pe)
    if direction=="BEARISH":
        strong=("SHORT_BUILDUP","LONG_BUILDUP")
        secondary={("SHORT_BUILDUP","SHORT_COVERING"),("LONG_UNWINDING","LONG_BUILDUP")}
        reverse=("SHORT_COVERING","LONG_UNWINDING")
        strong_name,support_name="STRONG_BEARISH","BEARISH_SUPPORTIVE"
    else:
        strong=("LONG_BUILDUP","SHORT_BUILDUP")
        secondary={("SHORT_COVERING","SHORT_BUILDUP"),("LONG_BUILDUP","LONG_UNWINDING")}
        reverse=("LONG_UNWINDING","SHORT_COVERING")
        strong_name,support_name="STRONG_BULLISH","BULLISH_SUPPORTIVE"
    if pair==strong:
        return {"combined_state":strong_name,"support_level":"STRONG","supportive":True,"reversal_warning":False}
    if pair in secondary:
        return {"combined_state":support_name,"support_level":"SECONDARY","supportive":True,"reversal_warning":False}
    if pair==reverse:
        return {"combined_state":"OPPOSITE_POSITIONING","support_level":"NONE","supportive":False,"reversal_warning":True}
    return {"combined_state":"MIXED_OR_OPPOSING","support_level":"NONE","supportive":False,"reversal_warning":False}

def extract_features(s,direction):
    out={k:first_num(s,v) for k,v in ALIASES.items()}
    if out["momentum_5m"] is not None and direction=="BEARISH":
        out["momentum_5m"]=-out["momentum_5m"]
    return out

def midpoint_threshold(pos,neg):
    return None if not pos or not neg else (median(pos)+median(neg))/2.0

def build_rows(f):
    rows=[]
    for e in f.get("events",[]):
        block=str(e.get("block"))
        direction=direction_for_event(e)
        if block not in ALLOWED_BLOCKS or direction is None: continue
        outcome=outcome_for_event(e); label=outcome_label(direction,outcome)
        if label not in {"CONTINUATION","REVERSAL","UNRESOLVED"}: continue
        for cp in CHECKPOINTS:
            s=snapshot_at(e,cp)
            if s is None: continue
            ce,pe=oi_state(s,"CE"),oi_state(s,"PE")
            oi=classify_oi_pair(direction,ce,pe)
            oi.update({
                "ce_state":ce,"pe_state":pe,
                "ce_premium_change_5m_pct":first_num(s,("ce_5m_premium_change_pct","ce_premium_change_5m_pct")),
                "ce_oi_change_5m_pct":first_num(s,("ce_5m_oi_change_pct","ce_oi_change_5m_pct")),
                "pe_premium_change_5m_pct":first_num(s,("pe_5m_premium_change_pct","pe_premium_change_5m_pct")),
                "pe_oi_change_5m_pct":first_num(s,("pe_5m_oi_change_pct","pe_oi_change_5m_pct")),
            })
            rows.append({
                "block":block,"session_date":e.get("session_date"),"setup_type":e.get("setup_type"),
                "direction":direction,"primary_outcome":outcome,"outcome_label":label,
                "checkpoint_minutes":cp,"checkpoint_label":"T0" if cp==0 else f"T+{cp}",
                "timestamp":s.get("timestamp"),"price_features":extract_features(s,direction),"oi":oi,
            })
    return rows

def build_thresholds(rows):
    out={}
    for d in ("BEARISH","BULLISH"):
        out[d]={}
        for cp in CHECKPOINTS:
            rs=[r for r in rows if r["block"]=="TRAIN" and r["direction"]==d and r["checkpoint_minutes"]==cp and r["outcome_label"] in {"CONTINUATION","REVERSAL"}]
            spec={}
            for feat,pref in FEATURE_DIRECTIONS.items():
                pos=[r["price_features"][feat] for r in rs if r["outcome_label"]=="CONTINUATION" and r["price_features"][feat] is not None]
                neg=[r["price_features"][feat] for r in rs if r["outcome_label"]=="REVERSAL" and r["price_features"][feat] is not None]
                spec[feat]={"threshold":midpoint_threshold(pos,neg),"preferred_direction":pref,
                            "continuation_median":median(pos) if pos else None,"reversal_median":median(neg) if neg else None,
                            "continuation_count":len(pos),"reversal_count":len(neg)}
            out[d][str(cp)]=spec
    return out

def feature_pass(v,spec):
    t=spec.get("threshold")
    if v is None or t is None: return None
    return v>=t if spec["preferred_direction"]=="HIGHER" else v<=t

def score_row(r,thresholds):
    spec=thresholds[r["direction"]][str(r["checkpoint_minutes"])]
    passes={f:feature_pass(v,spec[f]) for f,v in r["price_features"].items()}
    known=[v for v in passes.values() if v is not None]
    score=sum(v is True for v in known); n=len(known); ratio=score/n if n else None
    if r["oi"]["reversal_warning"] is True: state="FAILURE_WARNING"
    elif ratio is not None and ratio>=0.75 and r["oi"]["support_level"] in {"STRONG","SECONDARY"}:
        state="STRONG_CONTINUATION_EVIDENCE"
    elif ratio is not None and ratio<=0.375: state="FAILURE_WARNING"
    else: state="MIXED_WAIT"
    r["price_feature_passes"]=passes
    r["price_score"]={"passed":score,"available":n,"ratio":ratio}
    r["research_state"]=state

def add_transitions(rows):
    groups=defaultdict(list)
    for r in rows: groups[(r["block"],r["session_date"],r["setup_type"],r["primary_outcome"])].append(r)
    rank={"STRONG":2,"SECONDARY":1,"NONE":0,"UNAVAILABLE":-1}
    for g in groups.values():
        g.sort(key=lambda r:r["checkpoint_minutes"]); prev=None
        for r in g:
            if prev is None: r["oi_transition"]="INITIAL"
            elif r["oi"]["reversal_warning"] is True: r["oi_transition"]="REVERSAL_WARNING"
            else:
                a,b=rank.get(prev["oi"]["support_level"],-1),rank.get(r["oi"]["support_level"],-1)
                r["oi_transition"]="STRENGTHENING" if b>a else "WEAKENING" if b<a else "STABLE"
            prev=r

def summarize(rows):
    out={}
    for d in ("BEARISH","BULLISH"):
        out[d]={}
        for cp in CHECKPOINTS:
            rs=[r for r in rows if r["direction"]==d and r["checkpoint_minutes"]==cp]
            by={}
            for label in ("CONTINUATION","REVERSAL","UNRESOLVED"):
                p=[r for r in rs if r["outcome_label"]==label]
                by[label]={"count":len(p),
                           "research_states":dict(Counter(r["research_state"] for r in p)),
                           "oi_support":dict(Counter(r["oi"]["support_level"] for r in p)),
                           "oi_transitions":dict(Counter(r.get("oi_transition","UNKNOWN") for r in p))}
            out[d]["T0" if cp==0 else f"T+{cp}"]={"count":len(rs),"research_states":dict(Counter(r["research_state"] for r in rs)),"by_outcome":by}
    return out

def analyze(f):
    validate_framework(f)
    rows=build_rows(f)
    if not rows: raise ValueError("No T0/T+1/T+3 primary snapshots found in framework JSON")
    thresholds=build_thresholds(rows)
    for r in rows: score_row(r,thresholds)
    add_transitions(rows)
    return {
        "status":"AVAILABLE","research_version":RESEARCH_VERSION,"source_version":SOURCE_VERSION,
        "checkpoints":["T0_BOUNDARY_BREAK","T_PLUS_1","T_PLUS_3"],
        "oi_states_included":sorted(VALID_OI_STATES),
        "strong_oi_definitions":{"BEARISH":"CE SHORT_BUILDUP + PE LONG_BUILDUP","BULLISH":"CE LONG_BUILDUP + PE SHORT_BUILDUP"},
        "explicit_reversal_oi_definitions":{"BEARISH_FAILURE_WARNING":"CE SHORT_COVERING + PE LONG_UNWINDING","BULLISH_FAILURE_WARNING":"CE LONG_UNWINDING + PE SHORT_COVERING"},
        "thresholds":thresholds,"summary":summarize(rows),
        "leakage_guard":{"thresholds_derived_from_train_only":True,"oos_a_b_c_d_used_for_threshold_selection":False,
                         "oos_e_f_g_h_used":False,"oos_h_used":False,"future_outcome_used_as_checkpoint_feature":False,
                         "pnl_used_for_rule_selection":False,"all_four_oi_states_included":True,"research_emits_trade_order":False},
        "rows":rows,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--framework",required=True); p.add_argument("--output",required=True)
    a=p.parse_args(); result=analyze(load_json(Path(a.framework)))
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"research_version":result["research_version"],
                      "summary":result["summary"],"leakage_guard":result["leakage_guard"],"output":str(out)},indent=2))
if __name__=="__main__": main()
