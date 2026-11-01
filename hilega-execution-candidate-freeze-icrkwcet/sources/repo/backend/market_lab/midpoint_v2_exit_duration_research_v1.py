from __future__ import annotations
from dataclasses import dataclass, asdict
from math import isfinite
from typing import Sequence

RESEARCH_VERSION="MIDPOINT_V2_EXIT_DURATION_RESEARCH_V1"
ROUND_TRIP_COST_PCT_POINTS=0.5
POLICY_E15="E15_V1_BASELINE"; POLICY_E20="E20"; POLICY_E30="E30"
POLICY_HYBRID="HYBRID_TIME15_UNLESS_TRAIL_ACTIVE"
POLICY_TRAIL_ONLY="TRAIL_ONLY_AFTER_ACTIVATION_WITH_SAFETY_CAP"
POLICIES={POLICY_E15,POLICY_E20,POLICY_E30,POLICY_HYBRID,POLICY_TRAIL_ONLY}

@dataclass(frozen=True)
class ExitConfig:
    initial_stop_pct:float=5.0; breakeven_trigger_pct:float=5.0; trail_activation_pct:float=10.0; trail_distance_pct:float=3.0; safety_cap_minutes:int=60
    def validate(self):
        if self.initial_stop_pct<=0: raise ValueError("initial_stop_pct must be > 0")
        if self.breakeven_trigger_pct<=0: raise ValueError("breakeven_trigger_pct must be > 0")
        if self.trail_activation_pct<=self.breakeven_trigger_pct: raise ValueError("trail activation must exceed breakeven trigger")
        if not (0<self.trail_distance_pct<100): raise ValueError("trail_distance_pct must be between 0 and 100")
        if self.safety_cap_minutes<30: raise ValueError("safety_cap_minutes must be >= 30")
@dataclass(frozen=True)
class Bar:
    minute:int; open:float; high:float; low:float; close:float
@dataclass(frozen=True)
class ExitResult:
    policy_id:str; exit_minute:int; exit_price:float; exit_reason:str; gross_return_pct:float; net_return_pct:float; best_high_before_exit:float; mfe_pct:float; capture_ratio_pct:float|None; trail_was_active:bool
    def to_dict(self): return asdict(self)

def _time_limit(p):
    return {POLICY_E15:15,POLICY_E20:20,POLICY_E30:30,POLICY_HYBRID:None,POLICY_TRAIL_ONLY:None}[p]
def _gross(entry,px): return (px/entry-1.0)*100.0
def _cap(g,m): return None if m<=0 else g/m*100.0

def replay(*,entry_price:float,bars:Sequence[Bar],policy_id:str,config:ExitConfig|None=None)->ExitResult:
    if policy_id not in POLICIES: raise ValueError(f"unsupported policy_id={policy_id}")
    if entry_price<=0 or not isfinite(entry_price): raise ValueError("entry_price must be positive and finite")
    config=config or ExitConfig(); config.validate()
    if not bars: raise ValueError("bars required")
    active_stop=entry_price*(1-config.initial_stop_pct/100); pending_stop=None; best_high=entry_price; trail_ever=False; limit=_time_limit(policy_id)
    for bar in bars:
        minute=int(bar.minute)
        if pending_stop is not None: active_stop=max(active_stop,pending_stop); pending_stop=None
        if bar.open<active_stop:
            px=bar.open; g=_gross(entry_price,px); mfe=_gross(entry_price,best_high)
            return ExitResult(policy_id,minute,px,"STOP_GAP",g,g-ROUND_TRIP_COST_PCT_POINTS,best_high,mfe,_cap(g,mfe),trail_ever)
        if bar.low<=active_stop:
            px=active_stop; g=_gross(entry_price,px); mfe=_gross(entry_price,best_high)
            return ExitResult(policy_id,minute,px,"STOP_TOUCH",g,g-ROUND_TRIP_COST_PCT_POINTS,best_high,mfe,_cap(g,mfe),trail_ever)
        best_high=max(best_high,bar.high); gain=_gross(entry_price,best_high); next_stop=active_stop
        if gain>=config.breakeven_trigger_pct: next_stop=max(next_stop,entry_price)
        if gain>=config.trail_activation_pct:
            trail_ever=True; next_stop=max(next_stop,best_high*(1-config.trail_distance_pct/100))
        if next_stop>active_stop: pending_stop=next_stop
        if limit is not None and minute>=limit:
            px=bar.close; g=_gross(entry_price,px); mfe=_gross(entry_price,best_high)
            return ExitResult(policy_id,minute,px,"TIME_EXIT",g,g-ROUND_TRIP_COST_PCT_POINTS,best_high,mfe,_cap(g,mfe),trail_ever)
        if policy_id==POLICY_HYBRID and minute>=15 and not trail_ever:
            px=bar.close; g=_gross(entry_price,px); mfe=_gross(entry_price,best_high)
            return ExitResult(policy_id,minute,px,"TIME15_NO_TRAIL_EXIT",g,g-ROUND_TRIP_COST_PCT_POINTS,best_high,mfe,_cap(g,mfe),trail_ever)
        if minute>=config.safety_cap_minutes:
            px=bar.close; g=_gross(entry_price,px); mfe=_gross(entry_price,best_high)
            return ExitResult(policy_id,minute,px,"SAFETY_CAP_EXIT",g,g-ROUND_TRIP_COST_PCT_POINTS,best_high,mfe,_cap(g,mfe),trail_ever)
    bar=bars[-1]; px=bar.close; g=_gross(entry_price,px); mfe=_gross(entry_price,best_high)
    return ExitResult(policy_id,int(bar.minute),px,"DATA_END_EXIT",g,g-ROUND_TRIP_COST_PCT_POINTS,best_high,mfe,_cap(g,mfe),trail_ever)

def compare_policies(*,entry_price:float,bars:Sequence[Bar],config:ExitConfig|None=None)->dict:
    return {p:replay(entry_price=entry_price,bars=bars,policy_id=p,config=config).to_dict() for p in (POLICY_E15,POLICY_HYBRID,POLICY_E20,POLICY_E30,POLICY_TRAIL_ONLY)}
