"""Isolated historical research policy. No live adapters or broker operations."""
from __future__ import annotations
import os
import copy, json, hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, date, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from ..domain import IST
from .hilega_opening_reference_v1 import capture_opening_reference, confirmation_reference
from .hilega_directional_coordinator_v1 import (HilegaDirectionalCoordinatorV1, DirectionalDecision,
 BULLISH_ENTRY_EVENTS,BEARISH_ENTRY_EVENTS,BULLISH_EXIT_EVENTS,BEARISH_EXIT_EVENTS)
from .hilega_milega_strategy_v1 import SessionState,StrategyEvent
from .hilega_milega_bearish_strategy_v1 import BearishSessionState
from .session import aggregate_exact_3m as aggregate_exact_3m
STRATEGY_ID = 'HILEGA_WMA_GAP_V2_LIVE_SHADOW'
ENTRY_TYPES = BULLISH_ENTRY_EVENTS | BEARISH_ENTRY_EVENTS
EXIT_TYPES = BULLISH_EXIT_EVENTS | BEARISH_EXIT_EVENTS

def direction(event):
    return 'BEARISH' if event.event_type in BEARISH_ENTRY_EVENTS | BEARISH_EXIT_EVENTS else 'BULLISH'

class ExitFirstCanonical(HilegaDirectionalCoordinatorV1):
    """Only V2's canonical setup stream allows exit-boundary reversals."""
    def _coordinate(self, *, bar, bullish_events, bearish_events):
        old = self.trade_owner
        opposite = 'BEARISH' if old == 'BULLISH' else 'BULLISH'
        engine = self.bearish if opposite == 'BEARISH' else self.bullish
        saved = deepcopy(engine.session)
        new_entries = self._entry_events(bearish_events if opposite == 'BEARISH' else bullish_events, opposite)
        exiting = self._exit_events(bullish_events if old == 'BULLISH' else bearish_events, old)
        decision = super()._coordinate(bar=bar, bullish_events=bullish_events, bearish_events=bearish_events)
        if old != 'NONE' and exiting and new_entries and bar.ts.time() < time(15,27):
            engine.session = saved
            self.trade_owner = opposite
            accepted = tuple(e for e in decision.accepted_events if e.event_type in EXIT_TYPES) + tuple(new_entries) + tuple(e for e in decision.accepted_events if e.event_type not in EXIT_TYPES)
            decision = replace(decision, trade_owner_after=opposite, accepted_events=accepted,
                suppressed_events=tuple(e for e in decision.suppressed_events if e not in new_entries),
                bullish_state=self.bullish.session.name, bearish_state=self.bearish.session.name,
                bullish_armed=self.bullish.session.armed, bearish_armed=self.bearish.session.armed,
                note='EXIT_FIRST; SAME_CANDLE_CANONICAL_SETUP_ALLOWED')
        return decision

class WmaGapGate:
    """Pure deterministic gate shared by live processing and offline tests."""
    def __init__(self, opposite_switch=None):
        self.owner='NONE'; self.active=None; self.pending={}; self.previous=None; self.locked=False
        self.opposite_switch = os.getenv('HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED','0')=='1' if opposite_switch is None else opposite_switch
        self.watch_side=None; self.watch_at=None; self.switches=[]
    def _switch(self, side, available, reason):
        opposite='BEARISH' if side=='BULLISH' else 'BULLISH'
        old=self.pending.pop(opposite,None)
        if old or self.watch_side==opposite:
            self.switches.append(dict(time=available.isoformat(),from_direction=opposite,to_direction=side,reason=reason,cancelled_signal_available_at=old['available'].isoformat() if old else None,confirmation_reset=True))
        self.watch_side=side;self.watch_at=available
    def observe_arms(self, events, available):
        if not self.opposite_switch or self.owner!='NONE' or self.locked:return
        # Confirmed setups on the same boundary outrank an unconfirmed arm.
        if any(e.event_type in ENTRY_TYPES for e in events):return
        arms={'PATH1_ARMED_RSI_CROSS_EMA3_UP':'BULLISH','BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN':'BEARISH'}
        sides={arms[e.event_type] for e in events if e.event_type in arms}
        if len(sides)==1:
            side=next(iter(sides));opposite='BEARISH' if side=='BULLISH' else 'BULLISH'
            if opposite in self.pending or self.watch_side==opposite:self._switch(side,available,'OPPOSITE_CANONICAL_ARM')
    def can_signal(self, side, available):
        if not self.opposite_switch:return True
        if self.watch_at is not None and available-self.watch_at>=timedelta(minutes=10):self.watch_side=None;self.watch_at=None
        return self.watch_side in (None,side)
    def take_switches(self):
        result=self.switches;self.switches=[];return result
    def signal(self, event, available):
        side=direction(event)
        if self.opposite_switch:
            if self.owner!='NONE' or self.locked:return
            self._switch(side,available,'OPPOSITE_CONFIRMED_SETUP')
        self.pending[side]={'event':event, 'available':available, 'armed_at':None}
    def close(self, event, at, price):
        side=direction(event)
        self.pending.pop(side,None)
        if self.owner!=side:return None
        active=self.active
        result=replace(event,event_time=at,price=price,entry_time=active['time'],entry_price=active['price'],
                       points=(price-active['price'])*(1 if side=='BULLISH' else -1))
        self.owner='NONE'; self.active=None;self.watch_side=None;self.watch_at=None
        return result
    def evaluate(self, *, minute, current, reference, price, exit_boundary=False):
        accepted=[]; checks=[]
        self.can_signal('BULLISH',minute+timedelta(minutes=1))
        for side,p in list(self.pending.items()):
            sign=1 if side=='BULLISH' else -1
            previous=self.previous
            gap=sign*(current.ema3_rsi-current.wma21_rsi) if current.ready else None
            prev_gap=sign*(previous['snapshot'].ema3_rsi-previous['snapshot'].wma21_rsi) if previous and previous['snapshot'].ready else None
            strength=sign*(current.wma21_rsi-reference.wma21_rsi) if current.ready and reference and reference.ready else None
            previous_strength=sign*previous['wma_change'] if previous and previous['wma_change'] is not None else None
            age=(minute-p['available']).total_seconds()/60
            consecutive=previous is not None and previous['minute']==minute-timedelta(minutes=1)
            same_boundary=exit_boundary and age == -1
            elapsed=0<=age<10 or same_boundary
            threshold=strength is not None and strength>=.75
            was_armed=p['armed_at'] is not None and minute>p['armed_at']
            persistence=(was_armed or same_boundary) and consecutive and previous_strength is not None and previous_strength>=.75 and threshold
            expansion=gap is not None and prev_gap is not None and consecutive and gap>prev_gap
            reasons=[]
            if self.locked or (minute+timedelta(minutes=1)).time()>=time(15,30):reasons.append('SESSION_CUTOFF')
            if age<0 and not same_boundary:reasons.append('WAIT_FIRST_POST_SIGNAL_MINUTE')
            elif not elapsed:reasons.append('WINDOW_EXPIRED')
            if not threshold:reasons.append('WMA_THRESHOLD_NOT_MET')
            if not persistence:reasons.append('WAIT_LATER_PERSISTENCE')
            if gap is None or gap<=0:reasons.append('GAP_NOT_POSITIVE')
            if not expansion:reasons.append('GAP_NOT_EXPANDING_OR_PREVIOUS_MINUTE_MISSING')
            if self.owner!='NONE':reasons.append('ACTIVE_TRADE_OWNER')
            check={'direction':side,'signal_timestamp':p['event'].event_time.isoformat(),
                   'signal_available_at':p['available'].isoformat(),'minute_timestamp':minute.isoformat(),
                   'decision_timestamp':(minute+timedelta(minutes=1)).isoformat(),
                   'previous_timestamp':previous['minute'].isoformat() if previous else None,
                   'previous_rsi9':previous['snapshot'].rsi9 if previous else None,
                   'previous_ema3':previous['snapshot'].ema3_rsi if previous else None,
                   'previous_wma21':previous['snapshot'].wma21_rsi if previous else None,
                   'current_rsi9':current.rsi9,'current_ema3':current.ema3_rsi,'current_wma21':current.wma21_rsi,
                   'previous_gap':prev_gap,'current_gap':gap,'gap_delta':gap-prev_gap if gap is not None and prev_gap is not None else None,
                   'directional_wma_strength':strength,'previous_directional_wma_strength':previous_strength,
                   'wma_threshold_pass':threshold,'persistence_pass':persistence,'gap_positive_pass':gap is not None and gap>0,
                   'gap_expanding_pass':expansion,'confirmation_window_pass':elapsed,
                   'ema3_continuation_delta':sign*(current.ema3_rsi-previous['snapshot'].ema3_rsi) if current.ready and previous and previous['snapshot'].ready else None,
                   'directional_alignment_diagnostic':(sign*(current.rsi9-current.ema3_rsi)>0 and sign*(current.ema3_rsi-current.wma21_rsi)>0) if current.ready else None,
                   'same_exit_boundary_confirmation':same_boundary,
                   'armed_at':p['armed_at'].isoformat() if p['armed_at'] else None,
                   'status':'ENTRY' if not reasons else 'WAIT','reasons':reasons}
            checks.append(check)
            if elapsed and threshold and p['armed_at'] is None:p['armed_at']=minute
            if not reasons:
                at=minute+timedelta(minutes=1)
                accepted.append(replace(p['event'],event_time=at,price=price,entry_time=at,entry_price=price,
                    state_before='WMA_GAP_ARMED',state_after=side+'_ACTIVE',details={'wma_gap':check,'canonical_signal':p['event'].details}))
                self.owner=side;self.active={'time':at,'price':price};del self.pending[side];self.watch_side=None;self.watch_at=None
            elif age>=10 or self.locked:del self.pending[side]
        change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None
        self.previous={'minute':minute,'snapshot':current,'wma_change':change}
        return accepted,checks


def decision_checkpoint(*, boundary, checks, entries, exits):
    """Three-minute monitoring, with minute evidence only for pending confirmation/transitions."""
    return bool(boundary or checks or entries or exits)

MODEL='HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1'
SOURCE='V2_ALIGNMENT_DUAL_EXIT_RESEARCH'
OUTPUT_ROOT=Path('data/historical-evidence/hilega-v2-alignment-dual-exit-v1')
RULES={"version":"three-minute-setup-1.1.0","setup":"Three-minute boundary only: V1 OR completed-5m RSI9/EMA3/WMA21 ordering + positive expanding minute gap", "strength_min":0.75,"expansion_min_exclusive":0.0,"persistence":"previous/current >=0.75; later arm confirmation", "window_minutes":10,"exit":"both RSI9 and EMA3 opposite WMA21 at completed 5m close", "cutoff_IST":"15:30", "same_candle_exit_first":True,"ema10_enabled":False,"mandatory_5m_slope":False,"alternative_50_filter":False,"signal_episode":"one alternative per continuous alignment episode; no minute window reset", "setup_interval_minutes":5,"confirmation_interval_minutes":1,"active_decision_interval_minutes":5}
def candles(rows):
 result=[];seen=set()
 for row in rows:
  stamp=datetime.fromisoformat(row['timestamp'])
  if stamp.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
  stamp=stamp.astimezone(IST)
  if stamp in seen:raise ValueError('DUPLICATE_MINUTE')
  seen.add(stamp)
  values={k:float(row[k]) for k in ('open','high','low','close')}
  if values['high']<max(values['open'],values['close'],values['low']) or values['low']>min(values['open'],values['close']):raise ValueError('INVALID_OHLC')
  result.append(SimpleNamespace(**{**row,**values,'timestamp':stamp}))
 return sorted(result,key=lambda x:x.timestamp)
def dual_exit(side,snapshot):
 sign=1 if side=='BULLISH' else -1
 return snapshot.ready and sign*(snapshot.rsi9-snapshot.wma21_rsi)<0 and sign*(snapshot.ema3_rsi-snapshot.wma21_rsi)<0

from ..hilega_v2_alignment_replay_v1 import cache_index, CACHE_ROOTS, ReplayBusyError
