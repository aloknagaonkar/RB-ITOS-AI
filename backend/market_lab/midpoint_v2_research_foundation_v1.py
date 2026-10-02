from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Literal, Sequence

RESEARCH_VERSION = "MIDPOINT_V2_RESEARCH_FOUNDATION_V1"
BASELINE_ENTRY_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
BASELINE_EXIT_POLICY = "SL5_BE5_TRAIL3_AFTER10_TIME15"
Direction = Literal["BULLISH", "BEARISH"]
ALLOWED_DEVELOPMENT_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_RULE_DISCOVERY_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}
STATE_V1_CONTINUATION = "CONFIRM_CONTINUATION"
STATE_WAIT_BASE = "WAIT_BASE"
STATE_RECLAIM_WATCH = "RECLAIM_WATCH"
STATE_CANCEL = "CANCEL_BREAKOUT"
ARM_IMMEDIATE = "IMMEDIATE_CONTINUATION"
ARM_BASE = "BASE_THEN_GO"
ARM_RECLAIM = "FAILED_BREAK_RECLAIM"

@dataclass(frozen=True)
class V2WatchConfig:
    max_base_watch_bars: int = 8
    min_base_bars: int = 2
    max_reclaim_watch_bars: int = 8
    min_reversal_hold_bars: int = 2
    def validate(self) -> None:
        if self.max_base_watch_bars < 2: raise ValueError("max_base_watch_bars must be >= 2")
        if self.min_base_bars < 2: raise ValueError("min_base_bars must be >= 2")
        if self.min_base_bars > self.max_base_watch_bars: raise ValueError("min_base_bars cannot exceed max_base_watch_bars")
        if self.max_reclaim_watch_bars < 2: raise ValueError("max_reclaim_watch_bars must be >= 2")
        if self.min_reversal_hold_bars < 1: raise ValueError("min_reversal_hold_bars must be >= 1")

def assert_development_only(blocks: Iterable[str]) -> None:
    blocks={str(x) for x in blocks}
    forbidden=blocks & FORBIDDEN_RULE_DISCOVERY_BLOCKS
    if forbidden: raise ValueError("V2 rule discovery must not use consumed/forbidden OOS blocks: "+", ".join(sorted(forbidden)))
    unknown=blocks-ALLOWED_DEVELOPMENT_BLOCKS
    if unknown: raise ValueError("Unknown development blocks: "+", ".join(sorted(unknown)))

def opposite_direction(direction: Direction) -> Direction:
    return "BEARISH" if direction=="BULLISH" else "BULLISH"

def boundary_reclaimed(close: float, boundary: float, direction: Direction) -> bool:
    return close <= boundary if direction=="BULLISH" else close >= boundary

def midpoint_reclaimed(close: float, midpoint: float, direction: Direction) -> bool:
    return close <= midpoint if direction=="BULLISH" else close >= midpoint

def same_direction_break(close: float, base_extreme: float, direction: Direction) -> bool:
    return close > base_extreme if direction=="BULLISH" else close < base_extreme

def reversal_progress(close: float, midpoint: float, original_direction: Direction) -> bool:
    return close < midpoint if original_direction=="BULLISH" else close > midpoint

@dataclass(frozen=True)
class TransitionResult:
    source_t3_state: str
    final_state: str
    entry_arm: str|None
    entry_direction: Direction|None
    confirmation_bar_index: int|None
    reason: str
    observed_bars: int
    boundary: float
    midpoint: float
    def to_dict(self)->dict: return asdict(self)

def evaluate_wait_base(*, direction:Direction, boundary:float, midpoint:float, closes_after_t3:Sequence[float], config:V2WatchConfig|None=None)->TransitionResult:
    config=config or V2WatchConfig(); config.validate(); observed=[]
    limit=min(len(closes_after_t3), config.max_base_watch_bars)
    for i in range(limit):
        close=float(closes_after_t3[i])
        if midpoint_reclaimed(close, midpoint, direction):
            return TransitionResult(STATE_WAIT_BASE,STATE_RECLAIM_WATCH,None,None,i,"REFERENCE_MIDPOINT_RECLAIMED_DURING_BASE_WATCH",i+1,boundary,midpoint)
        if boundary_reclaimed(close,boundary,direction):
            return TransitionResult(STATE_WAIT_BASE,STATE_RECLAIM_WATCH,None,None,i,"BOUNDARY_RECLAIMED_DURING_BASE_WATCH",i+1,boundary,midpoint)
        if len(observed)>=config.min_base_bars:
            base_extreme=max(observed) if direction=="BULLISH" else min(observed)
            if same_direction_break(close,base_extreme,direction):
                return TransitionResult(STATE_WAIT_BASE,"CONFIRM_BASE_THEN_GO",ARM_BASE,direction,i,"CONTROLLED_BASE_HELD_AND_SAME_DIRECTION_EXPANSION_CONFIRMED",i+1,boundary,midpoint)
        observed.append(close)
    return TransitionResult(STATE_WAIT_BASE,"BASE_WATCH_EXPIRED",None,None,None,"NO_VALID_BASE_EXPANSION_WITHIN_RESEARCH_WATCH_WINDOW",limit,boundary,midpoint)

def evaluate_reclaim_watch(*, original_direction:Direction, boundary:float, midpoint:float, closes_after_t3:Sequence[float], config:V2WatchConfig|None=None)->TransitionResult:
    config=config or V2WatchConfig(); config.validate(); midpoint_seen_at=None; opposite_hold_count=0
    limit=min(len(closes_after_t3),config.max_reclaim_watch_bars)
    for i in range(limit):
        close=float(closes_after_t3[i])
        if midpoint_seen_at is None:
            if midpoint_reclaimed(close,midpoint,original_direction): midpoint_seen_at=i; opposite_hold_count=1
            continue
        if reversal_progress(close,midpoint,original_direction):
            opposite_hold_count += 1
            if opposite_hold_count >= config.min_reversal_hold_bars:
                new_direction=opposite_direction(original_direction)
                return TransitionResult(STATE_RECLAIM_WATCH,"CONFIRM_FAILED_BREAK_RECLAIM",ARM_RECLAIM,new_direction,i,"MIDPOINT_RECLAIMED_AND_OPPOSITE_DIRECTION_ACCEPTANCE_CONFIRMED",i+1,boundary,midpoint)
        else:
            opposite_hold_count=0; midpoint_seen_at=None
    return TransitionResult(STATE_RECLAIM_WATCH,"RECLAIM_WATCH_EXPIRED",None,None,None,"NO_CONFIRMED_OPPOSITE_DIRECTION_ACCEPTANCE",limit,boundary,midpoint)

def route_v2_extension(*, t3_state:str, direction:Direction, boundary:float, midpoint:float, closes_after_t3:Sequence[float], config:V2WatchConfig|None=None)->TransitionResult:
    if t3_state==STATE_V1_CONTINUATION:
        return TransitionResult(t3_state,STATE_V1_CONTINUATION,ARM_IMMEDIATE,direction,0,"V1_CONTINUATION_PATH_UNCHANGED",0,boundary,midpoint)
    if t3_state==STATE_WAIT_BASE:
        return evaluate_wait_base(direction=direction,boundary=boundary,midpoint=midpoint,closes_after_t3=closes_after_t3,config=config)
    if t3_state==STATE_RECLAIM_WATCH:
        return evaluate_reclaim_watch(original_direction=direction,boundary=boundary,midpoint=midpoint,closes_after_t3=closes_after_t3,config=config)
    return TransitionResult(t3_state,STATE_CANCEL,None,None,None,"T3_STATE_TERMINAL_OR_NOT_ELIGIBLE_FOR_V2_EXTENSION",0,boundary,midpoint)
