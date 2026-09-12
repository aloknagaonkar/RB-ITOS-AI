"""Bidirectional Stage-2 discriminator and frozen TRAIN-bucket research.

Evaluates bullish and bearish Stage-2 first-entry events independently, comparing
TRUE reversal outcomes with FALSE warnings using only features available at T0.
Bucket cut points are learned from the TRAIN block feature distribution WITHOUT
using outcome labels, then frozen and applied unchanged to every OOS block.

Research only. No CE/PE order, entry threshold, or option-P&L signal is emitted.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

DIRECTIONS = {
    "BEARISH": (-1, -1, 1),
    "BULLISH": (1, 1, -1),
}

FEATURES = (
    "fixed_pcr", "moving_pcr", "full_pcr", "fixed_moving_pcr_spread",
    "fixed_pcr_change_1m", "fixed_pcr_change_5m", "fixed_pcr_change_15m", "fixed_pcr_change_30m",
    "moving_pcr_change_1m", "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
    "full_pcr_change_1m", "full_pcr_change_5m", "full_pcr_change_15m", "full_pcr_change_30m",
    "fixed_call_oi_change_pct", "fixed_put_oi_change_pct",
    "moving_call_oi_change_pct", "moving_put_oi_change_pct",
    "full_call_oi_change_pct", "full_put_oi_change_pct", "atm_divergence_points",
)

PRIMARY_BUCKET_FEATURES = (
    "fixed_pcr_change_5m",
    "moving_pcr_change_15m",
    "full_pcr_change_15m",
    "fixed_pcr_change_15m",
    "moving_pcr_change_30m",
    "full_pcr_change_30m",
    "fixed_pcr",
)

class ResearchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class Distribution(ResearchModel):
    count: int
    mean: float | None = None
    median: float | None = None
    q25: float | None = None
    q75: float | None = None

class FeatureComparison(ResearchModel):
    feature: str
    true_reversal: Distribution
    false_warning: Distribution
    median_difference_true_minus_false: float | None = None
    standardized_median_difference: float | None = None
    block_direction_consistency_count: int = 0
    block_available_count: int = 0

class BucketBlockStats(ResearchModel):
    block: str
    event_count: int
    true_reversal_count: int
    false_warning_count: int
    other_count: int
    true_vs_false_rate_pct: float | None = None
    true_reversal_rate_all_pct: float | None = None

class FrozenBucket(ResearchModel):
    bucket: str
    lower_exclusive: float | None = None
    upper_inclusive: float | None = None
    blocks: list[BucketBlockStats]
    combined_oos: BucketBlockStats

class FeatureBuckets(ResearchModel):
    feature: str
    train_cut_points: list[float]
    buckets: list[FrozenBucket]
    combined_oos_true_vs_false_rates: list[float | None]
    monotonic_increasing: bool
    monotonic_decreasing: bool

class DirectionBlockSummary(ResearchModel):
    block: str
    evidence_source: str
    evidence_row_count: int
    stage_2_event_count: int
    true_reversal_count: int
    false_warning_count: int
    other_outcome_counts: dict[str, int]

class DirectionDiscriminator(ResearchModel):
    direction: str
    stage_2_definition: str
    target_true_label: str
    target_false_label: str
    total_stage_2_events: int
    total_true_reversals: int
    total_false_warnings: int
    blocks: list[DirectionBlockSummary]
    features: list[FeatureComparison]
    frozen_train_buckets: list[FeatureBuckets]

class BidirectionalDiscriminatorReport(ResearchModel):
    status: str
    block_count: int
    total_evidence_rows: int
    total_session_count: int
    bearish: DirectionDiscriminator
    bullish: DirectionDiscriminator
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _parse_dt(value: object) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    f = pos - lo
    return ordered[lo] * (1 - f) + ordered[hi] * f


def _distribution(values: list[float]) -> Distribution:
    if not values:
        return Distribution(count=0)
    return Distribution(
        count=len(values), mean=statistics.fmean(values), median=statistics.median(values),
        q25=_quantile(values, .25), q75=_quantile(values, .75),
    )


def _sign(value: object) -> int | None:
    x = _number(value)
    if x is None:
        return None
    return 1 if x > 0 else -1 if x < 0 else 0


def _load(path: str | Path) -> list[dict[str, object]]:
    required = {"session_date", "timestamp", "spot", "forward_change_5m", "forward_change_15m", "forward_change_30m",
                "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m", *FEATURES}
    rows=[]
    with Path(path).open("r", encoding="utf-8", newline="") as h:
        r=csv.DictReader(h)
        missing=required.difference(r.fieldnames or [])
        if missing:
            raise ValueError("historical evidence CSV missing columns: " + ", ".join(sorted(missing)))
        for raw in r:
            row=dict(raw)
            row["dt"]=_parse_dt(raw["timestamp"])
            row["spot"]=_number(raw.get("spot"))
            for k in set(FEATURES) | {"forward_change_5m","forward_change_15m","forward_change_30m"}:
                row[k]=_number(raw.get(k))
            rows.append(row)
    return rows


def _event_rows(rows: list[dict[str, object]], expected: tuple[int,int,int]) -> list[dict[str, object]]:
    grouped=defaultdict(list)
    for row in rows: grouped[str(row["session_date"])].append(row)
    result=[]
    for session in sorted(grouped):
        was=False
        for row in sorted(grouped[session], key=lambda x:x["dt"]):
            state=(_sign(row.get("moving_pcr_change_5m")), _sign(row.get("moving_pcr_change_15m")), _sign(row.get("moving_pcr_change_30m"))) == expected
            if state and not was: result.append(row)
            was=state
    return result


def _exact_change(by_time: dict[datetime,dict[str,object]], dt:datetime, minutes:int)->float|None:
    a=by_time.get(dt); b=by_time.get(dt-timedelta(minutes=minutes))
    if not a or not b: return None
    x=_number(a.get("spot")); y=_number(b.get("spot"))
    return None if x is None or y is None else x-y


def _label(direction:str, prior15:float|None, f5:float|None, f15:float|None, f30:float|None)->str:
    if prior15 is None or f15 is None: return "UNAVAILABLE"
    bullish=direction=="BULLISH"
    prior_opposite = prior15 < 0 if bullish else prior15 > 0
    favorable15 = f15 > 0 if bullish else f15 < 0
    favorable30 = None if f30 is None else (f30 > 0 if bullish else f30 < 0)
    favorable5 = None if f5 is None else (f5 > 0 if bullish else f5 < 0)
    p="BULLISH" if bullish else "BEARISH"
    if prior_opposite:
        if favorable15 and favorable30 is True: return f"TRUE_{p}_REVERSAL"
        if favorable15 and favorable30 is False: return f"{p}_PULLBACK"
        if favorable5 is True and not favorable15: return f"SHORT_{p}_REVERSAL"
        return f"FALSE_{p}_WARNING"
    if favorable15: return f"{p}_CONTINUATION"
    return f"FALSE_{p}_WARNING"


def _events(rows:list[dict[str,object]], direction:str)->list[dict[str,object]]:
    grouped=defaultdict(dict)
    for row in rows: grouped[str(row["session_date"])][row["dt"]]=row
    out=[]
    for row in _event_rows(rows,DIRECTIONS[direction]):
        dt=row["dt"]; session=str(row["session_date"]); lookup=grouped[session]
        prior15=_exact_change(lookup,dt,15)
        f5=_number(row.get("forward_change_5m")); f15=_number(row.get("forward_change_15m")); f30=_number(row.get("forward_change_30m"))
        event={"session_date":session,"event_time":dt.isoformat(),"label":_label(direction,prior15,f5,f15,f30)}
        for feature in FEATURES: event[feature]=_number(row.get(feature))
        out.append(event)
    return out


def _pct(n:int,d:int)->float|None: return n*100.0/d if d else None


def _bucket_index(value:float, cuts:list[float])->int:
    for i,c in enumerate(cuts):
        if value <= c: return i
    return len(cuts)


def _bucket_stats(name:str, events:list[dict[str,object]], true_label:str, false_label:str)->BucketBlockStats:
    t=sum(e["label"]==true_label for e in events); f=sum(e["label"]==false_label for e in events)
    return BucketBlockStats(block=name,event_count=len(events),true_reversal_count=t,false_warning_count=f,
        other_count=len(events)-t-f,true_vs_false_rate_pct=_pct(t,t+f),true_reversal_rate_all_pct=_pct(t,len(events)))


def _feature_buckets(feature:str, per_block:dict[str,list[dict[str,object]]], true_label:str, false_label:str)->FeatureBuckets:
    train=per_block.get("TRAIN",[])
    train_values=[float(e[feature]) for e in train if isinstance(e.get(feature),(int,float))]
    cuts=[x for x in (_quantile(train_values,.25),_quantile(train_values,.50),_quantile(train_values,.75)) if x is not None]
    if len(cuts)!=3:
        return FeatureBuckets(feature=feature,train_cut_points=cuts,buckets=[],combined_oos_true_vs_false_rates=[],monotonic_increasing=False,monotonic_decreasing=False)
    bucket_names=["Q1","Q2","Q3","Q4"]
    buckets=[]; rates=[]
    for idx,bname in enumerate(bucket_names):
        block_stats=[]; combined=[]
        for block,events in per_block.items():
            selected=[e for e in events if isinstance(e.get(feature),(int,float)) and _bucket_index(float(e[feature]),cuts)==idx]
            block_stats.append(_bucket_stats(block,selected,true_label,false_label))
            if block!="TRAIN": combined.extend(selected)
        cstats=_bucket_stats("OOS_COMBINED",combined,true_label,false_label)
        rates.append(cstats.true_vs_false_rate_pct)
        lower=None if idx==0 else cuts[idx-1]; upper=None if idx==3 else cuts[idx]
        buckets.append(FrozenBucket(bucket=bname,lower_exclusive=lower,upper_inclusive=upper,blocks=block_stats,combined_oos=cstats))
    numeric=[x for x in rates if x is not None]
    inc=len(numeric)==4 and all(a<=b for a,b in zip(numeric,numeric[1:]))
    dec=len(numeric)==4 and all(a>=b for a,b in zip(numeric,numeric[1:]))
    return FeatureBuckets(feature=feature,train_cut_points=cuts,buckets=buckets,combined_oos_true_vs_false_rates=rates,monotonic_increasing=inc,monotonic_decreasing=dec)


def _direction(blocks:list[tuple[str,str|Path,list[dict[str,object]]]], direction:str)->DirectionDiscriminator:
    true_label=f"TRUE_{direction}_REVERSAL"; false_label=f"FALSE_{direction}_WARNING"
    per_block={}; summaries=[]
    combined={f:{true_label:[],false_label:[]} for f in FEATURES}; block_diffs=defaultdict(list)
    total_events=total_true=total_false=0
    for name,path,rows in blocks:
        ev=_events(rows,direction); per_block[name]=ev; c=Counter(e["label"] for e in ev)
        t=c[true_label]; f=c[false_label]
        total_events+=len(ev); total_true+=t; total_false+=f
        summaries.append(DirectionBlockSummary(block=name,evidence_source=str(path),evidence_row_count=len(rows),stage_2_event_count=len(ev),true_reversal_count=t,false_warning_count=f,other_outcome_counts=dict(sorted((k,v) for k,v in c.items() if k not in {true_label,false_label}))))
        for feature in FEATURES:
            tv=[float(e[feature]) for e in ev if e["label"]==true_label and isinstance(e.get(feature),(int,float))]
            fv=[float(e[feature]) for e in ev if e["label"]==false_label and isinstance(e.get(feature),(int,float))]
            combined[feature][true_label].extend(tv); combined[feature][false_label].extend(fv)
            if tv and fv: block_diffs[feature].append(statistics.median(tv)-statistics.median(fv))
    features=[]
    for feature in FEATURES:
        tv=combined[feature][true_label]; fv=combined[feature][false_label]
        td=_distribution(tv); fd=_distribution(fv)
        diff=None if td.median is None or fd.median is None else td.median-fd.median
        pooled_iqr=None
        if td.q25 is not None and td.q75 is not None and fd.q25 is not None and fd.q75 is not None:
            pooled_iqr=((td.q75-td.q25)+(fd.q75-fd.q25))/2
        std=None if diff is None or not pooled_iqr else diff/pooled_iqr
        diffs=block_diffs.get(feature,[])
        if diff is None or diff==0: consistency=0
        else: consistency=sum((d>0)==(diff>0) for d in diffs if d!=0)
        features.append(FeatureComparison(feature=feature,true_reversal=td,false_warning=fd,median_difference_true_minus_false=diff,standardized_median_difference=std,block_direction_consistency_count=consistency,block_available_count=len(diffs)))
    features.sort(key=lambda x: abs(x.standardized_median_difference or 0),reverse=True)
    buckets=[_feature_buckets(f,per_block,true_label,false_label) for f in PRIMARY_BUCKET_FEATURES]
    definition="5m and 15m rising; 30m falling" if direction=="BULLISH" else "5m and 15m falling; 30m rising"
    return DirectionDiscriminator(direction=direction,stage_2_definition=definition,target_true_label=true_label,target_false_label=false_label,total_stage_2_events=total_events,total_true_reversals=total_true,total_false_warnings=total_false,blocks=summaries,features=features,frozen_train_buckets=buckets)


def analyze_bidirectional_discriminator(blocks:Iterable[tuple[str,str|Path]])->BidirectionalDiscriminatorReport:
    specs=list(blocks)
    if not specs: raise ValueError("at least one --block is required")
    if specs[0][0] != "TRAIN": raise ValueError("first block must be named TRAIN so bucket cut points are frozen from TRAIN")
    if len({n for n,_ in specs})!=len(specs): raise ValueError("block names must be unique")
    loaded=[]
    for name,path in specs:
        rows=_load(path)
        if not rows: raise ValueError(f"evidence block has no rows: {path}")
        loaded.append((name,path,rows))
    return BidirectionalDiscriminatorReport(status="AVAILABLE",block_count=len(loaded),total_evidence_rows=sum(len(r) for _,_,r in loaded),total_session_count=sum(len({str(x['session_date']) for x in r}) for _,_,r in loaded),
        bearish=_direction(loaded,"BEARISH"),bullish=_direction(loaded,"BULLISH"),
        methodology=[
            "Bullish and bearish Stage-2 definitions remain frozen and are evaluated independently.",
            "Only first-entry Stage-2 events are counted; persistent minute states are not repeated events.",
            "TRUE reversal and FALSE warning labels use the same transparent price rules as the bidirectional reversal study.",
            "Feature comparisons use only T0 evidence available when the Stage-2 event occurred.",
            "For bucket research, Q1/Q2/Q3/Q4 cut points are computed from the TRAIN block feature distribution without outcome labels, then frozen and applied unchanged to OOS-A/B/C/D.",
            "Bucket success rate is TRUE_REVERSAL / (TRUE_REVERSAL + FALSE_WARNING); other response types are reported separately and not silently treated as failures.",
            "This is research output only and does not create CE/PE BUY thresholds.",
        ],
        limitations=[
            "The discriminator feature shortlist was motivated by the existing 100-session research, so the current 100 sessions are not a pristine feature-selection OOS set. A future untouched block is required before promotion.",
            "Current evidence still lacks per-strike option premium plus OI positioning and underlying-volume timing.",
            "Monotonic bucket behavior is descriptive and should not be converted directly into a trading threshold without fresh OOS validation.",
        ])


def write_bidirectional_discriminator_json(report:BidirectionalDiscriminatorReport,path:str|Path)->None:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(report.model_dump(mode="json"),indent=2)+"\n",encoding="utf-8")
