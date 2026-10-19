"""Research only: scoped close versus price EMA10 AND completed RSI9 threshold cross.
Only Fresh AND + EMA10 and Existing baseline 2 use the new conjunction.
No orders, installation or live strategy changes. Optional --fetch-today uses
one read-only analytics request. Run from RB-ITOS-AI.
"""
import csv
import inspect
import json
import linecache
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='FRESH_DIRECT_5M_RSI40_60_SINGLE_FOLLOWUP_V19'
BASES=('EXISTING','PREVIOUS_AND','FRESH_AND')
POLICIES=tuple(k for b in BASES for k in (b,b+'_EMA10_ENTRY'))+('EXISTING_BASELINE_2',)
WARNING=('Research only. Gross NIFTY points; no option fills or costs. Each EMA variant adds an entry gate to its own baseline. '
    'EXISTING_BASELINE_2 requires bullish completed 5m CLOSE > price EMA10 AND RSI9 crossing UP through 45 OR 55; '
    'bearish completed 5m CLOSE < EMA10 AND RSI9 crossing DOWN through 55 OR 45. Those baseline-2 conditions must pass on the same completed candle. Fresh EMA instead requires RSI9 rising and above40 for bullish, falling and below60 for bearish; fresh crosses or directional continuation qualify. Flat RSI and threshold equality fail. Its EMA slope, candle colour and other signal checks remain mandatory. '
    'Cross UP means previous RSI <= threshold and current RSI > threshold; DOWN means previous RSI >= threshold and current RSI < threshold. '
    'No cross latch: evidence expires when a new completed 5m candle replaces it. Fresh direct 5m starts checking at the immediately next completed 5m close strictly above signal CLOSE OR signal midpoint for bullish, below signal CLOSE OR signal midpoint for bearish; midpoint=(signal high+low)/2, close-based comparison not intrabar touch; no entry on signal candle. Follow-up requires a green candle AND rising completed RSI9 for bullish, or a red candle AND falling completed RSI9 for bearish; doji/flat RSI fails. These mandatory checks cannot be bypassed by either price confirmation OR fresh strength/positive-expanding-gap checks. For the latest FRESH_AND_EMA10_ENTRY policy, WMA direction lock and RSI/EMA lock exceptions are DISABLED. Candidate validity, flat position and cutoff remain mandatory for either route. Signal candle still requires all original signal checks. No repeated RSI cross on follow-up. Latest policy has NO candidate or direction-watch expiry. Each qualified signal close/midpoint is valid ONLY for its immediate next completed5m candle. A failed follow-up discards that signal reference and seeks a fresh fully qualifying signal. The failed candle can itself qualify as the new signal on the same boundary, then must wait for its own next candle. Underlying candidate monitoring remains unlimited; fresh qualification rechecks alignment, strength, positive expanding5m gap, RSI40/60 direction, EMA10 position/slope and colour. Opposite arms, incomplete setups and canonical pending cancellation do not discard the candidate. Only a fully qualifying opposite signal replaces the pending direction; it must then pass its own follow-up. Same-direction repeated setup events do not reset the candidate; a fresh qualifying signal after failed follow-up saves a NEW candle reference. Actual entry clears pending candidates; session cutoff still clears them. A fresh qualifying signal waits for its own next completed candle; discarded close and midpoint are never reused. Original cancellation and expiry remain only in unchanged controls; cutoff still applies to all policies. Wicks do not veto these two policies. Fresh direct 5m additionally requires rising EMA10 and green close>open for bullish, falling EMA10 and red close<open for bearish; flat EMA or doji fails. Existing baseline 2 has no slope or colour veto. '
    'EXISTING_EMA10_ENTRY and PREVIOUS_AND_EMA10_ENTRY retain whole-candle position AND directional EMA10 slope. '
    'Strict comparisons; equality waits. EMA10 uses close, alpha 2/11, first-close seed, continuous over original warmup. '
    'FRESH_AND_EMA10_ENTRY now removes minute-gap setup vetoes, separate 1m entry evaluation and persistence. '
    'It evaluates strength >=0.75 and positive expanding gap against the previous completed 5m reference, plus close/RSI-directional-continuation, '
    'directly at completed 5m boundaries INCLUDING the setup boundary. WMA direction lock and 40/60 AND exceptions are disabled only for this latest policy; WMA alignment, strength and gap calculations remain required. '
    'Its time expiry and canonical pending cancellation are disabled; an opposite direction watch may be replaced only by a full qualifying completed5m signal (alignment, strength, expansion, EMA10 position/slope, candle colour, RSI continuation, flat and cutoff); an arm alone cannot override it; existing pending candidates are not refreshed. '
    'Other EMA variants retain their prior confirmation rules. WMA-vetoed candidates stay consumed. Original exits and 14:55 cutoff retained. '
    'EXISTING_BASELINE_2 instead validates only completed 5m boundaries: strength >=0.75, positive gap expanding versus the prior completed 5m, '
    'plus the close/RSI-cross conjunction above. No persistence veto or time-based candidate expiry in baseline 2. '
    'Existing setup generation, opposite-arm/setup cancellation, canonical cancellation, position ownership and exits remain in baseline 2; '
    'no WMA direction lock or RSI/EMA exception is added. A candidate can still be cancelled by original lifecycle events. '
    'Baseline 2 retains its first-post-setup timing and same-exit-boundary exception. No EMA exit or reversal override in any policy. '
    'Historical controls reproduce saved research, not historical broker execution; Oct16 recorded/API inputs are mixed. '
    'Exploratory sample already examined; no independent holdout or live changes.')


def single_session(value,calendar,start,end,extra_day):
    try:
        parsed=datetime.strptime(value,'%Y-%m-%d').date().isoformat()
    except ValueError as exc:raise ValueError('DATE_MUST_BE_YYYY_MM_DD') from exc
    if parsed!=value:raise ValueError('DATE_MUST_BE_YYYY_MM_DD')
    if not start<=value<=end:raise ValueError('DATE_OUTSIDE_SAVED_RESEARCH_RANGE:'+start+'..'+end)
    if value not in set(calendar)|{extra_day}:raise ValueError('REQUESTED_TRADING_SESSION_UNAVAILABLE:'+value)
    return [value]


def rsi_cross(side,previous,current):
    if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    for value in (previous,current):
        if isinstance(value,bool) or value is None or not math.isfinite(float(value)) or not 0<=float(value)<=100:
            return dict(rsi_cross_pass=False,rsi_crossed_thresholds=[],rsi_evidence_available=False)
    previous,current=float(previous),float(current)
    thresholds=[v for v in (45,55) if (previous<=v<current if side=='BULLISH' else current<v<=previous)]
    return dict(rsi_cross_pass=bool(thresholds),rsi_crossed_thresholds=thresholds,rsi_evidence_available=True)


def attach_completed_rsi(frames,baseline,dt):
    seen=set()
    for row in baseline['audit']:
        at=dt(row['checkpoint']);ind=row.get('completed_5m_indicators');changes=row.get('five_minute_changes')
        if at not in frames or not ind or not changes:continue
        if at in seen:raise ValueError('DUPLICATE_COMPLETED_RSI_FRAME')
        seen.add(at)
        current=ind.get('rsi9');delta=changes.get('rsi9')
        previous=float(current)-float(delta) if current is not None and delta is not None else None
        frames[at].update(ema3_rsi=ind.get('ema3'),wma21_rsi=ind.get('wma21'),
            previous_ema3_rsi=(float(ind['ema3'])-float(changes['ema3'])) if ind.get('ema3') is not None and changes.get('ema3') is not None else None,
            previous_wma21_rsi=(float(ind['wma21'])-float(changes['wma21'])) if ind.get('wma21') is not None and changes.get('wma21') is not None else None,
            rsi9=current,previous_rsi9=previous,rsi_source='COMPLETED_5M_INPUT_BASELINE',rsi_available_at=at.isoformat())
    return frames


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


def build_frames(engine,day,raw,warm,dt):
    if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    value=None;frames={};count=0
    for session,rows in list(warm)+[(day,raw)]:
        # The cutoff minute OPEN is replay evidence, not a completed 14:55-15:00 bar.
        if session==day:rows=[r for r in rows if dt(r['timestamp']).strftime('%H:%M')<'14:55']
        bars=engine.aggregate_exact_5m(engine.candles(rows),dt(session+'T00:00:00+05:30').date(),require_full_session=False)
        for bar in bars:
            previous=value;close=float(bar.close)
            if not math.isfinite(close) or close<=0:raise ValueError('INVALID_CLOSE')
            value=close if value is None else value+(2/11)*(close-value);count+=1
            if session==day:
                available=bar.ts+timedelta(minutes=5)
                if available in frames:raise ValueError('DUPLICATE_EMA_BOUNDARY')
                frames[available]=dict(open=float(bar.open),high=float(bar.high),low=float(bar.low),close=close,
                    ema10=value,previous_ema10=previous,candle_label=bar.ts.isoformat(),available_at=available.isoformat(),seeded_bar_count=count)
    return frames


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


def entry_gate(Parent,frames,rule='FULL_CANDLE',followup=False,continue_waiting=False,until_opposite=False,reset_reference_only=False):
    class EmaEntry(Parent):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if not hasattr(self,'policy_events'):self.policy_events=[]
        def retain_followup(self,waiting,check,at,candidate):
            if not continue_waiting or candidate is None or candidate['available'].isoformat()!=waiting['setup_available']:return False
            if self.locked or at.strftime('%H:%M')>='14:55':return False
            if not until_opposite and not all(check.get(k) for k in ('wma_threshold_pass','gap_positive_pass','gap_expanding_pass')):return False
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
                price_ev=followup_check(waiting['direction'],waiting,frames.get(at),at,require_direction=True,continued=continue_waiting)
                if price_ev['passed']:self.followup_price_permission=(waiting['direction'],at)
            try:
                entries,checks=super().evaluate(**kwargs)
            finally:
                self.followup_price_permission=None
            if not entries:
                if waiting is not None and at==waiting['due']:
                    side=waiting['direction']
                    check=next((c for c in checks if c.get('direction')==side),{})
                    ev=followup_check(side,waiting,frames.get(at),at,require_direction=True,continued=continue_waiting)
                    retained=self.retain_followup(waiting,check,at,self.pending.get(side))
                    ev.update(passed=False,continued_wait=retained)
                    ev['reasons']=list(ev['reasons'])+(['CONTINUE_WAIT_UNTIL_QUALIFIED_OPPOSITE' if until_opposite else 'CONTINUE_WAIT_FRESH_STRENGTH_GAP_PASSED'] if retained else ['FRESH_ENTRY_CHECKS_FAILED_OR_CANDIDATE_CANCELLED'])
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
                evidence=followup_check(side,waiting,frames.get(boundary),at,require_direction=True,continued=continue_waiting)
                price_pass=evidence['passed']
                fresh_pass=bool(check.get('wma_threshold_pass') and check.get('gap_positive_pass') and check.get('gap_expanding_pass'))
                structural=[reason for reason in evidence['reasons'] if not reason.startswith('FOLLOWUP_CLOSE_NOT_')]
                evidence.update(passed=not structural and (price_pass or fresh_pass),reasons=structural,
                    followup_price_pass=price_pass,fresh_strength_gap_pass=fresh_pass,
                    entry_confirmation_route='BOTH' if price_pass and fresh_pass else 'PRICE' if price_pass else 'FRESH_CHECKS' if fresh_pass else 'NONE')
                if not price_pass and not fresh_pass:evidence['reasons'].append('FOLLOWUP_PRICE_AND_FRESH_CHECKS_FAILED')
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
                if retained:evidence['reasons'].append('CONTINUE_WAIT_UNTIL_QUALIFIED_OPPOSITE' if until_opposite else 'CONTINUE_WAIT_FRESH_STRENGTH_GAP_PASSED')
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


def baseline2_gate(engine,frames,rule='FULL_CANDLE'):
    """Original lifecycle, 5m checks, unlimited time window, no persistence veto."""
    import textwrap
    from hilega_five_min_confirmation_research import five_gate
    Base=engine.WmaGapGate
    source=textwrap.dedent(inspect.getsource(Base.evaluate))
    old="if not persistence:reasons.append('WAIT_LATER_PERSISTENCE')"
    if source.count(old)!=1:raise ValueError('BASELINE2_PERSISTENCE_ANCHOR_MISMATCH')
    source=source.replace(old,'# Persistence remains diagnostic only; not an entry veto.',1)
    filename='<hilega-baseline2-no-persistence>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    namespace=dict(Base.evaluate.__globals__)
    exec(compile(source,filename,'exec'),namespace)
    NoPersistence=type('Baseline2NoPersistence',(Base,),{'evaluate':namespace['evaluate']})
    Boundary=five_gate(NoPersistence,continued=True)
    class ValidatedBoundary(Boundary):
        def evaluate(self,**kwargs):
            entries,checks=super().evaluate(**kwargs)
            for c in checks:c.update(persistence_required=False,candidate_time_expiry_enabled=False,policy_name='EXISTING_BASELINE_2')
            return entries,checks
    return entry_gate(ValidatedBoundary,frames,rule=rule)


def direct_five_base(Base,no_expiry=False):
    """5m-only strength/gap evaluation, no persistence, same-boundary setup allowed."""
    import textwrap
    source=textwrap.dedent(inspect.getsource(Base.evaluate))
    replacements={
        "previous['minute']==minute-timedelta(minutes=1)":"previous['minute']==minute-timedelta(minutes=5)",
        'elapsed=0<=age<10 or same_boundary':'elapsed=age>=-1 or same_boundary' if no_expiry else 'elapsed=-1<=age<10 or same_boundary',
        'if age<0 and not same_boundary:':'if age<-1 and not same_boundary:',
        "if not persistence:reasons.append('WAIT_LATER_PERSISTENCE')":'# Persistence is diagnostic only in direct 5m research.',
    }
    for old,new in replacements.items():
        if source.count(old)!=1:raise ValueError('DIRECT_5M_GATE_ANCHOR_MISMATCH:'+old)
        source=source.replace(old,new,1)
    if no_expiry:
        old='elif age>=10 or self.locked:del self.pending[side]'
        if source.count(old)!=1:raise ValueError('UNLIMITED_EXPIRY_ANCHOR_MISMATCH')
        source=source.replace(old,'elif self.locked:del self.pending[side]',1)
    anchor_text="if self.owner!='NONE':reasons.append('ACTIVE_TRADE_OWNER')"
    matches=[line for line in source.splitlines() if line.strip()==anchor_text]
    if len(matches)!=1:raise ValueError('FOLLOWUP_OR_GATE_ANCHOR_MISMATCH')
    anchor=matches[0];indent=anchor[:len(anchor)-len(anchor.lstrip())]
    addition=("\n"+indent+"if getattr(self,'followup_price_permission',None)==(side,minute+timedelta(minutes=1)):\n"+
        indent+"    reasons=[reason for reason in reasons if reason not in ('WMA_THRESHOLD_NOT_MET','GAP_NOT_POSITIVE','GAP_NOT_EXPANDING_OR_PREVIOUS_MINUTE_MISSING')]")
    source=source.replace(anchor,anchor+addition,1)
    filename='<hilega-fresh-direct-five-minute-gate>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    namespace=dict(Base.evaluate.__globals__)
    exec(compile(source,filename,'exec'),namespace)
    evaluate_boundary=namespace['evaluate']
    class DirectFive(Base):
        def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
            at=minute+timedelta(minutes=1)
            history=dict(minute=minute,snapshot=current,
                wma_change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None)
            if at.minute%5:
                self.can_signal('BULLISH',at)
                for side,pending in list(self.pending.items()):
                    if self.locked or (not no_expiry and (minute-pending['available']).total_seconds()/60>=10):del self.pending[side]
                self.previous=history
                return [],[]
            # Use the immediately prior completed 5m indicator snapshot, including opening reference.
            self.previous=dict(minute=minute-timedelta(minutes=5),snapshot=reference,wma_change=None) if reference and reference.ready else None
            entries,checks=evaluate_boundary(self,minute=minute,current=current,reference=reference,price=price,exit_boundary=exit_boundary)
            self.previous=history
            for c in checks:c.update(policy_name='FRESH_AND_EMA10_ENTRY',confirmation_interval_minutes=5,
                confirmation_snapshot_basis='COMPLETED_FIVE_MINUTE',persistence_required=False,
                setup_boundary_entry_allowed=True,gap_reference='PREVIOUS_COMPLETED_FIVE_MINUTE')
            return entries,checks
    return DirectFive


def followup_retry_source(source):
    """One fresh setup pass after failed follow-up; never recursive or old-close reuse."""
    start="  for side in ['BULLISH','BEARISH']:"
    evaluation='  entries,cc=g.evaluate(minute=t,current=current,reference=ref,price=float(minute.close),exit_boundary=bool(events));checks.extend(cc)'
    if source.count(start)!=1 or source.count(evaluation)!=1:raise ValueError('FOLLOWUP_RETRY_REPLAY_ANCHOR_MISMATCH')
    a=source.index(start);b=source.index(evaluation,a)
    loop=source[a:b]
    # The research simulator instruments the original setup condition once.
    # Instrument this extra pass explicitly without duplicating its exact anchor.
    loop=loop.replace('   if bar and g.can_signal(side,at)',
        "   _research_probe(_setup_audit,_policy,side,at,bar,latest,current,prev,ref,g,episode)\n   if (bar) and g.can_signal(side,at)",1)
    # Existing fresh replay resets each alignment episode at this completed boundary.
    retry="  if bar and not entries and g.owner=='NONE' and getattr(g,'followup_failed_at',None)==at and at.strftime('%H:%M')<'14:55':\n"
    retry+="   g.policy_events.append(dict(event='FRESH_SETUP_AFTER_FOLLOWUP_FAILURE',time=at.isoformat()))\n"
    retry+=''.join(' '+line+'\n' for line in loop.splitlines())
    retry+='   entries,retry_checks=g.evaluate(minute=t,current=current,reference=ref,price=float(minute.close),exit_boundary=bool(events));checks.extend(retry_checks);cc+=retry_checks\n'
    return source.replace(evaluation,evaluation+'\n'+retry.rstrip('\n'),1)


def direct_fresh_replay(engine,fresh,retry_followup=False,until_opposite=False):
    original=fresh.fresh_replay(engine)
    source=inspect.getsource(original)
    old='and aligned and gap is not None and gap>0 and expanding and not episode[side]'
    if source.count(old)!=1:raise ValueError('DIRECT_SETUP_GAP_ANCHOR_MISMATCH')
    source=source.replace(old,'and aligned and not episode[side]',1)
    old='delta=gap-pg,strength='
    if source.count(old)!=1:raise ValueError('DIRECT_SETUP_DIAGNOSTIC_ANCHOR_MISMATCH')
    source=source.replace(old,'delta=(gap-pg if gap is not None and pg is not None else None),strength=',1)
    if until_opposite:
        old='if e.event_type in EXIT_TYPES:g.pending.pop(direction(e),None)'
        if source.count(old)!=1:raise ValueError('RETAIN_CANONICAL_CANCEL_ANCHOR_MISMATCH')
        source=source.replace(old,'if False:pass # Pending survives canonical cancellation until qualifying opposite signal.',1)
    if retry_followup:source=followup_retry_source(source)
    filename='<hilega-direct-fresh-five-minute-replay>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    namespace=dict(original.__globals__)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['replay']


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


def add_variants(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold):
    frames=attach_completed_rsi(build_frames(engine,day,raw,warm,p.dt),baseline,p.dt)
    variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)
    for key,parent,replay in (
        ('EXISTING',engine.WmaGapGate,engine.replay),
        ('PREVIOUS_AND',Gate,engine.replay),
        ('FRESH_AND',NewGate,fresh.fresh_replay(engine))):
        rule='CLOSE_RSI40_60_SLOPE_COLOUR' if key=='FRESH_AND' else 'FULL_CANDLE'
        if key=='FRESH_AND':
            parent=direct_five_base(engine.WmaGapGate,no_expiry=True)
            parent=qualified_opposite_watch_gate(parent,frames,engine.direction,require_wma_permission=False,signal_rule=rule,until_opposite=True)
            replay=direct_fresh_replay(engine,fresh,retry_followup=True,until_opposite=True)
        variants[key+'_EMA10_ENTRY']=p.simulate(SimpleNamespace(WmaGapGate=entry_gate(parent,frames,rule=rule,followup=key=='FRESH_AND',continue_waiting=False,until_opposite=key=='FRESH_AND',reset_reference_only=key=='FRESH_AND'),replay=replay),day,raw,warm,asof,'CURRENT')
        if key=='FRESH_AND':
            value=variants[key+'_EMA10_ENTRY']
            for row in value['setup_diagnostics']:
                row['original_minute_gap_diagnostics']={k:row['flags'].get(k) for k in ('gap_positive','previous_minute_available','gap_expanding')}
                row['flags']={k:v for k,v in row['flags'].items() if k not in ('gap_positive','previous_minute_available','gap_expanding')}
                row['failed']=[k for k in row['failed'] if k not in ('gap_positive','previous_minute_available','gap_expanding')]
                row['minute_gap_required_for_setup']=False
            for signal in value.get('alternative_signals',[]):signal['minute_gap_diagnostic_only']=True
            value['research_entry_rules']=dict(evaluation_minutes=5,strength_min=.75,positive_expanding_5m_gap=True,
                minute_gap_setup_filter=False,persistence_required=False,setup_boundary_entry_allowed=True,
                candidate_expiry_minutes=None,signal_reference_next_candle_only=True,discard_failed_signal_reference=True,wma_lock_and_exception=False,continue_until_qualified_opposite=True,ema_rule='CLOSE_RSI40_60_SLOPE_COLOUR',rsi_rule='RISING_ABOVE_40_OR_FALLING_BELOW_60',ema10_slope_required=True,candle_colour_required=True,followup='PRICE_CLOSE_OR_MIDPOINT_OR_FRESH_STRENGTH_GAP',wma_permission_mandatory=False,fresh_setup_after_failed_followup_same_boundary=True,qualified_opposite_signal_overrides_watch=True)
    variants['EXISTING_BASELINE_2']=p.simulate(SimpleNamespace(WmaGapGate=baseline2_gate(engine,frames,rule='CLOSE_AND_RSI_CROSS'),replay=engine.replay),day,raw,warm,asof,'CURRENT')
    return variants


def write_reports(output,days,results,coverage,provenance,version,unused,stats):
    import hilega_existing_ema10_wma_combined_last10_research as base
    control_root=Path('data/research/hilega-and-fresh-setup-3months-20261016')
    control=json.loads((control_root/'report.json').read_text())
    if control.get('status')!='COMPLETE' or control.get('strategy_version')!=version:raise ValueError('COMPLETE_THREE_MONTH_CONTROL_REQUIRED')
    for day,variants in results.items():
        if provenance[day]['input_sha256']!=control['provenance'][day]['input_sha256']:raise ValueError('CONTROL_INPUT_MISMATCH:'+day)
        saved=json.loads((control_root/'sessions'/(day+'.json')).read_text())
        for key in BASES:
            if stats.signature(saved[key]['trades'])!=stats.signature(variants[key]['trades']):raise ValueError('CONTROL_POLICY_MISMATCH:'+day+':'+key)
        provenance[day]['three_month_control_parity']='PASS'
    totals={k:stats.stats([t for day in sorted(results) for t in results[day][k]['trades']]) for k in POLICIES}
    complete=len(results)==len(days)
    lines=['# Scoped EMA10 close AND RSI9 cross comparison','',WARNING,'',
        f"Status: {'COMPLETE' if complete else 'INCOMPLETE'}; coverage {len(results)}/{len(days)} sessions.",'',
        '| Policy | Trades | Winning points | Losing points | Net points | Change vs own baseline | Winners | Losers | Flat | Closed-trade drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key in POLICIES:
        s=totals[key];parent='EXISTING' if key=='EXISTING_BASELINE_2' else key.removesuffix('_EMA10_ENTRY')
        lines.append(f"| {key} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['points']-totals[parent]['points']:+.2f} | {s['winners']} | {s['losers']} | {s['flat']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | '+' | '.join(POLICIES)+' |','|---|'+'---:|'*len(POLICIES)]
    detail=['# Signal-wise actual entry / exit / points','',WARNING,'',
        'Times IST. A dash means no actual entry from that exact setup, not proof of direct rejection. WAIT_EMA10_ENTRY retains the latest-policy candidate without time expiry until entry, qualified opposite replacement or cutoff. BLOCKED_WMA_LOCK consumes it. See entry-decisions.csv for explicit outcomes. Different setup identities can produce the same actual trade.','']
    trades=[];events=[]
    for day,v in sorted(results.items()):
        lines.append('| '+day+' | '+' | '.join(f"{stats.stats(v[k]['trades'])['points']:+.2f}" for k in POLICIES)+' |')
        identities={(t['direction'],t['signal_time']) for k in POLICIES for t in v[k]['trades']}
        for k in POLICIES:
            trades.extend(dict(t,policy=k,session_date=day) for t in v[k]['trades'])
            for e in v[k].get('policy_events',[]):
                if e['event'] not in ('EMA10_ENTRY_CHECK','COMBINED_ENTRY_DECISION','FOLLOWUP_CANDLE_CHECK','QUALIFIED_OPPOSITE_WATCH_OVERRIDE'):continue
                identities.add((e['direction'],e['setup_available']))
                events.append(dict(session_date=day,policy=k,**e))
        detail+=['','## '+day,'','| Direction | Setup available | '+' | '.join(POLICIES)+' |','|---|---|'+'---|'*len(POLICIES)]
        for side,signal in sorted(identities,key=lambda z:(z[1],z[0])):
            cells=[base.cell([t for t in v[k]['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for k in POLICIES]
            detail.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
    report=dict(model=MODEL,status='COMPLETE' if complete else 'INCOMPLETE',session_dates=days,strategy_version=version,
        coverage=coverage,provenance=provenance,comparisons=totals,warning=WARNING,
        ema10_entry_rules={key:('CLOSE_RSI40_60_SLOPE_COLOUR' if key=='FRESH_AND_EMA10_ENTRY' else 'CLOSE_AND_RSI_CROSS_45_OR_55' if key=='EXISTING_BASELINE_2' else 'FULL_CANDLE_AND_EMA_SLOPE')
            for key in ('EXISTING_EMA10_ENTRY','PREVIOUS_AND_EMA10_ENTRY','FRESH_AND_EMA10_ENTRY','EXISTING_BASELINE_2')},
        orders_sent=False,observation_only=True)
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-signal-comparison.md').write_text('\n'.join(detail)+'\n')
    validation=['# Completed five-minute EMA10 entry validation','',WARNING,'',
        'Checks below occur only after that policy fully confirms an entry. WAIT is not an executed trade. Times IST.','',
        '| Date | Policy | Setup | Decision | Direction | Candle label | Open | High | Low | Close | EMA10 | EMA10 slope | Previous RSI9 | RSI9 | Strength | Gap | Expansion | Crossed thresholds | Outcome / reason |',
        '|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|']
    for e in events:
        if e['event']!='EMA10_ENTRY_CHECK':continue
        vals=[f"{e[k]:.3f}" if e.get(k) is not None else '—' for k in ('open','high','low','close','ema10','ema10_slope','previous_rsi9','rsi9','directional_strength','directional_gap','gap_expansion')]
        outcome='PASS' if e['passed'] else 'WAIT: '+', '.join(e['reasons'])
        validation.append('| '+' | '.join([e['session_date'],e['policy'],e['setup_available'][11:16],e['time'][11:16],e['direction'],e.get('candle_label','—')[11:16]]+vals+[','.join(map(str,e.get('rsi_crossed_thresholds',[]))) or 'None',outcome])+' |')
    validation+=['','## Follow-up candle checks','','| Date | Policy | Setup | Decision | Direction | Signal close | Signal midpoint | Follow-up close | Open | Previous RSI9 | RSI9 | Colour pass | RSI direction pass | Entry route | Outcome / reason |','|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|']
    for e in events:
        if e['event']!='FOLLOWUP_CANDLE_CHECK':continue
        validation.append('| '+' | '.join(str(x) for x in (e['session_date'],e['policy'],e['setup_available'][11:16],e['time'][11:16],e['direction'],e.get('signal_close','—'),e.get('signal_midpoint','—'),e.get('close','—'),e.get('open','—'),e.get('previous_rsi9','—'),e.get('rsi9','—'),e.get('followup_colour_pass','—'),e.get('followup_rsi_direction_pass','—'),e.get('entry_confirmation_route','—'),'PASS' if e['passed'] else ', '.join(e['reasons'])))+' |')
    (output/'ema10-entry-validation.md').write_text('\n'.join(validation)+'\n')
    for name,rows in (('trades.csv',trades),('losing-trades.csv',[t for t in trades if t['points']<0]),('entry-decisions.csv',events)):
        fields=sorted({k for row in rows for k in row}) or ['session_date','policy']
        with (output/name).open('w',newline='') as f:
            writer=csv.DictWriter(f,fields);writer.writeheader()
            writer.writerows({k:json.dumps(v,default=str) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows)
    print('\n'.join(lines))
    if len(days)==1:print('\n'.join(detail));print('\n'.join(validation))
    print('SIGNAL TABLE:',output/'daily-signal-comparison.md')
    print('EMA VALIDATION:',output/'ema10-entry-validation.md')


class Checks(unittest.TestCase):
    at=datetime.fromisoformat('2026-10-16T10:03:00+05:30')
    def frame(self,**kw):
        return dict(dict(open=102,high=104,low=101,close=103,ema10=100,previous_ema10=99,
            available_at='2026-10-16T10:00:00+05:30'),**kw)
    def test_bullish_full_candle(self):self.assertTrue(frame_check('BULLISH',self.frame(),self.at)['passed'])
    def test_single_day_only(self):
        self.assertEqual(single_session('2026-10-14',['2026-10-13','2026-10-14','2026-10-15'],'2026-07-16','2026-10-16','2026-10-16'),['2026-10-14'])
    def test_single_extra_day(self):
        self.assertEqual(single_session('2026-10-16',[],'2026-07-16','2026-10-16','2026-10-16'),['2026-10-16'])
    def test_unavailable_single_day_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            single_session('2026-10-11',[],'2026-07-16','2026-10-16','2026-10-16')
    def test_out_of_range_rejected(self):
        with self.assertRaisesRegex(ValueError,'OUTSIDE'):
            single_session('2026-07-15',[],'2026-07-16','2026-10-16','2026-10-16')
    def test_noncanonical_date_rejected(self):
        with self.assertRaisesRegex(ValueError,'YYYY_MM_DD'):
            single_session('2026-8-26',[],'2026-07-16','2026-10-16','2026-10-16')
    def test_bearish_full_candle(self):self.assertTrue(frame_check('BEARISH',self.frame(ema10=105,previous_ema10=106),self.at)['passed'])
    def test_wick_fails(self):self.assertFalse(frame_check('BULLISH',self.frame(low=99),self.at)['passed'])
    def test_touch_fails(self):self.assertFalse(frame_check('BULLISH',self.frame(low=100),self.at)['passed'])
    def test_bearish_touch_fails(self):self.assertFalse(frame_check('BEARISH',self.frame(ema10=104,previous_ema10=105),self.at)['passed'])
    def test_falling_ema_fails_bullish(self):self.assertFalse(frame_check('BULLISH',self.frame(previous_ema10=101),self.at)['passed'])
    def test_flat_ema_fails(self):self.assertFalse(frame_check('BULLISH',self.frame(previous_ema10=100),self.at)['passed'])
    def test_future_rejected(self):
        with self.assertRaises(ValueError):frame_check('BULLISH',self.frame(available_at='2026-10-16T10:05:00+05:30'),self.at)
    def test_stale_rejected(self):
        with self.assertRaises(ValueError):frame_check('BULLISH',self.frame(available_at='2026-10-16T09:55:00+05:30'),self.at)
    def test_missing_waits(self):self.assertFalse(frame_check('BULLISH',None,self.at)['passed'])
    def harness(self,passed=True,veto=False,frame=None,rule='FULL_CANDLE'):
        at=self.at
        class Base:
            def __init__(self):
                self.pending={'BULLISH':dict(available=at-timedelta(minutes=3),armed_at=at-timedelta(minutes=2),event=None)}
                self.owner='NONE';self.active=None;self.watch_side='BULLISH';self.watch_at=at-timedelta(minutes=3)
            def can_signal(self,*a):return True
            def evaluate(self,**kw):
                self.previous=kw['minute']
                if not passed:return [],[]
                p=self.pending.pop('BULLISH')
                if veto:return [],[]
                self.owner='BULLISH';self.active=True;self.watch_side=None;self.watch_at=None
                return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[])]
            def close(self):return 'ORIGINAL_EXIT'
        return entry_gate(Base,{at.replace(minute=0):self.frame(low=99) if frame is None else frame},rule=rule)()
    def test_failed_gate_restores_original_candidate_and_keeps_history(self):
        g=self.harness();original=dict(g.pending['BULLISH']);minute=self.at-timedelta(minutes=1)
        entries,checks=g.evaluate(minute=minute)
        self.assertFalse(entries);self.assertEqual(g.pending['BULLISH'],original)
        self.assertEqual(g.owner,'NONE');self.assertIsNone(g.active);self.assertEqual(g.previous,minute)
        self.assertEqual(checks[0]['status'],'EMA10_ENTRY_WAIT')
    def test_no_baseline_confirmation_no_ema_entry(self):
        g=self.harness(passed=False);self.assertEqual(g.evaluate(minute=self.at-timedelta(minutes=1)),([],[]));self.assertFalse(g.policy_events)
    def test_wma_veto_not_resurrected(self):
        g=self.harness(veto=True);g.evaluate(minute=self.at-timedelta(minutes=1));self.assertFalse(g.pending);self.assertFalse(g.policy_events)
    def test_exit_unmodified(self):self.assertEqual(self.harness().close(),'ORIGINAL_EXIT')
    def test_new_bullish_close_allows_lower_wick(self):
        ev=frame_check('BULLISH',self.frame(low=99),self.at,rule='BULLISH_CLOSE')
        self.assertTrue(ev['passed']);self.assertFalse(ev['entire_candle_pass'])
    def test_new_bullish_close_allows_falling_ema(self):
        ev=frame_check('BULLISH',self.frame(previous_ema10=101),self.at,rule='BULLISH_CLOSE')
        self.assertTrue(ev['passed']);self.assertFalse(ev['slope_required']);self.assertFalse(ev['slope_pass'])
    def test_new_bullish_close_equality_waits(self):
        self.assertFalse(frame_check('BULLISH',self.frame(ema10=103),self.at,rule='BULLISH_CLOSE')['passed'])
    def test_new_bullish_close_below_waits(self):
        self.assertFalse(frame_check('BULLISH',self.frame(ema10=104),self.at,rule='BULLISH_CLOSE')['passed'])
    def test_new_bearish_rule_unchanged(self):
        for frame in (self.frame(ema10=105,previous_ema10=106),self.frame(ema10=103,previous_ema10=104),self.frame(ema10=105,previous_ema10=104)):
            a=frame_check('BEARISH',frame,self.at,rule='BULLISH_CLOSE')
            b=frame_check('BEARISH',frame,self.at,rule='FULL_CANDLE')
            self.assertEqual((a['passed'],a['reasons']),(b['passed'],b['reasons']))
    def test_new_gate_accepts_confirmed_bullish_with_lower_wick(self):
        g=self.harness(rule='BULLISH_CLOSE');self.assertTrue(g.evaluate(minute=self.at-timedelta(minutes=1))[0])
    def test_new_ema_permission_cannot_create_confirmation(self):
        g=self.harness(passed=False,rule='BULLISH_CLOSE');self.assertFalse(g.evaluate(minute=self.at-timedelta(minutes=1))[0]);self.assertEqual(g.owner,'NONE')
    def test_directional_bearish_close_allows_upper_wick(self):
        ev=frame_check('BEARISH',self.frame(ema10=103.5,previous_ema10=104),self.at,rule='CLOSE_BOTH')
        self.assertTrue(ev['passed']);self.assertFalse(ev['entire_candle_pass'])
    def test_directional_bearish_close_allows_rising_ema(self):
        ev=frame_check('BEARISH',self.frame(ema10=105,previous_ema10=104),self.at,rule='CLOSE_BOTH')
        self.assertTrue(ev['passed']);self.assertFalse(ev['slope_required']);self.assertFalse(ev['slope_pass'])
    def test_directional_bearish_equality_waits(self):
        ev=frame_check('BEARISH',self.frame(ema10=103),self.at,rule='CLOSE_BOTH')
        self.assertFalse(ev['passed']);self.assertIn('BEARISH_CLOSE_NOT_BELOW_EMA10',ev['reasons'])
    def test_directional_bearish_close_above_waits(self):
        self.assertFalse(frame_check('BEARISH',self.frame(),self.at,rule='CLOSE_BOTH')['passed'])
    def test_directional_bullish_rule_matches_previous_update(self):
        for frame in (self.frame(low=99),self.frame(previous_ema10=101),self.frame(ema10=103)):
            a=frame_check('BULLISH',frame,self.at,rule='CLOSE_BOTH')
            b=frame_check('BULLISH',frame,self.at,rule='BULLISH_CLOSE')
            self.assertEqual((a['passed'],a['reasons']),(b['passed'],b['reasons']))
    def test_scoped_routing_only_two_policies_use_cross_rule(self):
        source=inspect.getsource(add_variants)
        self.assertIn("rule='CLOSE_RSI40_60_SLOPE_COLOUR' if key=='FRESH_AND' else 'FULL_CANDLE'",source)
        self.assertIn("baseline2_gate(engine,frames,rule='CLOSE_AND_RSI_CROSS')",source)
        self.assertNotIn("rule='CLOSE_BOTH'",source)
        self.assertNotIn("rule='BULLISH_CLOSE'",source)
    def cross_frame(self,previous=44,current=46,**kw):
        values=dict(previous_rsi9=previous,rsi9=current,rsi_available_at=kw.get('available_at','2026-10-16T10:00:00+05:30'))
        values.update(kw)
        return self.frame(**values)
    def test_followup_gate_waits_then_enters_or_consumes_failure(self):
        for close,expected in [(104,True),(102,False)]:
            at=self.at.replace(minute=0)
            class Base:
                def __init__(self):
                    self.pending={'BULLISH':dict(available=at,armed_at=None)}
                    self.owner='NONE';self.active=None;self.watch_side=None;self.watch_at=None
                def can_signal(self,*args):return True
                def evaluate(self,**kw):
                    pending=self.pending.pop('BULLISH');self.owner='BULLISH';self.active=True
                    return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=pending['available'].isoformat(),reasons=[])]
            frames={at:self.cross_frame(),at+timedelta(minutes=5):self.cross_frame(close=close,available_at=(at+timedelta(minutes=5)).isoformat())}
            g=entry_gate(Base,frames,rule='CLOSE_RSI_SLOPE_COLOUR',followup=True)()
            entries,checks=g.evaluate(minute=at-timedelta(minutes=1))
            self.assertFalse(entries);self.assertEqual(g.owner,'NONE');self.assertIn('BULLISH',g.pending)
            entries,checks=g.evaluate(minute=at+timedelta(minutes=4))
            self.assertEqual(bool(entries),expected);self.assertIsNone(g.followup_signal)
            if not expected:self.assertEqual(g.owner,'NONE');self.assertNotIn('BULLISH',g.pending)
    def test_followup_cancellation_cannot_restore_signal(self):
        at=self.at.replace(minute=0)
        g=self.harness(passed=False)
        g.followup_signal=dict(direction='BULLISH',setup_available='different',time=at,due=at+timedelta(minutes=5),close=103,midpoint=103)
        g.evaluate(minute=at+timedelta(minutes=4))
        self.assertIsNone(g.followup_signal);self.assertEqual(g.owner,'NONE')
    def test_followup_failed_close_requests_same_boundary_fresh_pass(self):
        at=self.at.replace(minute=0)
        class Base:
            def __init__(self):
                self.pending={'BULLISH':dict(available=at,armed_at=None)}
                self.owner='NONE';self.active=None;self.watch_side=None;self.watch_at=None
            def can_signal(self,*args):return True
            def evaluate(self,**kw):
                p=self.pending.pop('BULLISH');self.owner='BULLISH';self.active=True
                return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[])]
        next_at=at+timedelta(minutes=5)
        # Failed follow-up close 102 < original 103, but its own RSI cross,
        # green candle and rising EMA all qualify as a NEW bullish signal.
        frames={at:self.cross_frame(),next_at:self.cross_frame(open=101,close=102,available_at=next_at.isoformat(),rsi_available_at=next_at.isoformat())}
        g=entry_gate(Base,frames,rule='CLOSE_RSI_SLOPE_COLOUR',followup=True)()
        self.assertFalse(g.evaluate(minute=at-timedelta(minutes=1))[0])
        self.assertFalse(g.evaluate(minute=next_at-timedelta(minutes=1))[0])
        self.assertEqual(g.followup_failed_at,next_at);self.assertNotIn('BULLISH',g.pending)
        g.pending['BULLISH']=dict(available=next_at,armed_at=None)
        self.assertFalse(g.evaluate(minute=next_at-timedelta(minutes=1))[0])
        self.assertEqual(g.followup_signal['close'],102)
        self.assertEqual(g.followup_signal['time'],next_at)
        self.assertEqual(g.followup_signal['due'],next_at+timedelta(minutes=5))
        self.assertEqual(g.followup_signal['setup_available'],next_at.isoformat())
        self.assertEqual(g.owner,'NONE')
    def test_followup_retry_replay_is_one_pass_and_scoped(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_and_fresh_setup_last10_research as fresh
        original=inspect.getsource(engine.replay)
        ordinary=inspect.getsource(direct_fresh_replay(engine,fresh))
        changed=inspect.getsource(direct_fresh_replay(engine,fresh,retry_followup=True))
        self.assertNotIn('FRESH_SETUP_AFTER_FOLLOWUP_FAILURE',ordinary)
        self.assertEqual(changed.count('FRESH_SETUP_AFTER_FOLLOWUP_FAILURE'),1)
        self.assertIn('cc+=retry_checks',changed)
        self.assertIn("at.strftime('%H:%M')<'14:55'",changed)
        self.assertEqual(original,inspect.getsource(engine.replay))
    def test_followup_price_permission_bypasses_strength_gap_only(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=datetime.fromisoformat('2026-10-16T10:05:00+05:30')
        g=direct_five_base(engine.WmaGapGate)(opposite_switch=True)
        ev=engine.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at-timedelta(minutes=5),None,'IDLE','ARMED',details={})
        g.signal(ev,at-timedelta(minutes=5));g.followup_price_permission=('BULLISH',at)
        snap=SimpleNamespace(ready=True,wma21_rsi=50,ema3_rsi=49,rsi9=48)
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1),current=snap,reference=snap,price=100)
        self.assertTrue(entries);self.assertFalse(checks[0]['wma_threshold_pass']);self.assertFalse(checks[0]['gap_positive_pass'])
    def test_followup_price_permission_does_not_bypass_cutoff(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=datetime.fromisoformat('2026-10-16T14:55:00+05:30')
        g=direct_five_base(engine.WmaGapGate)(opposite_switch=True)
        ev=engine.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at-timedelta(minutes=5),None,'IDLE','ARMED',details={})
        g.signal(ev,at-timedelta(minutes=5));g.followup_price_permission=('BULLISH',at)
        snap=SimpleNamespace(ready=True,wma21_rsi=50,ema3_rsi=49,rsi9=48)
        self.assertFalse(g.evaluate(minute=at-timedelta(minutes=1),current=snap,reference=snap,price=100)[0])
    def test_qualified_opposite_watch_requires_all_signal_checks(self):
        at=self.at.replace(minute=0)
        import hilega_wma_threshold_only_oct14_research as threshold
        import hilega_post_entry_wma_lock_today_research as lock
        class Base:
            def __init__(self):
                self.owner='NONE';self.locked=False;self.watch_side='BULLISH';self.watch_at=at-timedelta(minutes=5)
                self.policy_events=[];self.direction_lock=threshold.threshold_lock_class(lock.DirectionLock)();self.recorded=[]
            def can_signal(self,side,time):return self.watch_side==side
            def signal(self,event,available):self.recorded.append(event);self.watch_side=event
        f=self.cross_frame(previous=53,current=44,open=103,close=102,ema10=105,previous_ema10=106,
            ema3_rsi=48,wma21_rsi=52,previous_ema3_rsi=52,previous_wma21_rsi=53)
        g=qualified_opposite_watch_gate(Base,{at:f},lambda event:event)()
        self.assertTrue(g.can_signal('BEARISH',at));self.assertEqual(g.watch_side,'BULLISH')
        g.signal('BEARISH',at);self.assertEqual(g.recorded,['BEARISH']);self.assertEqual(g.watch_side,'BEARISH')
        self.assertEqual(g.policy_events[-1]['event'],'QUALIFIED_OPPOSITE_WATCH_OVERRIDE')
        self.assertEqual(g.policy_events[-1]['setup_available'],at.isoformat())
        for changes in [dict(previous_wma21_rsi=52.2),dict(previous_ema3_rsi=47),dict(close=104,open=103),dict(previous_rsi9=42)]:
            other=dict(f,**changes);h=qualified_opposite_watch_gate(Base,{at:other},lambda event:event)()
            self.assertFalse(h.can_signal('BEARISH',at));h.signal('BEARISH',at);self.assertFalse(h.recorded)
    def test_single_followup_failure_discards_reference_and_allows_fresh_same_candle(self):
        at=self.at.replace(minute=0)
        class Base:
            def __init__(self):
                self.pending={'BULLISH':dict(available=at,armed_at=None)}
                self.owner='NONE';self.active=None;self.watch_side=None;self.watch_at=None;self.locked=False
            def can_signal(self,*args):return True
            def evaluate(self,**kwargs):
                p=self.pending.pop('BULLISH');self.owner='BULLISH';self.active=True
                return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[],wma_threshold_pass=True,gap_positive_pass=True,gap_expanding_pass=True)]
        later=at+timedelta(minutes=5);last=at+timedelta(minutes=10)
        # Price fails the OLD close and midpoint, but this green rising-RSI candle
        # may qualify independently when fresh strength/gap checks pass.
        frames={at:self.cross_frame(open=101,close=103,ema3_rsi=43,wma21_rsi=42),
            later:self.cross_frame(previous=46,current=48,open=101,close=102,ema3_rsi=45,wma21_rsi=44,available_at=later.isoformat()),
            last:self.cross_frame(previous=48,current=50,open=102,close=104,ema3_rsi=47,wma21_rsi=46,available_at=last.isoformat())}
        # Force old follow-up colour failure initially, to test no strength bypass.
        frames[later]['open']=103
        g=entry_gate(Base,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,reset_reference_only=True,until_opposite=True)()
        self.assertFalse(g.evaluate(minute=at-timedelta(minutes=1))[0])
        self.assertFalse(g.evaluate(minute=later-timedelta(minutes=1))[0])
        self.assertIsNone(g.followup_signal);self.assertIn('BULLISH',g.pending)
        self.assertEqual(g.pending['BULLISH']['available'],at);self.assertEqual(g.followup_failed_at,later)
        # Same-boundary fresh check fails colour; it cannot reuse the old signal.
        self.assertFalse(g.evaluate(minute=later-timedelta(minutes=1))[0]);self.assertIsNone(g.followup_signal)
        # Now provide a qualifying fresh candle and establish a NEW reference.
        frames[later]['open']=101
        self.assertFalse(g.evaluate(minute=later-timedelta(minutes=1))[0])
        self.assertEqual(g.followup_signal['time'],later);self.assertEqual(g.followup_signal['close'],102)
        self.assertEqual(g.followup_signal['due'],last)
        self.assertTrue(g.evaluate(minute=last-timedelta(minutes=1))[0])
    def test_signal_rsi40_60_thresholds_and_direction(self):
        for side,previous,current,passed in [('BULLISH',39,41,True),('BULLISH',39,40,False),('BULLISH',43,42,False),('BEARISH',62,59,True),('BEARISH',62,60,False),('BEARISH',57,59,False)]:
            kw=dict(open=101,close=103,ema10=100,previous_ema10=99) if side=='BULLISH' else dict(open=103,close=102,ema10=105,previous_ema10=106)
            ev=frame_check(side,self.cross_frame(previous=previous,current=current,**kw),self.at,rule='CLOSE_RSI40_60_SLOPE_COLOUR')
            self.assertEqual(ev['passed'],passed)
    def test_continued_followup_retains_original_reference_then_enters(self):
        at=self.at.replace(minute=0)
        class Base:
            def __init__(self):
                self.pending={'BEARISH':dict(available=at,armed_at=None)}
                self.owner='NONE';self.active=None;self.watch_side=None;self.watch_at=None;self.locked=False
            def can_signal(self,*args):return True
            def evaluate(self,**kw):
                p=self.pending.pop('BEARISH');self.owner='BEARISH';self.active=True
                return ['entry'],[dict(direction='BEARISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[],wma_threshold_pass=True,gap_positive_pass=True,gap_expanding_pass=True)]
        f0=self.cross_frame(previous=64,current=59,open=103,close=102,ema10=105,previous_ema10=106)
        later=at+timedelta(minutes=5);last=at+timedelta(minutes=10)
        f1=self.cross_frame(previous=59,current=62,open=102,close=103,available_at=later.isoformat())
        f2=self.cross_frame(previous=62,current=55,open=103,close=101,available_at=last.isoformat())
        g=entry_gate(Base,{at:f0,later:f1,last:f2},rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,continue_waiting=True)()
        self.assertFalse(g.evaluate(minute=at-timedelta(minutes=1))[0])
        original=dict(g.followup_signal)
        self.assertFalse(g.evaluate(minute=later-timedelta(minutes=1))[0]);self.assertEqual(g.owner,'NONE')
        self.assertEqual(g.followup_signal['due'],last)
        for key in ('close','midpoint','time','setup_available'):self.assertEqual(g.followup_signal[key],original[key])
        self.assertEqual(g.pending['BEARISH']['available'],at);self.assertIsNone(g.followup_failed_at)
        self.assertTrue(g.policy_events[-1]['continued_wait'])
        self.assertTrue(g.evaluate(minute=last-timedelta(minutes=1))[0]);self.assertEqual(g.owner,'BEARISH')
    def test_continued_followup_requires_all_three_fresh_checks(self):
        class Base:
            def __init__(self):self.pending={};self.locked=False
        g=entry_gate(Base,{},continue_waiting=True)();at=self.at
        waiting=dict(direction='BEARISH',setup_available=at.isoformat(),time=at,due=at+timedelta(minutes=5),close=100,midpoint=101)
        candidate=dict(available=at)
        keys=('wma_threshold_pass','gap_positive_pass','gap_expanding_pass')
        for failed in keys:
            checks={k:k!=failed for k in keys}
            self.assertFalse(g.retain_followup(waiting,checks,at+timedelta(minutes=5),candidate))
        self.assertFalse(g.retain_followup(waiting,{k:True for k in keys},at+timedelta(minutes=5),None))
        g.locked=True
        self.assertFalse(g.retain_followup(waiting,{k:True for k in keys},at+timedelta(minutes=5),candidate))
    def test_no_lock_watch_override_does_not_require_direction_lock(self):
        at=self.at.replace(minute=0)
        class Base:
            def __init__(self):
                self.owner='NONE';self.locked=False;self.watch_side='BULLISH';self.watch_at=at
            def can_signal(self,*args):return False
            def signal(self,event,available):self.watch_side=event
        f=self.cross_frame(previous=53,current=44,open=103,close=102,ema10=105,previous_ema10=106,
            ema3_rsi=48,wma21_rsi=52,previous_ema3_rsi=52,previous_wma21_rsi=53)
        g=qualified_opposite_watch_gate(Base,{at:f},lambda event:event,require_wma_permission=False)()
        self.assertFalse(hasattr(g,'direction_lock'))
        self.assertTrue(g.can_signal('BEARISH',at));g.signal('BEARISH',at)
        self.assertEqual(g.watch_side,'BEARISH')
        f['previous_wma21_rsi']=52.2
        self.assertFalse(g.qualifies('BEARISH',at))
    def test_watch_override_cannot_enter_midminute_or_while_position_active(self):
        at=self.at.replace(minute=0)
        class Base:
            def __init__(self):self.owner='BULLISH';self.locked=False;self.watch_side='BULLISH';self.watch_at=at
            def can_signal(self,*args):return False
        g=qualified_opposite_watch_gate(Base,{},lambda event:event)()
        self.assertFalse(g.can_signal('BEARISH',at));g.owner='NONE'
        self.assertFalse(g.can_signal('BEARISH',at+timedelta(minutes=1)))
    def test_continued_rsi_both_directions(self):
        for side,a,b,expected in [('BULLISH',46,50,True),('BULLISH',56,60,True),('BULLISH',44,46,True),('BEARISH',44.570,39.080,True),('BEARISH',53,50,True),('BEARISH',56,54,True),('BULLISH',60,58,False),('BEARISH',39,42,False),('BULLISH',50,50,False),('BEARISH',50,50,False),('BULLISH',44,45,False),('BEARISH',56,55,False)]:
            f=self.cross_frame(previous=a,current=b,open=102 if side=='BULLISH' else 103,close=103 if side=='BULLISH' else 102,ema10=100 if side=='BULLISH' else 105,previous_ema10=99 if side=='BULLISH' else 106)
            ev=frame_check(side,f,self.at,rule='CLOSE_RSI_CONTINUATION_SLOPE_COLOUR')
            self.assertEqual(ev['passed'],expected);self.assertFalse(ev['rsi_cross_required'])
    def test_continuation_preserves_other_signal_checks(self):
        for changes in [dict(ema10=104,previous_ema10=103),dict(previous_ema10=101),dict(open=104)]:
            self.assertFalse(frame_check('BULLISH',self.cross_frame(previous=46,current=50,**changes),self.at,rule='CLOSE_RSI_CONTINUATION_SLOPE_COLOUR')['passed'])
    def test_continuation_baseline2_cross_unchanged(self):
        f=self.cross_frame(previous=46,current=50)
        self.assertTrue(frame_check('BULLISH',f,self.at,rule='CLOSE_RSI_CONTINUATION_SLOPE_COLOUR')['passed'])
        self.assertFalse(frame_check('BULLISH',f,self.at,rule='CLOSE_AND_RSI_CROSS')['passed'])
    def test_midpoint_only_pass_bullish_and_bearish(self):
        at=self.at.replace(minute=5)
        for side,signal_close,midpoint,close in [('BULLISH',110,105,107),('BEARISH',100,105,103)]:
            signal=dict(time=at-timedelta(minutes=5),due=at,close=signal_close,midpoint=midpoint)
            ev=followup_check(side,signal,dict(close=close,available_at=at.isoformat()),at)
            self.assertTrue(ev['passed']);self.assertFalse(ev['signal_close_comparison_pass'])
            self.assertTrue(ev['signal_midpoint_comparison_pass']);self.assertEqual(ev['confirmation_route'],'MIDPOINT')
    def test_midpoint_equality_does_not_pass_when_close_route_fails(self):
        at=self.at.replace(minute=5)
        for side,signal_close in [('BULLISH',110),('BEARISH',100)]:
            signal=dict(time=at-timedelta(minutes=5),due=at,close=signal_close,midpoint=105)
            self.assertFalse(followup_check(side,signal,dict(close=105,available_at=at.isoformat()),at)['passed'])
    def test_close_or_midpoint_is_or_not_and(self):
        at=self.at.replace(minute=5)
        for side,close in [('BULLISH',104),('BEARISH',102)]:
            signal=dict(time=at-timedelta(minutes=5),due=at,close=103,midpoint=105 if side=='BULLISH' else 101)
            ev=followup_check(side,signal,dict(close=close,available_at=at.isoformat()),at)
            self.assertTrue(ev['passed']);self.assertEqual(ev['confirmation_route'],'SIGNAL_CLOSE')
    def test_followup_colour_and_rsi_are_mandatory_both_directions(self):
        at=self.at.replace(minute=5)
        signal=dict(time=at-timedelta(minutes=5),due=at,close=103,midpoint=103)
        for side,close,opening,previous,current in [('BULLISH',104,103,45,46),('BEARISH',102,103,55,54)]:
            frame=dict(open=opening,close=close,previous_rsi9=previous,rsi9=current,available_at=at.isoformat(),rsi_available_at=at.isoformat())
            self.assertTrue(followup_check(side,signal,frame,at,require_direction=True)['passed'])
            for change in (dict(open=close),dict(open=close+1 if side=='BULLISH' else close-1),dict(rsi9=previous),dict(rsi9=previous-1 if side=='BULLISH' else previous+1),dict(rsi_available_at=signal['time'].isoformat())):
                ev=followup_check(side,signal,dict(frame,**change),at,require_direction=True)
                self.assertFalse(ev['passed'])
                structural=[r for r in ev['reasons'] if not r.startswith('FOLLOWUP_CLOSE_NOT_')]
                self.assertTrue(structural) # Fresh strength/gap success cannot remove this veto.
    def test_followup_fresh_checks_cannot_bypass_wrong_colour_or_rsi(self):
        at=self.at.replace(minute=0)
        for change in (dict(open=105),dict(previous_rsi9=47,rsi9=46)):
            class Base:
                def __init__(self):
                    self.pending={'BULLISH':dict(available=at,armed_at=None)}
                    self.owner='NONE';self.active=None;self.watch_side=None;self.watch_at=None
                def can_signal(self,*args):return True
                def evaluate(self,**kw):
                    p=self.pending.pop('BULLISH');self.owner='BULLISH';self.active=True
                    return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[],wma_threshold_pass=True,gap_positive_pass=True,gap_expanding_pass=True)]
            later=at+timedelta(minutes=5)
            frame=self.cross_frame(close=104,available_at=later.isoformat(),**change)
            g=entry_gate(Base,{at:self.cross_frame(),later:frame},rule='CLOSE_RSI_SLOPE_COLOUR',followup=True)()
            self.assertFalse(g.evaluate(minute=at-timedelta(minutes=1))[0])
            self.assertFalse(g.evaluate(minute=later-timedelta(minutes=1))[0])
            self.assertEqual(g.owner,'NONE');self.assertNotIn('BULLISH',g.pending)
    def test_followup_option_a_both_directions_and_equality(self):
        at=self.at.replace(minute=5)
        signal=dict(time=at-timedelta(minutes=5),due=at,close=103,midpoint=103)
        for side,close,expected in [('BULLISH',104,True),('BULLISH',103,False),('BULLISH',102,False),('BEARISH',102,True),('BEARISH',103,False),('BEARISH',104,False)]:
            self.assertEqual(followup_check(side,signal,dict(close=close,available_at=at.isoformat()),at)['passed'],expected)
    def test_followup_missing_stale_and_late_fail(self):
        at=self.at.replace(minute=5);signal=dict(time=at-timedelta(minutes=5),due=at,close=103,midpoint=103)
        self.assertFalse(followup_check('BULLISH',signal,None,at)['passed'])
        self.assertFalse(followup_check('BULLISH',signal,dict(close=104,available_at=signal['time'].isoformat()),at)['passed'])
        later=at+timedelta(minutes=5)
        self.assertFalse(followup_check('BULLISH',signal,dict(close=104,available_at=later.isoformat()),later)['passed'])
    def test_followup_cutoff_fails(self):
        at=self.at.replace(hour=14,minute=55);signal=dict(time=at-timedelta(minutes=5),due=at,close=103,midpoint=103)
        self.assertFalse(followup_check('BULLISH',signal,dict(close=104,available_at=at.isoformat()),at)['passed'])
    def test_slope_colour_bullish_pass(self):
        self.assertTrue(frame_check('BULLISH',self.cross_frame(),self.at,rule='CLOSE_RSI_SLOPE_COLOUR')['passed'])
    def test_slope_colour_bearish_pass(self):
        f=self.cross_frame(previous=56,current=54,open=103,close=102,ema10=105,previous_ema10=106)
        self.assertTrue(frame_check('BEARISH',f,self.at,rule='CLOSE_RSI_SLOPE_COLOUR')['passed'])
    def test_slope_colour_wrong_and_flat_slope_rejected_both_directions(self):
        for side,previous,current,ema in [('BULLISH',44,46,100),('BEARISH',56,54,105)]:
            for prior in ([100,101] if side=='BULLISH' else [105,104]):
                f=self.cross_frame(previous=previous,current=current,open=102 if side=='BULLISH' else 103,close=103 if side=='BULLISH' else 102,ema10=ema,previous_ema10=prior)
                ev=frame_check(side,f,self.at,rule='CLOSE_RSI_SLOPE_COLOUR')
                self.assertFalse(ev['passed']);self.assertFalse(ev['slope_pass'])
    def test_slope_colour_wrong_colour_and_doji_rejected(self):
        for side in ('BULLISH','BEARISH'):
            for opening in ([103,104] if side=='BULLISH' else [102,101]):
                f=self.cross_frame(previous=44 if side=='BULLISH' else 56,current=46 if side=='BULLISH' else 54,open=opening,close=103 if side=='BULLISH' else 102,ema10=100 if side=='BULLISH' else 105,previous_ema10=99 if side=='BULLISH' else 106)
                ev=frame_check(side,f,self.at,rule='CLOSE_RSI_SLOPE_COLOUR')
                self.assertFalse(ev['passed']);self.assertFalse(ev['candle_colour_pass'])
    def test_slope_colour_still_requires_cross_and_price(self):
        for changes in [dict(previous=56,current=58),dict(ema10=104,previous_ema10=103)]:
            self.assertFalse(frame_check('BULLISH',self.cross_frame(**changes),self.at,rule='CLOSE_RSI_SLOPE_COLOUR')['passed'])
    def test_rsi_bullish_either_threshold(self):
        self.assertEqual(rsi_cross('BULLISH',44,46)['rsi_crossed_thresholds'],[45])
        self.assertEqual(rsi_cross('BULLISH',54,56)['rsi_crossed_thresholds'],[55])
        self.assertEqual(rsi_cross('BULLISH',44,56)['rsi_crossed_thresholds'],[45,55])
    def test_rsi_bearish_either_threshold(self):
        self.assertEqual(rsi_cross('BEARISH',56,54)['rsi_crossed_thresholds'],[55])
        self.assertEqual(rsi_cross('BEARISH',46,44)['rsi_crossed_thresholds'],[45])
        self.assertEqual(rsi_cross('BEARISH',56,44)['rsi_crossed_thresholds'],[45,55])
    def test_rsi_current_equality_is_not_cross(self):
        for side,a,b in [('BULLISH',44,45),('BULLISH',54,55),('BEARISH',56,55),('BEARISH',46,45)]:
            self.assertFalse(rsi_cross(side,a,b)['rsi_cross_pass'])
    def test_rsi_departure_from_equal_threshold_is_cross(self):
        self.assertTrue(rsi_cross('BULLISH',45,46)['rsi_cross_pass'])
        self.assertTrue(rsi_cross('BEARISH',55,54)['rsi_cross_pass'])
    def test_rsi_rising_already_above_is_not_cross(self):
        self.assertFalse(rsi_cross('BULLISH',56,58)['rsi_cross_pass'])
        self.assertFalse(rsi_cross('BEARISH',44,42)['rsi_cross_pass'])
    def test_cross_direction_must_agree(self):
        self.assertFalse(rsi_cross('BULLISH',56,54)['rsi_cross_pass'])
        self.assertFalse(rsi_cross('BEARISH',44,46)['rsi_cross_pass'])
    def test_close_and_cross_both_pass_with_wrong_wick_and_slope(self):
        ev=frame_check('BULLISH',self.cross_frame(low=99,previous_ema10=101),self.at,rule='CLOSE_AND_RSI_CROSS')
        self.assertTrue(ev['passed']);self.assertFalse(ev['entire_candle_pass']);self.assertFalse(ev['slope_pass'])
    def test_close_pass_without_cross_waits(self):
        self.assertFalse(frame_check('BULLISH',self.cross_frame(previous=56,current=58),self.at,rule='CLOSE_AND_RSI_CROSS')['passed'])
    def test_cross_pass_without_correct_close_waits(self):
        self.assertFalse(frame_check('BULLISH',self.cross_frame(ema10=104),self.at,rule='CLOSE_AND_RSI_CROSS')['passed'])
    def test_bearish_close_and_down_cross(self):
        self.assertTrue(frame_check('BEARISH',self.cross_frame(previous=56,current=54,ema10=103.5,previous_ema10=103),self.at,rule='CLOSE_AND_RSI_CROSS')['passed'])
    def test_missing_rsi_waits(self):
        ev=frame_check('BULLISH',self.frame(),self.at,rule='CLOSE_AND_RSI_CROSS')
        self.assertFalse(ev['passed']);self.assertIn('COMPLETED_RSI_CROSS_EVIDENCE_MISSING',ev['reasons'])
    def test_invalid_rsi_rejected_as_unavailable(self):
        for v in (float('nan'),float('inf'),True,-1,101,None):self.assertFalse(rsi_cross('BULLISH',44,v)['rsi_evidence_available'])
    def test_rsi_and_ema_must_use_same_completed_boundary(self):
        frame=self.cross_frame();frame['rsi_available_at']='2026-10-16T10:05:00+05:30'
        with self.assertRaisesRegex(ValueError,'BOUNDARY_MISMATCH'):frame_check('BULLISH',frame,self.at,rule='CLOSE_AND_RSI_CROSS')
    def test_new_bar_without_new_cross_cannot_reuse_old_cross(self):
        a=self.cross_frame();self.assertTrue(frame_check('BULLISH',a,self.at,rule='CLOSE_AND_RSI_CROSS')['passed'])
        a.update(previous_rsi9=46,rsi9=47,available_at='2026-10-16T10:05:00+05:30',rsi_available_at='2026-10-16T10:05:00+05:30')
        self.assertFalse(frame_check('BULLISH',a,self.at+timedelta(minutes=5),rule='CLOSE_AND_RSI_CROSS')['passed'])
    def test_cross_does_not_bypass_missing_baseline_confirmation(self):
        g=self.harness(passed=False,frame=self.cross_frame(),rule='CLOSE_AND_RSI_CROSS')
        self.assertFalse(g.evaluate(minute=self.at-timedelta(minutes=1))[0]);self.assertEqual(g.owner,'NONE')
    def test_cross_does_not_bypass_wma_lock_veto(self):
        g=self.harness(veto=True,frame=self.cross_frame(),rule='CLOSE_AND_RSI_CROSS')
        self.assertFalse(g.evaluate(minute=self.at-timedelta(minutes=1))[0]);self.assertFalse(g.pending)
    def test_cross_permission_enters_only_after_baseline_pass(self):
        g=self.harness(frame=self.cross_frame(low=99),rule='CLOSE_AND_RSI_CROSS')
        self.assertTrue(g.evaluate(minute=self.at-timedelta(minutes=1))[0])
    def test_completed_rsi_previous_uses_recorded_5m_change(self):
        at=self.at.replace(minute=0);frames={at:self.frame()}
        rows=dict(audit=[dict(checkpoint=at.isoformat(),completed_5m_indicators=dict(rsi9=46),five_minute_changes=dict(rsi9=2))])
        attach_completed_rsi(frames,rows,datetime.fromisoformat)
        self.assertEqual(frames[at]['previous_rsi9'],44);self.assertEqual(frames[at]['rsi9'],46)
    def direct_harness(self,strength=1,gap=2,no_expiry=False):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        g=direct_five_base(engine.WmaGapGate,no_expiry=no_expiry)(opposite_switch=True)
        event=engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        reference=SimpleNamespace(ready=True,wma21_rsi=50,ema3_rsi=49,rsi9=48)
        wma=50-strength
        current=SimpleNamespace(ready=True,wma21_rsi=wma,ema3_rsi=wma-gap,rsi9=wma-gap-1)
        def tick(offset=0,snap=current):
            return g.evaluate(minute=at+timedelta(minutes=offset-1),current=snap,reference=reference,price=100)
        return g,tick,at,engine
    def test_direct5m_enters_on_setup_boundary_without_persistence(self):
        g,tick,_,_=self.direct_harness();entries,checks=tick()
        self.assertTrue(entries);self.assertFalse(checks[0]['persistence_pass']);self.assertFalse(checks[0]['persistence_required'])
        self.assertEqual(checks[0]['previous_gap'],1);self.assertEqual(checks[0]['gap_delta'],1)
    def test_direct5m_strength_still_required(self):
        g,tick,_,_=self.direct_harness(strength=.74)
        entries,checks=tick();self.assertFalse(entries);self.assertIn('WMA_THRESHOLD_NOT_MET',checks[0]['reasons'])
    def test_direct5m_expansion_still_required(self):
        g,tick,_,_=self.direct_harness(gap=1)
        entries,checks=tick();self.assertFalse(entries);self.assertFalse(checks[0]['gap_expanding_pass'])
    def test_direct5m_no_entry_between_boundaries(self):
        g,tick,_,_=self.direct_harness();self.assertEqual(tick(1),([],[]));self.assertEqual(g.owner,'NONE')
    def test_direct5m_reference_ignores_intermediate_minute(self):
        g,tick,_,_=self.direct_harness()
        tick(4,SimpleNamespace(ready=True,wma21_rsi=49,ema3_rsi=30,rsi9=29))
        entries,checks=tick(5);self.assertTrue(entries);self.assertEqual(checks[0]['previous_gap'],1)
    def test_direct5m_original_ten_minute_expiry_retained(self):
        g,tick,_,_=self.direct_harness(gap=1);tick();tick(5);tick(10);tick(11)
        self.assertFalse(g.pending);self.assertFalse(tick(15)[0])
    def test_no_expiry_survives_between_boundaries_and_old_age(self):
        g,tick,at,engine=self.direct_harness(strength=.2,no_expiry=True)
        for offset in (0,5,10,11,15,20,25):
            self.assertFalse(tick(offset)[0]);self.assertEqual(g.pending['BEARISH']['available'],at)
        entries,checks=tick(30,SimpleNamespace(ready=True,wma21_rsi=49,ema3_rsi=46,rsi9=45))
        self.assertTrue(entries);self.assertTrue(checks[0]['confirmation_window_pass'])
    def test_no_expiry_still_rejects_cutoff_entry(self):
        g,tick,_,_=self.direct_harness(strength=.2,no_expiry=True)
        tick(30)
        self.assertFalse(tick(35,SimpleNamespace(ready=True,wma21_rsi=49,ema3_rsi=46,rsi9=45))[0])
    def test_until_opposite_ignores_arms_and_repeated_setup(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=self.at.replace(minute=0)
        frame=self.cross_frame(previous=53,current=44,open=103,close=102,ema10=105,previous_ema10=106,
            ema3_rsi=48,wma21_rsi=52,previous_ema3_rsi=52,previous_wma21_rsi=53)
        Gate=qualified_opposite_watch_gate(direct_five_base(engine.WmaGapGate,no_expiry=True),{at:frame},engine.direction,require_wma_permission=False,signal_rule='CLOSE_RSI40_60_SLOPE_COLOUR',until_opposite=True)
        g=Gate(opposite_switch=True)
        def event(side):return engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL' if side=='BEARISH' else 'ENTRY_BULLISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        # Use an original recognised bullish ENTRY type from the engine registry.
        bull_type=next(k for k in engine.ENTRY_TYPES if engine.direction(engine.StrategyEvent(k,at,None,'IDLE','ARMED',details={}))=='BULLISH')
        bull=engine.StrategyEvent(bull_type,at,None,'IDLE','ARMED',details={})
        g.signal(bull,at-timedelta(minutes=20));original=g.pending['BULLISH']
        g.signal(bull,at);self.assertIs(g.pending['BULLISH'],original)
        arm=engine.StrategyEvent('BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN',at,None,'IDLE','ARMED',details={})
        g.observe_arms([arm],at);self.assertIn('BULLISH',g.pending)
        self.assertEqual(g.watch_side,'BULLISH')
        frame['previous_wma21_rsi']=52.2
        g.signal(event('BEARISH'),at);self.assertIn('BULLISH',g.pending)
        frame['previous_wma21_rsi']=53
        g.signal(event('BEARISH'),at);self.assertNotIn('BULLISH',g.pending);self.assertIn('BEARISH',g.pending)
    def test_until_opposite_replay_disables_only_pending_canonical_cancel(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_and_fresh_setup_last10_research as fresh
        source=inspect.getsource(direct_fresh_replay(engine,fresh,until_opposite=True))
        self.assertNotIn('if e.event_type in EXIT_TYPES:g.pending.pop(direction(e),None)',source)
        self.assertIn('if dual_exit(side,new):',source)
        self.assertIn("if at.strftime('%H:%M')>='14:55':g.pending.clear()",source)
    def test_direct5m_original_engine_unchanged(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        source=inspect.getsource(engine.WmaGapGate.evaluate);direct_five_base(engine.WmaGapGate)
        self.assertEqual(inspect.getsource(engine.WmaGapGate.evaluate),source)
    def test_direct_replay_removes_only_minute_setup_gap_veto(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_and_fresh_setup_last10_research as fresh
        original=inspect.getsource(engine.replay);source=inspect.getsource(direct_fresh_replay(engine,fresh))
        self.assertIn('if bar and g.can_signal(side,at) and aligned and not episode[side]',source)
        self.assertIn('side not in g.pending',source);self.assertIn("g.owner=='NONE'",source)
        self.assertIn('if bar:episode[side]=False',source)
        self.assertEqual(inspect.getsource(engine.replay),original)
    def test_direct5m_cross_close_gate_runs_on_setup_boundary(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        frame=dict(open=101,high=107,low=99,close=100,ema10=105,previous_ema10=106,
            previous_rsi9=56,rsi9=54,available_at=at.isoformat(),rsi_available_at=at.isoformat())
        g=entry_gate(direct_five_base(engine.WmaGapGate),{at:frame},rule='CLOSE_RSI_SLOPE_COLOUR')(opposite_switch=True)
        ev=engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={});g.signal(ev,at)
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1),current=SimpleNamespace(ready=True,wma21_rsi=49,ema3_rsi=47,rsi9=46),
            reference=SimpleNamespace(ready=True,wma21_rsi=50,ema3_rsi=49,rsi9=48),price=100)
        self.assertTrue(entries);self.assertTrue(checks[0]['ema10_entry']['rsi_cross_pass'])
    def test_direct5m_wma_lock_still_vetoes(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_and_fresh_setup_last10_research as fresh
        import hilega_post_entry_wma_lock_today_research as lock
        import hilega_wma_threshold_only_oct14_research as threshold
        at=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        wm={at:dict(wma21=70,previous_wma21=71,rsi9=65,ema3=65,available_at=at.isoformat())}
        Parent=fresh.combined_gate(SimpleNamespace(WmaGapGate=direct_five_base(engine.WmaGapGate),direction=engine.direction),{},wm,lock,None,threshold)
        g=Parent(opposite_switch=True)
        ev=engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={});g.signal(ev,at)
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1),current=SimpleNamespace(ready=True,wma21_rsi=69,ema3_rsi=67,rsi9=66),
            reference=SimpleNamespace(ready=True,wma21_rsi=70,ema3_rsi=69,rsi9=68),price=100)
        self.assertFalse(entries);self.assertEqual(g.owner,'NONE');self.assertFalse(g.pending)
        self.assertEqual(checks[0]['status'],'POST_ENTRY_WMA_LOCK_BLOCKED')
    def test_supported_original_confirmation_enters(self):
        g=self.harness(frame=self.frame());entries,checks=g.evaluate(minute=self.at-timedelta(minutes=1))
        self.assertEqual(entries,['entry']);self.assertEqual(g.owner,'BULLISH');self.assertFalse(g.pending)
        self.assertTrue(checks[0]['ema10_entry']['passed'])
    def test_wait_can_pass_on_later_fresh_check(self):
        frame=self.frame(low=99);g=self.harness(frame=frame)
        self.assertFalse(g.evaluate(minute=self.at-timedelta(minutes=1))[0])
        frame['low']=101
        self.assertEqual(g.evaluate(minute=self.at)[0],['entry'])
    def test_ema_uses_close_alpha_and_cutoff_not_partial_bar(self):
        captured=[]
        class Engine:
            candles=staticmethod(lambda rows: rows)
            @staticmethod
            def aggregate_exact_5m(rows,day,**kw):
                captured.extend(rows)
                return [SimpleNamespace(ts=datetime.combine(day,datetime.min.time(),tzinfo=Checks.at.tzinfo).replace(hour=9,minute=15),
                    open=100,high=102,low=99,close=100 if day.day!=16 else 102)]
        warm=[('2026-09-01',[]) for _ in range(20)]
        # Synthetic deterministic bars isolate seeding and last cutoff-minute handling.
        raw=[dict(timestamp='2026-10-16T14:55:00+05:30'),dict(timestamp='2026-10-16T14:54:00+05:30')]
        frames=build_frames(Engine,'2026-10-16',raw,warm,datetime.fromisoformat)
        f=next(iter(frames.values()))
        self.assertAlmostEqual(f['previous_ema10'],100);self.assertAlmostEqual(f['ema10'],100+4/11)
        self.assertEqual(captured,[raw[1]]);self.assertEqual(len(raw),2)

    def baseline2_harness(self,ema_ok=True,rule='FULL_CANDLE'):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        frames={}
        for minutes in range(0,36,5):
            boundary=at+timedelta(minutes=minutes)
            frames[boundary]=dict(open=100,high=101 if ema_ok else 107,low=99,close=100,
                ema10=105,previous_ema10=106,available_at=boundary.isoformat(),
                rsi9=54,previous_rsi9=56,rsi_available_at=boundary.isoformat())
        g=baseline2_gate(engine,frames,rule=rule)(opposite_switch=True)
        event=engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at-timedelta(minutes=5),None,'IDLE','ARMED',details={})
        g.signal(event,at)
        def tick(clock,ema=48,strength=1):
            t=datetime.fromisoformat('2026-10-16T'+clock+':00+05:30')
            snap=SimpleNamespace(ready=True,rsi9=ema-1,ema3_rsi=ema,wma21_rsi=49)
            ref=SimpleNamespace(ready=True,wma21_rsi=49+strength)
            return g.evaluate(minute=t-timedelta(minutes=1),current=snap,reference=ref,price=100)
        return g,tick,engine
    def test_baseline2_no_intermediate_minute_entry(self):
        g,tick,_=self.baseline2_harness();tick('14:20')
        self.assertEqual(tick('14:21',ema=45),([],[]));self.assertIsNone(g.pending['BEARISH']['armed_at'])
    def test_baseline2_directional_close_enters_despite_upper_wick(self):
        g,tick,_=self.baseline2_harness(ema_ok=False,rule='CLOSE_BOTH');tick('14:20')
        entries,checks=tick('14:25',ema=47)
        self.assertTrue(entries);self.assertFalse(checks[0]['ema10_entry']['entire_candle_pass'])
        self.assertTrue(checks[0]['ema10_entry']['close_below_ema10'])
    def test_baseline2_cross_rule_runs_at_5m_only(self):
        g,tick,_=self.baseline2_harness(ema_ok=False,rule='CLOSE_AND_RSI_CROSS');tick('14:20')
        self.assertFalse(tick('14:21',ema=47)[0])
        self.assertTrue(tick('14:25',ema=47)[0])
    def test_baseline2_first_qualifying_5m_needs_no_persistence(self):
        g,tick,_=self.baseline2_harness();tick('14:20')
        entries,checks=tick('14:25',ema=47)
        self.assertTrue(entries);self.assertFalse(checks[0]['persistence_pass']);self.assertFalse(checks[0]['persistence_required'])
    def test_baseline2_no_time_expiry(self):
        g,tick,_=self.baseline2_harness();tick('14:20');tick('14:25');tick('14:30');tick('14:31')
        self.assertIn('BEARISH',g.pending)
        self.assertTrue(tick('14:35',ema=47)[0])
    def test_baseline2_strength_still_required(self):
        g,tick,_=self.baseline2_harness();tick('14:20')
        entries,checks=tick('14:25',ema=47,strength=.74)
        self.assertFalse(entries);self.assertIn('WMA_THRESHOLD_NOT_MET',checks[0]['reasons'])
    def test_baseline2_expansion_uses_5m_not_minute(self):
        g,tick,_=self.baseline2_harness();tick('14:20');tick('14:24',ema=40)
        entries,checks=tick('14:25',ema=47)
        self.assertTrue(entries);self.assertEqual(checks[0]['previous_gap'],1)
    def test_baseline2_ema_rejection_retains_candidate_beyond_ten(self):
        g,tick,_=self.baseline2_harness(ema_ok=False);tick('14:20');tick('14:25')
        entries,checks=tick('14:35',ema=47)
        # A gap is only valid against consecutive completed 5m readings.
        self.assertFalse(entries);self.assertIn('BEARISH',g.pending)
        entries,checks=tick('14:40',ema=46)
        self.assertFalse(entries);self.assertEqual(checks[0]['status'],'EMA10_ENTRY_WAIT')
        self.assertEqual(g.owner,'NONE');self.assertIn('BEARISH',g.pending)
    def test_baseline2_cutoff_still_blocks(self):
        g,tick,_=self.baseline2_harness();tick('14:50')
        entries,checks=tick('14:55',ema=47)
        self.assertFalse(entries);self.assertIn('SESSION_CUTOFF',checks[0]['reasons'])
    def test_baseline2_original_opposite_setup_cancels(self):
        g,tick,engine=self.baseline2_harness();tick('14:20')
        at=datetime.fromisoformat('2026-10-16T14:25:00+05:30')
        event=engine.StrategyEvent('ENTRY_BULLISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        self.assertNotIn('BEARISH',g.pending);self.assertIn('BULLISH',g.pending)


class NewSessionChecks(unittest.TestCase):
    @staticmethod
    def rows():
        start=datetime.fromisoformat('2026-10-19T09:15:00+05:30')
        return [dict(timestamp=(start+timedelta(minutes=i)).isoformat()) for i in range(340)]
    def test_complete_pre_cutoff_grid(self):
        validate_new_session_minutes(self.rows(),'2026-10-19')
    def test_missing_minute_rejected(self):
        with self.assertRaisesRegex(ValueError,'MISSING_MINUTES:09:15'):
            validate_new_session_minutes(self.rows()[1:],'2026-10-19')
    def test_duplicate_minute_rejected(self):
        rows=self.rows()
        with self.assertRaisesRegex(ValueError,'DUPLICATE_MINUTE'):
            validate_new_session_minutes(rows+[rows[0]],'2026-10-19')
    def test_wrong_session_rejected(self):
        with self.assertRaisesRegex(ValueError,'WRONG_DATE'):
            validate_new_session_minutes(self.rows(),'2026-10-20')


def validate_new_session_minutes(raw,day):
    """Require the complete pre-cutoff minute grid; never reuse another day."""
    start=datetime.fromisoformat(day+'T09:15:00+05:30')
    end=datetime.fromisoformat(day+'T14:55:00+05:30')
    seen=set()
    for row in raw:
        at=datetime.fromisoformat(row['timestamp'])
        if at.tzinfo is None:raise ValueError('NEW_SESSION_NAIVE_TIMESTAMP')
        if at.astimezone(start.tzinfo).date()!=start.date():raise ValueError('NEW_SESSION_WRONG_DATE')
        if at in seen:raise ValueError('NEW_SESSION_DUPLICATE_MINUTE:'+at.isoformat())
        seen.add(at)
    required={start+timedelta(minutes=i) for i in range(int((end-start).total_seconds()/60))}
    missing=sorted(required-seen)
    if missing:raise ValueError('NEW_SESSION_MISSING_MINUTES:'+','.join(x.strftime('%H:%M') for x in missing))


def main():
    import hilega_and_fresh_setup_30_sessions_research as batch
    if '--test' in __import__('sys').argv:
        new_result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NewSessionChecks))
        if not new_result.wasSuccessful():raise SystemExit(1)
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
        batch.main()  # Original control and composition tests, too.
        return
    source=inspect.getsource(batch.main)
    def replace(old,new):
        nonlocal source
        if source.count(old)!=1:raise ValueError('BATCH_SOURCE_ANCHOR_MISMATCH:'+old)
        source=source.replace(old,new,1)
    replace("default=30)","default=65)")
    replace("ap.add_argument('--test',action='store_true')",
        "ap.add_argument('--test',action='store_true')\n    ap.add_argument('--date',help='Replay only this saved trading session, YYYY-MM-DD')")
    replace('args=ap.parse_args()',
        "args=ap.parse_args()\n    if args.date:\n        if any(x in ('--sessions','--end-date') or x.startswith(('--sessions=','--end-date=')) for x in sys.argv[1:]):ap.error('--date cannot be combined with --sessions or --end-date')\n        args.end_date=args.date\n        args.sessions=1\n        if not any(x=='--output' or x.startswith('--output=') for x in sys.argv[1:]):args.output=Path('data/research/hilega-ema10-entry-day-'+args.date.replace('-',''))")
    replace("ap.add_argument('--date',help='Replay only this saved trading session, YYYY-MM-DD')",
        "ap.add_argument('--date',help='Replay one session, YYYY-MM-DD')\n    ap.add_argument('--fetch-today',action='store_true',help='Read-only analytics fetch for a newer single session on the current IST date')\n    ap.add_argument('--session-input',type=Path,help='Captured candle JSON for a newer single session')\n    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))")
    replace("extra=json.loads(args.today_input.read_text())",
        "extra=json.loads(args.today_input.read_text())\n    newer_session=bool(args.date and args.date>extra['session_date'])\n    if (args.fetch_today or args.session_input) and not newer_session:ap.error('--fetch-today/--session-input require a newer --date')\n    if args.fetch_today and args.session_input:ap.error('Choose --fetch-today OR --session-input')\n    if newer_session and not (args.fetch_today or args.session_input):ap.error('Newer session requires --fetch-today or --session-input PATH')")
    replace("days=select_sessions(calendar,parent['start_date'],args.end_date,args.sessions,extra['session_date'])",
        "days=single_session(args.date,calendar,parent['start_date'],args.date if newer_session else extra['session_date'],args.date if newer_session else extra['session_date']) if args.date else select_sessions(calendar,parent['start_date'],args.end_date,args.sessions,extra['session_date'])")
    replace("if day==extra['session_date']:",
        "if newer_session:\n                raw,warm,input_hashes=p.inputs(engine,day,args.session_input,args.fetch_today,args.output)\n                validate_new_session_minutes(raw,day)\n                saved=None\n                basis='NEW_SESSION_ANALYTICS_WITH_RECORDED_AUDIT_PARITY'\n                (args.output/'new-session-input-provenance.json').write_text(json.dumps(dict(session_date=day,input_hashes=input_hashes,audit=str(args.audit)),indent=2)+'\\n')\n            elif day==extra['session_date']:")
    replace("if saved['session_date']!=day or saved['strategy_version']!=p.VERSION:raise ValueError('BASELINE_IDENTITY_MISMATCH')",
        "if saved is not None and (saved['session_date']!=day or saved['strategy_version']!=p.VERSION):raise ValueError('BASELINE_IDENTITY_MISMATCH')")
    replace("parity=stats.frozen_parity(saved,baseline)",
        "parity=p.audit_parity(args.audit,day,asof,baseline) if newer_session else stats.frozen_parity(saved,baseline)\n            if newer_session:\n                (args.output/'new-session-baseline.json').write_text(json.dumps(baseline,indent=2,default=str)+'\\n')\n                (args.output/'new-session-parity.json').write_text(json.dumps(parity,indent=2,default=str)+'\\n')")
    replace("data/research/hilega-and-fresh-setup-30sessions-20261016","data/research/hilega-qualified-watch-override-3months-20261016")
    replace('variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)',
        'variants=add_variants(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold)')
    namespace=dict(batch.main.__globals__,add_variants=add_variants,write_reports=write_reports,single_session=single_session,validate_new_session_minutes=validate_new_session_minutes,sys=sys)
    filename='<hilega-ema10-entry-batch>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),namespace)
    namespace['main']()


if __name__=='__main__':main()
