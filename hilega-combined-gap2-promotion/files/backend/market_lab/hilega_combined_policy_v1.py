"""Shared BULLISH_GAP2_FULL_WMA2 policy. Frozen from the validated research gate; no broker access.
Legacy routing strategy ID is retained; policy identity and version are explicit.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,time
import math
from .hilega_v2_alignment_replay_v1 import WmaGapGate, direction, ENTRY_TYPES, EXIT_TYPES, dual_exit

POLICY_ID="BULLISH_GAP2_FULL_WMA2"
VERSION="bullish-gap2-full-wma2-1.0.0"
RULES=dict(version=VERSION,policy_id=POLICY_ID,setup="Completed5m canonical or fresh alignment; strength>=0.75; positive expanding5m gap; price EMA10 slope/side; directional RSI40/60 and candle colour",confirmation_interval_minutes=5,persistence_required=False,window_minutes=None,bullish_signal_gap_min=2,bullish_full_wma_min=2,ema10_enabled=True,wma_direction_lock=False,followup="Directional colour/RSI AND (signal close OR midpoint OR fresh strength/gap)",failed_followup="Retain original reference only on EMA10 touch; else fresh signal",exit="Both RSI9 and EMA3 of RSI opposite WMA21",cutoff_IST="14:55",same_candle_exit_first=True)


def rsi_cross(side,previous,current):
    if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    for value in (previous,current):
        if isinstance(value,bool) or value is None or not math.isfinite(float(value)) or not 0<=float(value)<=100:
            return dict(rsi_cross_pass=False,rsi_crossed_thresholds=[],rsi_evidence_available=False)
    previous,current=float(previous),float(current)
    thresholds=[v for v in (45,55) if (previous<=v<current if side=='BULLISH' else current<v<=previous)]
    return dict(rsi_cross_pass=bool(thresholds),rsi_crossed_thresholds=thresholds,rsi_evidence_available=True)


def frame_check(side, frame, at, rule='FULL_CANDLE'):
    if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    if rule not in ('FULL_CANDLE','BULLISH_CLOSE','CLOSE_BOTH','CLOSE_AND_RSI_CROSS','CLOSE_RSI_SLOPE_COLOUR','CLOSE_RSI_CONTINUATION_SLOPE_COLOUR','CLOSE_RSI40_60_SLOPE_COLOUR'):raise ValueError('INVALID_EMA_ENTRY_RULE')
    if frame is None:return dict(passed=False,reasons=['COMPLETED_5M_FRAME_MISSING'])
    available=datetime.fromisoformat(frame['available_at'])
    if available>at:raise ValueError('FUTURE_EMA_FRAME')
    if at-available>=timedelta(minutes=5):raise ValueError('STALE_EMA_FRAME')
    fields=('open','high','low','close','ema10','previous_ema10')
    for k in fields:
        v=frame[k]
        if isinstance(v,bool) or v is None or not math.isfinite(float(v)) or float(v)<=0:
            raise ValueError('INVALID_EMA_FRAME:'+k)
    o,h,l,c,e,p=(float(frame[k]) for k in fields)
    if h<max(o,l,c) or l>min(o,c):raise ValueError('INVALID_OHLC')
    continuation_rule=rule in ('CLOSE_RSI_CONTINUATION_SLOPE_COLOUR','CLOSE_RSI40_60_SLOPE_COLOUR')
    bull_level,bear_level=(40,60) if rule=='CLOSE_RSI40_60_SLOPE_COLOUR' else (45,55)
    cross_required=rule in ('CLOSE_AND_RSI_CROSS','CLOSE_RSI_SLOPE_COLOUR')
    rsi_required=cross_required or continuation_rule
    slope_colour=rule in ('CLOSE_RSI_SLOPE_COLOUR','CLOSE_RSI_CONTINUATION_SLOPE_COLOUR','CLOSE_RSI40_60_SLOPE_COLOUR')
    close_only=rule in ('CLOSE_BOTH','CLOSE_AND_RSI_CROSS','CLOSE_RSI_SLOPE_COLOUR','CLOSE_RSI_CONTINUATION_SLOPE_COLOUR','CLOSE_RSI40_60_SLOPE_COLOUR') or (side=='BULLISH' and rule=='BULLISH_CLOSE')
    whole_side=l>e if side=='BULLISH' else h<e
    close_side=c>e if side=='BULLISH' else c<e
    correct_side=close_side if close_only else whole_side
    correct_slope=e>p if side=='BULLISH' else e<p
    reasons=[]
    if not correct_side:
        if close_only:reasons.append('BULLISH_CLOSE_NOT_ABOVE_EMA10' if side=='BULLISH' else 'BEARISH_CLOSE_NOT_BELOW_EMA10')
        else:reasons.append('ENTIRE_CANDLE_NOT_ABOVE_EMA10' if side=='BULLISH' else 'ENTIRE_CANDLE_NOT_BELOW_EMA10')
    if (not close_only or slope_colour) and not correct_slope:reasons.append('EMA10_NOT_RISING' if side=='BULLISH' else 'EMA10_NOT_FALLING')
    cross=rsi_cross(side,frame.get('previous_rsi9'),frame.get('rsi9'))
    colour_pass=c>o if side=='BULLISH' else c<o
    if slope_colour and not colour_pass:reasons.append('BULLISH_CANDLE_NOT_GREEN' if side=='BULLISH' else 'BEARISH_CANDLE_NOT_RED')
    continuation_pass=False
    if cross['rsi_evidence_available']:
        prior_rsi=float(frame['previous_rsi9']);current_rsi=float(frame['rsi9'])
        continuation_pass=(current_rsi>prior_rsi and current_rsi>bull_level) if side=='BULLISH' else (current_rsi<prior_rsi and current_rsi<bear_level)
    if rsi_required:
        if frame.get('rsi_available_at') is not None and frame['rsi_available_at']!=frame['available_at']:raise ValueError('RSI_EMA_BOUNDARY_MISMATCH')
        if not cross['rsi_evidence_available']:reasons.append('COMPLETED_RSI_CROSS_EVIDENCE_MISSING')
        elif continuation_rule and not continuation_pass:reasons.append('RSI_NOT_RISING_ABOVE_'+str(bull_level) if side=='BULLISH' else 'RSI_NOT_FALLING_BELOW_'+str(bear_level))
        elif not continuation_rule and not cross['rsi_cross_pass']:reasons.append('NO_COMPLETED_RSI_UP_CROSS_45_OR_55' if side=='BULLISH' else 'NO_COMPLETED_RSI_DOWN_CROSS_55_OR_45')
    return dict(frame,passed=not reasons,reasons=reasons,ema10_slope=e-p,
                entire_candle_pass=whole_side,slope_pass=correct_slope,price_position_pass=correct_side,
                ema_entry_rule=rule,slope_required=not close_only or slope_colour,candle_colour_required=slope_colour,candle_colour_pass=colour_pass,close_above_ema10=c>e,close_below_ema10=c<e,
                rsi_cross_required=cross_required,rsi_continuation_required=continuation_rule,rsi_continuation_pass=continuation_pass,
                rsi_signal_route=('FRESH_CROSS' if cross['rsi_cross_pass'] else 'CONTINUATION') if continuation_rule and continuation_pass else 'NONE',**cross)


def followup_check(side, signal, frame, at, require_direction=False,continued=False):
    if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    reasons=[]
    if at!=signal['due'] or (not continued and at!=signal['time']+timedelta(minutes=5)) or (continued and (at<=signal['time'] or (at-signal['time']).total_seconds()%300!=0)):reasons.append('NOT_IMMEDIATE_NEXT_5M_BOUNDARY')
    if at.strftime('%H:%M')>='14:55':reasons.append('SESSION_CUTOFF')
    if frame is None:return dict(passed=False,reasons=reasons+['FOLLOWUP_FRAME_MISSING'],signal_close=signal['close'])
    available=datetime.fromisoformat(frame['available_at'])
    if available>at:raise ValueError('FUTURE_EMA_FRAME')
    if available!=at:reasons.append('FOLLOWUP_FRAME_NOT_CURRENT')
    close=frame['close'];original=signal['close'];midpoint=signal['midpoint']
    if any(isinstance(v,bool) or v is None or not math.isfinite(float(v)) or float(v)<=0 for v in (close,original,midpoint)):raise ValueError('INVALID_FOLLOWUP_CLOSE')
    close_pass=float(close)>float(original) if side=='BULLISH' else float(close)<float(original)
    midpoint_pass=float(close)>float(midpoint) if side=='BULLISH' else float(close)<float(midpoint)
    if not (close_pass or midpoint_pass):reasons.append('FOLLOWUP_CLOSE_NOT_ABOVE_SIGNAL_CLOSE_OR_MIDPOINT' if side=='BULLISH' else 'FOLLOWUP_CLOSE_NOT_BELOW_SIGNAL_CLOSE_OR_MIDPOINT')
    direction={}
    if require_direction:
        values=[frame.get(k) for k in ('open','previous_rsi9','rsi9')]
        valid=all(v is not None and not isinstance(v,bool) and math.isfinite(float(v)) for v in values)
        valid=valid and float(values[0])>0 and all(0<=float(v)<=100 for v in values[1:])
        current_rsi=frame.get('rsi_available_at')==at.isoformat()
        colour=valid and (float(close)>float(values[0]) if side=='BULLISH' else float(close)<float(values[0]))
        rsi_direction=valid and current_rsi and (float(values[2])>float(values[1]) if side=='BULLISH' else float(values[2])<float(values[1]))
        if not colour:reasons.append('FOLLOWUP_CANDLE_COLOUR_FAILED')
        if not rsi_direction:reasons.append('FOLLOWUP_RSI_DIRECTION_FAILED')
        direction=dict(followup_colour_pass=bool(colour),followup_rsi_direction_pass=bool(rsi_direction),followup_direction_required=True)
    return dict(frame,passed=not reasons,reasons=reasons,signal_close=original,signal_midpoint=midpoint,
                **direction,
                signal_time=signal['time'].isoformat(),followup_rule='NEXT_CLOSE_VS_SIGNAL_CLOSE_OR_MIDPOINT',
                signal_close_comparison_pass=close_pass,signal_midpoint_comparison_pass=midpoint_pass,
                confirmation_route='BOTH' if close_pass and midpoint_pass else 'SIGNAL_CLOSE' if close_pass else 'MIDPOINT' if midpoint_pass else 'NONE')


def ema10_touch(frame,at):
    if frame is None or frame.get('available_at')!=at.isoformat():return False
    values=[frame.get(k) for k in ('low','high','ema10')]
    if not all(v is not None and not isinstance(v,bool) and math.isfinite(float(v)) and float(v)>0 for v in values):return False
    low,high,ema=map(float,values)
    return low<=ema<=high


def numeric(value):
    return value is not None and not isinstance(value,bool) and math.isfinite(float(value))


def apply_gap(evidence,frame,minimum):
    e=frame.get('ema3_rsi') if frame else None;w=frame.get('wma21_rsi') if frame else None
    gap=float(e)-float(w) if numeric(e) and numeric(w) else None
    passed=gap is not None and gap>=minimum
    evidence.update(bullish_signal_gap=gap,bullish_signal_gap_min=minimum,bullish_signal_gap_pass=passed)
    if not passed:
        evidence['passed']=False;evidence['reasons'].append('BULLISH_SIGNAL_GAP_BELOW_MIN_OR_MISSING')


def apply_magnitude(evidence,waiting,frames,at,minimum):
    signal=frames.get(waiting['time']);entry=frames.get(at)
    previous=signal.get('previous_wma21_rsi') if signal else None
    current=entry.get('wma21_rsi') if entry else None
    valid=signal is not None and entry is not None and signal.get('available_at')==waiting['time'].isoformat() and entry.get('available_at')==at.isoformat()
    full=float(current)-float(previous) if valid and numeric(previous) and numeric(current) else None
    passed=full is not None and full>=minimum
    evidence.update(bullish_pre_signal_wma=previous,bullish_entry_wma=current,full_wma_magnitude=full,full_wma_min=minimum,full_wma_pass=passed)
    if not passed:
        evidence['passed']=False;evidence['reasons'].append('BULLISH_FULL_WMA_MAGNITUDE_BELOW_MIN_OR_MISSING')


def entry_gate(Parent,frames,rule='FULL_CANDLE',followup=False,continue_waiting=False,until_opposite=False,reset_reference_only=False,touch_wait=False,signal_gap_min=0,full_wma_min=0):
    class EmaEntry(Parent):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if not hasattr(self,'policy_events'):self.policy_events=[]
        def retain_followup(self,waiting,check,at,candidate):
            if not (continue_waiting or touch_wait) or candidate is None or candidate['available'].isoformat()!=waiting['setup_available']:return False
            if self.locked or at.strftime('%H:%M')>='14:55':return False
            if touch_wait:
                if at!=waiting['due'] or not ema10_touch(frames.get(at),at):return False
            elif not until_opposite and not all(check.get(k) for k in ('wma_threshold_pass','gap_positive_pass','gap_expanding_pass')):return False
            # Retain original reference and identity, never refresh candidate lifetime.
            self.pending[waiting['direction']]=candidate
            self.followup_signal=dict(waiting,due=at+timedelta(minutes=5))
            return True
        def evaluate(self,**kwargs):
            at=kwargs['minute']+timedelta(minutes=1)
            # Match the parent's watch expiry before snapshotting; never resurrect stale watch.
            self.can_signal('BULLISH',at)
            before={side:dict(p) for side,p in self.pending.items()}
            watch=(self.watch_side,self.watch_at)
            event_start=len(self.policy_events)
            self.followup_failed_at=None
            waiting=getattr(self,'followup_signal',None)
            if waiting is not None:
                pending=before.get(waiting['direction'])
                if pending is None or pending['available'].isoformat()!=waiting['setup_available'] or at>waiting['due']:
                    self.policy_events.append(dict(event='FOLLOWUP_CANDLE_CHECK',time=at.isoformat(),direction=waiting['direction'],setup_available=waiting['setup_available'],passed=False,reasons=['FOLLOWUP_CANCELLED_OR_MISSED'],signal_close=waiting['close'],signal_midpoint=waiting['midpoint']))
                    if at==waiting['due'] and at.minute%5==0:
                        self.followup_failed_at=at
                        stale=self.pending.get(waiting['direction'])
                        if stale is not None and stale['available'].isoformat()==waiting['setup_available']:self.pending.pop(waiting['direction'],None)
                    self.followup_signal=None;waiting=None
            self.followup_price_permission=None
            if followup and waiting is not None and at==waiting['due']:
                price_ev=followup_check(waiting['direction'],waiting,frames.get(at),at,require_direction=True,continued=(continue_waiting or touch_wait))
                if price_ev['passed']:self.followup_price_permission=(waiting['direction'],at)
            try:
                entries,checks=super().evaluate(**kwargs)
            finally:
                self.followup_price_permission=None
            if not entries:
                if waiting is not None and at==waiting['due']:
                    side=waiting['direction']
                    check=next((c for c in checks if c.get('direction')==side),{})
                    ev=followup_check(side,waiting,frames.get(at),at,require_direction=True,continued=(continue_waiting or touch_wait))
                    retained=self.retain_followup(waiting,check,at,self.pending.get(side))
                    ev.update(passed=False,continued_wait=retained,ema10_touch_pass=ema10_touch(frames.get(at),at) if touch_wait else None)
                    ev['reasons']=list(ev['reasons'])+(['CONTINUE_WAIT_EMA10_TOUCH' if touch_wait else 'CONTINUE_WAIT_UNTIL_QUALIFIED_OPPOSITE' if until_opposite else 'CONTINUE_WAIT_FRESH_STRENGTH_GAP_PASSED'] if retained else ['FRESH_ENTRY_CHECKS_FAILED_OR_CANDIDATE_CANCELLED'])
                    self.policy_events.append(dict(event='FOLLOWUP_CANDLE_CHECK',time=at.isoformat(),direction=side,setup_available=waiting['setup_available'],directional_strength=check.get('directional_wma_strength'),directional_gap=check.get('current_gap'),gap_expansion=check.get('gap_delta'),**ev))
                    if not retained:
                        if not reset_reference_only:self.pending.pop(side,None)
                        self.followup_signal=None
                        self.followup_failed_at=at
                        if reset_reference_only:self.policy_events[-1]['reasons'].append('SIGNAL_REFERENCE_DISCARDED_SEEK_FRESH_SIGNAL')
                return entries,checks
            side=self.owner
            matching=[c for c in checks if c.get('status')=='ENTRY' and c['direction']==side]
            if len(entries)!=1 or len(matching)!=1 or side not in before:raise ValueError('CONFIRMATION_IDENTITY_MISMATCH')
            check=matching[0];boundary=at.replace(minute=at.minute//5*5,second=0,microsecond=0)
            is_followup=followup and waiting is not None and waiting['direction']==side and at==waiting['due']
            if is_followup:
                evidence=followup_check(side,waiting,frames.get(boundary),at,require_direction=True,continued=(continue_waiting or touch_wait))
                price_pass=evidence['passed']
                fresh_pass=bool(check.get('wma_threshold_pass') and check.get('gap_positive_pass') and check.get('gap_expanding_pass'))
                structural=[reason for reason in evidence['reasons'] if not reason.startswith('FOLLOWUP_CLOSE_NOT_')]
                evidence.update(passed=not structural and (price_pass or fresh_pass),reasons=structural,
                    followup_price_pass=price_pass,fresh_strength_gap_pass=fresh_pass,
                    entry_confirmation_route='BOTH' if price_pass and fresh_pass else 'PRICE' if price_pass else 'FRESH_CHECKS' if fresh_pass else 'NONE')
                if not price_pass and not fresh_pass:evidence['reasons'].append('FOLLOWUP_PRICE_AND_FRESH_CHECKS_FAILED')
                if side=='BULLISH' and full_wma_min>0:apply_magnitude(evidence,waiting,frames,at,full_wma_min)
                self.followup_signal=None
            else:
                evidence=frame_check(side,frames.get(boundary),at,rule=rule)
                if reset_reference_only:
                    values=[evidence.get(k) for k in ('rsi9','ema3_rsi','wma21_rsi')]
                    ready=all(v is not None and not isinstance(v,bool) and math.isfinite(float(v)) for v in values)
                    alignment=ready and (float(values[0])>float(values[1])>float(values[2]) if side=='BULLISH' else float(values[0])<float(values[1])<float(values[2]))
                    evidence['fresh_signal_alignment_pass']=bool(alignment)
                    if not alignment:
                        evidence['passed']=False
                        evidence['reasons'].append('FRESH_SIGNAL_ALIGNMENT_FAILED_OR_MISSING')
                if side=='BULLISH' and signal_gap_min>0:apply_gap(evidence,frames.get(boundary),signal_gap_min)
                if followup and evidence['passed']:
                    self.followup_signal=dict(direction=side,setup_available=check['signal_available_at'],time=at,due=at+timedelta(minutes=5),close=float(evidence['close']),high=float(evidence['high']),low=float(evidence['low']),midpoint=(float(evidence['high'])+float(evidence['low']))/2)
                    evidence.update(passed=False,reasons=['WAIT_NEXT_COMPLETED_5M_CLOSE'],signal_close=evidence['close'],signal_midpoint=self.followup_signal['midpoint'],followup_due=(at+timedelta(minutes=5)).isoformat())
            check['ema10_entry']=evidence
            self.policy_events.append(dict(event='FOLLOWUP_CANDLE_CHECK' if is_followup else 'EMA10_ENTRY_CHECK',time=at.isoformat(),direction=side,
                setup_available=check['signal_available_at'],baseline_confirmed=True,
                directional_strength=check.get('directional_wma_strength'),directional_gap=check.get('current_gap'),
                gap_expansion=check.get('gap_delta'),**evidence))
            if evidence['passed']:return entries,checks
            candidate=before[side]
            if candidate['available'].isoformat()!=check['signal_available_at']:raise ValueError('CANDIDATE_IDENTITY_MISMATCH')
            if candidate.get('armed_at') is None:candidate['armed_at']=kwargs['minute']
            self.owner='NONE';self.active=None
            if is_followup:
                retained=self.retain_followup(waiting,check,at,candidate)
                evidence['continued_wait']=retained
                evidence['ema10_touch_pass']=ema10_touch(frames.get(at),at) if touch_wait else None
                if retained:evidence['reasons'].append('CONTINUE_WAIT_EMA10_TOUCH' if touch_wait else 'CONTINUE_WAIT_UNTIL_QUALIFIED_OPPOSITE' if until_opposite else 'CONTINUE_WAIT_FRESH_STRENGTH_GAP_PASSED')
                else:
                    if reset_reference_only:
                        self.pending[side]=candidate
                        evidence['reasons'].append('SIGNAL_REFERENCE_DISCARDED_SEEK_FRESH_SIGNAL')
                    else:self.pending.pop(side,None)
                    self.followup_failed_at=at
                self.policy_events[-1].update(continued_wait=retained,reasons=list(evidence['reasons']))
            else:self.pending[side]=candidate
            self.watch_side,self.watch_at=watch
            check.update(status='EMA10_ENTRY_WAIT',reasons=list(evidence['reasons']))
            for event in self.policy_events[event_start:]:
                if event.get('event')=='COMBINED_ENTRY_DECISION' and event.get('outcome')=='PASS':
                    event.update(outcome='WAIT_EMA10_ENTRY',baseline_confirmed=True)
            # previous minute snapshot remains current; no stale confirmation latch.
            return [],checks
    return EmaEntry


class _BoundaryBase(WmaGapGate):
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
            consecutive=previous is not None and previous['minute']==minute-timedelta(minutes=5)
            same_boundary=exit_boundary and age == -1
            elapsed=age>=-1 or same_boundary
            threshold=strength is not None and strength>=.75
            was_armed=p['armed_at'] is not None and minute>p['armed_at']
            persistence=(was_armed or same_boundary) and consecutive and previous_strength is not None and previous_strength>=.75 and threshold
            expansion=gap is not None and prev_gap is not None and consecutive and gap>prev_gap
            reasons=[]
            if self.locked or (minute+timedelta(minutes=1)).time()>=time(14,55):reasons.append('SESSION_CUTOFF')
            if age<-1 and not same_boundary:reasons.append('WAIT_FIRST_POST_SIGNAL_MINUTE')
            elif not elapsed:reasons.append('WINDOW_EXPIRED')
            if not threshold:reasons.append('WMA_THRESHOLD_NOT_MET')
            # Persistence is diagnostic only.
            if gap is None or gap<=0:reasons.append('GAP_NOT_POSITIVE')
            if not expansion:reasons.append('GAP_NOT_EXPANDING_OR_PREVIOUS_MINUTE_MISSING')
            if self.owner!='NONE':reasons.append('ACTIVE_TRADE_OWNER')
            if getattr(self,'followup_price_permission',None)==(side,minute+timedelta(minutes=1)):
                reasons=[r for r in reasons if r not in ('WMA_THRESHOLD_NOT_MET','GAP_NOT_POSITIVE','GAP_NOT_EXPANDING_OR_PREVIOUS_MINUTE_MISSING')]
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
            elif self.locked:del self.pending[side]
        change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None
        self.previous={'minute':minute,'snapshot':current,'wma_change':change}
        return accepted,checks


class DirectFive(_BoundaryBase):
    def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
        at=minute+timedelta(minutes=1)
        if at.minute%5:return [],[]
        self.previous=dict(minute=minute-timedelta(minutes=5),snapshot=reference,wma_change=None) if reference and reference.ready else None
        entries,checks=super().evaluate(minute=minute,current=current,reference=reference,price=price,exit_boundary=exit_boundary)
        self.previous=dict(minute=minute,snapshot=current,wma_change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None)
        for c in checks:c.update(policy_name=POLICY_ID,strategy_version=VERSION,confirmation_interval_minutes=5,confirmation_snapshot_basis='COMPLETED_FIVE_MINUTE',persistence_required=False,setup_boundary_entry_allowed=True,gap_reference='PREVIOUS_COMPLETED_FIVE_MINUTE',candidate_time_expiry_enabled=False)
        return entries,checks


def qualified_opposite_watch_gate(Parent,frames,direction,require_wma_permission=True,signal_rule='CLOSE_RSI_CONTINUATION_SLOPE_COLOUR',until_opposite=False):
    """Only a complete new signal may override an opposite setup watch."""
    class QualifiedWatch(Parent):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if not hasattr(self,'policy_events'):self.policy_events=[]
        def qualifies(self,side,at):
            if self.owner!='NONE' or self.locked or at.minute%5 or at.strftime('%H:%M')>='14:55':return False
            frame=frames.get(at)
            if frame is None or not frame_check(side,frame,at,rule=signal_rule)['passed']:return False
            keys=('rsi9','ema3_rsi','wma21_rsi','previous_ema3_rsi','previous_wma21_rsi')
            if any(frame.get(k) is None or isinstance(frame[k],bool) or not math.isfinite(float(frame[k])) for k in keys):return False
            r,e,w,pe,pw=(float(frame[k]) for k in keys);sign=1 if side=='BULLISH' else -1
            gap=sign*(e-w);previous_gap=sign*(pe-pw)
            if not (sign*(r-e)>0 and gap>0 and gap>previous_gap and sign*(w-pw)>=.75):return False
            if not require_wma_permission:return True
            self.direction_lock.observe(at,w,pw,self.owner)
            if self.direction_lock.permits(side):return True
            import hilega_existing_ema10_wma_exception_40_60_last10_research as exception
            return exception.exception_allows(self.direction_lock.side,side,r,e)
        def can_signal(self,side,at):
            if until_opposite:
                return self.watch_side in (None,side) or self.qualifies(side,at)
            allowed=super().can_signal(side,at)
            if allowed:return True
            return self.watch_side is not None and self.watch_side!=side and self.qualifies(side,at)
        def signal(self,event,available):
            side=direction(event)
            if until_opposite and side in self.pending:return
            opposite=self.watch_side is not None and self.watch_side!=side
            if opposite:
                if not self.qualifies(side,available):return
                self.policy_events.append(dict(event='QUALIFIED_OPPOSITE_WATCH_OVERRIDE',time=available.isoformat(),
                    setup_available=available.isoformat(),direction=side,previous_watch=self.watch_side,previous_watch_at=self.watch_at.isoformat() if self.watch_at else None))
            return super().signal(event,available)
        def observe_arms(self,events,available):
            if until_opposite:return
            return super().observe_arms(events,available)
        def close(self,event,at,price):
            # Canonical cancellation while flat must not erase a retained setup.
            # Active-position exits and session cutoff are unchanged.
            if until_opposite and self.owner!=direction(event):return None
            return super().close(event,at,price)
    return QualifiedWatch


def make_gate(frames):
    Watch=qualified_opposite_watch_gate(DirectFive,frames,direction,require_wma_permission=False,signal_rule='CLOSE_RSI40_60_SLOPE_COLOUR',until_opposite=True)
    class GapWatch(Watch):
        def qualifies(self,side,at):
            if not super().qualifies(side,at):return False
            if side!='BULLISH':return True
            evidence=dict(passed=True,reasons=[]);apply_gap(evidence,frames.get(at),2)
            return evidence['passed']
    Gate=entry_gate(GapWatch,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,until_opposite=True,reset_reference_only=True,touch_wait=True,signal_gap_min=2,full_wma_min=2)
    return Gate(opposite_switch=True)

class PriceFrames:
    def __init__(self):self.value=None;self.count=0;self.frames={}
    def seed(self,bar):
        previous=self.value;close=float(bar.close)
        if not math.isfinite(close) or close<=0:raise ValueError('INVALID_PRICE_EMA_CLOSE')
        self.value=close if previous is None else previous+(2/11)*(close-previous)
        self.count+=1
        return previous
    def complete(self,bar,snapshot,reference):
        previous=self.seed(bar);at=bar.ts+timedelta(minutes=5)
        if at in self.frames:raise ValueError('DUPLICATE_COMPLETED_POLICY_FRAME')
        self.frames[at]=dict(open=float(bar.open),high=float(bar.high),low=float(bar.low),close=float(bar.close),ema10=self.value,previous_ema10=previous,candle_label=bar.ts.isoformat(),available_at=at.isoformat(),seeded_bar_count=self.count,rsi9=snapshot.rsi9,previous_rsi9=reference.rsi9 if reference else None,ema3_rsi=snapshot.ema3_rsi,wma21_rsi=snapshot.wma21_rsi,previous_ema3_rsi=reference.ema3_rsi if reference else None,previous_wma21_rsi=reference.wma21_rsi if reference else None,rsi_available_at=at.isoformat())
        return self.frames[at]

def reset_pending(gate):
    gate.pending.clear();gate.followup_signal=None;gate.followup_price_permission=None
    gate.followup_failed_at=None;gate.watch_side=None;gate.watch_at=None

from .hilega_milega_strategy_v1 import StrategyEvent

def advance_boundary(c,g,bar,reference,tracker,manual_block=False):
    at=bar.ts+timedelta(minutes=5);minute=at-timedelta(minutes=1)
    start=len(g.policy_events);setups=[];signals=[];events=[];exit_validation=None
    dec=c.on_bar(bar);current=c.bullish.previous_indicators
    frame=tracker.complete(bar,current,reference)
    g.observe_arms(dec.accepted_events,at)
    if g.owner!='NONE':
        side=g.owner;sign=1 if side=='BULLISH' else -1
        exit_validation=dict(direction=side,rsi9=current.rsi9,ema3=current.ema3_rsi,wma21=current.wma21_rsi,rsi_opposite=sign*(current.rsi9-current.wma21_rsi)<0,ema_opposite=sign*(current.ema3_rsi-current.wma21_rsi)<0,dual_exit_pass=dual_exit(side,current))
        if exit_validation['dual_exit_pass']:
            event=StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if side=='BULLISH' else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',at,None,'ACTIVE','IDLE',exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
            closed=g.close(event,at,float(bar.close))
            if closed:events.append(closed)
    for event in dec.accepted_events:
        if event.event_type in ENTRY_TYPES and g.owner=='NONE' and direction(event) not in g.pending:
            g.signal(event,at);setups.append(dict(time=at.isoformat(),direction=direction(event),source='V1_CANONICAL'))
    def fresh_setups():
        for side in ('BULLISH','BEARISH'):
            sign=1 if side=='BULLISH' else -1
            aligned=current and current.ready and sign*(current.rsi9-current.ema3_rsi)>0 and sign*(current.ema3_rsi-current.wma21_rsi)>0
            if g.can_signal(side,at) and aligned and g.owner=='NONE' and side not in g.pending and at.time()<time(14,55):
                event=StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',minute,'ALTERNATIVE_ALIGNMENT','IDLE','ARMED',details={'alternative':True})
                g.signal(event,at);setups.append(dict(time=at.isoformat(),direction=side,source='ALTERNATIVE_ALIGNMENT'))
                gap=sign*(current.ema3_rsi-current.wma21_rsi);pg=sign*(reference.ema3_rsi-reference.wma21_rsi) if reference else None
                signals.append(dict(time=at.isoformat(),direction=side,rsi=current.rsi9,ema=current.ema3_rsi,wma=current.wma21_rsi,current_gap=gap,previous_gap=pg,delta=gap-pg if pg is not None else None,strength=sign*(current.wma21_rsi-reference.wma21_rsi) if reference else None))
    if manual_block:reset_pending(g)
    else:fresh_setups()
    entries,checks=g.evaluate(minute=minute,current=current,reference=reference,price=float(bar.close),exit_boundary=bool(events))
    if not manual_block and not entries and g.owner=='NONE' and getattr(g,'followup_failed_at',None)==at and at.time()<time(14,55):
        g.policy_events.append(dict(event='FRESH_SETUP_AFTER_FOLLOWUP_FAILURE',time=at.isoformat()))
        fresh_setups();entries,retry=g.evaluate(minute=minute,current=current,reference=reference,price=float(bar.close),exit_boundary=bool(events));checks+=retry
    if entries:
        g.pending.clear()
        confirmed=[]
        for e in entries:
            evidence=next((v for v in reversed(g.policy_events[start:]) if v.get('event')=='FOLLOWUP_CANDLE_CHECK' and v.get('direction')==direction(e) and v.get('passed') is True),{})
            confirmed.append(replace(e,details={**e.details,'policy_id':POLICY_ID,'strategy_version':VERSION,'qualified_signal_time':evidence.get('signal_time'),'combined_entry':deepcopy(evidence)}))
        entries=confirmed
    if at.time()>=time(14,55):reset_pending(g)
    policy_events=deepcopy(g.policy_events[start:])
    for row in policy_events:row.update(policy_id=POLICY_ID,strategy_version=VERSION)
    return dict(decision=dec,current=current,entries=entries,exits=events,checks=checks,setups=setups,signals=signals,exit_validation=exit_validation,policy_events=policy_events,frame=frame,pending_switches=g.take_switches())
