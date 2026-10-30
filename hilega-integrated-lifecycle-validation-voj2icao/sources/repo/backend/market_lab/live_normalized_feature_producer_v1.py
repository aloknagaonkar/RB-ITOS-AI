from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Literal

from .domain import IST, Snapshot
from .live_observational_data_health_v1 import evaluate_snapshot_health, strategy_dependency_gate

MODEL = "LIVE_NORMALIZED_FEATURE_PRODUCER_V1_1"
HORIZONS_MINUTES = (5, 10, 15)
All3State = Literal["BULLISH_ALL_3", "BEARISH_ALL_3", "MIXED", "INCOMPLETE"]

@dataclass(frozen=True)
class HorizonFeature:
    horizon_minutes: int
    current_ce_oi: float | None
    current_pe_oi: float | None
    prior_ce_oi: float | None
    prior_pe_oi: float | None
    ce_delta: float | None
    pe_delta: float | None
    imbalance: float | None
    prior_pcr: float | None
    current_pcr: float | None
    pcr_change: float | None
    state: str

@dataclass(frozen=True)
class CheckpointSnapshot:
    checkpoint_timestamp: datetime
    snapshot: Snapshot

@dataclass(frozen=True)
class LiveNormalizedCheckpoint:
    model: str
    session_date: str
    timestamp: datetime
    source_received_at: datetime
    source_delay_ms: float
    spot: float
    moving_atm: float
    strike_interval: float
    moving_strikes: tuple[float, ...]
    state_5m: str
    state_10m: str
    state_15m: str
    all3_state: All3State
    previous_directional_all3: str | None
    ce_instrument_key: str | None
    pe_instrument_key: str | None
    health_state: str
    health_allowed: bool
    health_reason: str | None
    features: tuple[HorizonFeature, ...]

def _round_atm(spot: float, strike_interval: float) -> float:
    return round(spot / strike_interval) * strike_interval

def _infer_strike_interval(snapshot: Snapshot) -> float:
    strikes = sorted({float(c.strike) for c in snapshot.catalog})
    diffs = sorted({round(b-a, 10) for a,b in zip(strikes,strikes[1:]) if b>a})
    if not diffs: raise ValueError("Cannot infer strike interval from snapshot catalog")
    return diffs[0]

def _quote_index(snapshot: Snapshot):
    contracts={c.key:c for c in snapshot.catalog}; quotes={q.key:q for q in snapshot.quotes}
    return {(float(c.strike),c.side):quotes.get(key) for key,c in contracts.items()}

def _sum_side(snapshot: Snapshot, strikes: Iterable[float], side: str) -> float | None:
    idx=_quote_index(snapshot); total=0.0
    for strike in strikes:
        q=idx.get((float(strike),side))
        if q is None or q.oi is None: return None
        total+=float(q.oi)
    return total

def _pcr(pe,ce):
    if pe is None or ce in (None,0): return None
    return pe/ce

def _state(imbalance,pcr_change):
    if imbalance is None or pcr_change is None: return "NA"
    if imbalance>0 and pcr_change>0:return "BULLISH"
    if imbalance<0 and pcr_change<0:return "BEARISH"
    return "MIXED"

def _all3(states):
    if "NA" in states:return "INCOMPLETE"
    if all(x=="BULLISH" for x in states):return "BULLISH_ALL_3"
    if all(x=="BEARISH" for x in states):return "BEARISH_ALL_3"
    return "MIXED"

def _atm_keys(snapshot,atm):
    ce=[c.key for c in snapshot.catalog if float(c.strike)==atm and c.side=="CE"]
    pe=[c.key for c in snapshot.catalog if float(c.strike)==atm and c.side=="PE"]
    if len(ce)>1 or len(pe)>1: raise ValueError("Ambiguous exact ATM contract")
    return (ce[0] if ce else None,pe[0] if pe else None)

class LiveNormalizedFeatureProducerV1:
    def __init__(self,wings:int=5):
        if wings!=5: raise ValueError("V1 is frozen to moving ATM +/-5")
        self.wings=wings; self.history:list[CheckpointSnapshot]=[]; self.last_directional_all3=None

    def add_snapshot(self,snapshot:Snapshot,checkpoint_timestamp:datetime|None=None)->None:
        checkpoint_timestamp=checkpoint_timestamp or snapshot.received_at
        if checkpoint_timestamp.tzinfo is None: raise ValueError("checkpoint_timestamp must be timezone-aware")
        if self.history and checkpoint_timestamp<=self.history[-1].checkpoint_timestamp: raise ValueError("Out-of-order or duplicate checkpoint")
        if snapshot.received_at<checkpoint_timestamp: raise ValueError("Snapshot cannot be received before its checkpoint")
        self.history.append(CheckpointSnapshot(checkpoint_timestamp,snapshot))

    def _exact(self,target):
        rows=[x.snapshot for x in self.history if x.checkpoint_timestamp==target]
        if len(rows)>1: raise ValueError("Duplicate checkpoint")
        return rows[0] if rows else None

    def build_current(self)->LiveNormalizedCheckpoint:
        if not self.history: raise ValueError("No snapshots available")
        entry=self.history[-1]; current=entry.snapshot; checkpoint=entry.checkpoint_timestamp
        health=evaluate_snapshot_health(current); allowed,reason=strategy_dependency_gate(health,dependency="ALL3")
        delay_ms=(current.received_at-checkpoint).total_seconds()*1000.0
        interval=_infer_strike_interval(current); atm=_round_atm(current.spot,interval)
        strikes=tuple(atm+i*interval for i in range(-self.wings,self.wings+1))
        if any(s not in {float(c.strike) for c in current.catalog} for s in strikes):
            allowed=False; reason="DATA_HEALTH_ALL3_MISSING_CURRENT_STRIKE_BASKET"
        current_ce=_sum_side(current,strikes,"CE"); current_pe=_sum_side(current,strikes,"PE"); features=[]
        for minutes in HORIZONS_MINUTES:
            prior=self._exact(checkpoint-timedelta(minutes=minutes))
            prior_ce=_sum_side(prior,strikes,"CE") if prior else None; prior_pe=_sum_side(prior,strikes,"PE") if prior else None
            ce_delta=current_ce-prior_ce if current_ce is not None and prior_ce is not None else None
            pe_delta=current_pe-prior_pe if current_pe is not None and prior_pe is not None else None
            imbalance=pe_delta-ce_delta if pe_delta is not None and ce_delta is not None else None
            prior_pcr=_pcr(prior_pe,prior_ce); current_pcr=_pcr(current_pe,current_ce)
            pcr_change=current_pcr-prior_pcr if current_pcr is not None and prior_pcr is not None else None
            features.append(HorizonFeature(minutes,current_ce,current_pe,prior_ce,prior_pe,ce_delta,pe_delta,imbalance,prior_pcr,current_pcr,pcr_change,_state(imbalance,pcr_change)))
        all3=_all3(tuple(f.state for f in features)); previous=self.last_directional_all3
        if all3 in {"BULLISH_ALL_3","BEARISH_ALL_3"}: self.last_directional_all3=all3
        ce_key,pe_key=_atm_keys(current,atm)
        if not allowed: all3="INCOMPLETE"
        return LiveNormalizedCheckpoint(MODEL,checkpoint.astimezone(IST).date().isoformat(),checkpoint,current.received_at,delay_ms,float(current.spot),atm,interval,strikes,features[0].state,features[1].state,features[2].state,all3,previous,ce_key,pe_key,health.state,allowed,reason,tuple(features))
