"""WMA-gap V2 live observation adapter. No broker calls or real-money orders.

Canonical signal generation is separate from actual V2 ownership. Minute
indicators are provisional clones of the last completed five-minute state.
Exits precede entry evaluation, including when both occur at one boundary.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from .domain import IST
from .hilega_directional_coordinator_v1 import (
    HilegaDirectionalCoordinatorV1, DirectionalDecision,
    BULLISH_ENTRY_EVENTS, BEARISH_ENTRY_EVENTS, BULLISH_EXIT_EVENTS, BEARISH_EXIT_EVENTS,
)
from .hilega_directional_live_shadow_v1 import HilegaDirectionalLiveShadowCoordinatorV1
from .hilega_milega_strategy_v1 import FiveMinuteBar, SessionState
from .hilega_milega_bearish_strategy_v1 import BearishSessionState
from .hilega_milega_historical_replay_v1 import aggregate_exact_5m, load_validated_warmup_1m, UNDERLYING

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
        if old != 'NONE' and exiting and new_entries and bar.ts.time() < time(14,50):
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
    def __init__(self):
        self.owner='NONE'; self.active=None; self.pending={}; self.previous=None; self.locked=False
    def signal(self, event, available):
        side=direction(event)
        self.pending[side]={'event':event, 'available':available, 'armed_at':None}
    def close(self, event, at, price):
        side=direction(event)
        self.pending.pop(side,None)
        if self.owner!=side:return None
        active=self.active
        result=replace(event,event_time=at,price=price,entry_time=active['time'],entry_price=active['price'],
                       points=(price-active['price'])*(1 if side=='BULLISH' else -1))
        self.owner='NONE'; self.active=None
        return result
    def evaluate(self, *, minute, current, reference, price, exit_boundary=False):
        accepted=[]; checks=[]
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
            if self.locked or (minute+timedelta(minutes=1)).time()>=time(14,55):reasons.append('SESSION_CUTOFF')
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
                self.owner=side;self.active={'time':at,'price':price};del self.pending[side]
            elif age>=10 or self.locked:del self.pending[side]
        change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None
        self.previous={'minute':minute,'snapshot':current,'wma_change':change}
        return accepted,checks

class HilegaWmaGapLiveCoordinatorV2(HilegaDirectionalLiveShadowCoordinatorV1):
    def _safe(self):
        return {**super()._safe(),'model':'HILEGA_WMA_GAP_LIVE_V2','strategy_id':STRATEGY_ID,'strategy_version':'2.0.0',
                'entry_policy':'POST_ARM_PERSISTENCE_ADJACENT_GAP','same_candle_exit_entry_enabled':True,
                'exit_policy':'CURRENT_RSI9_WMA21_STRUCTURAL'}
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.minute_entry_boundaries=True
        self.canonical=ExitFirstCanonical();self.gate=WmaGapGate();self._last_minute=None
        self._sync_view()
    def _audited_option_restore_plan(self, session_date):
        # V1 option identities must never be restored into the V2 strategy.
        original = self.step_audit.read_all
        self.step_audit.read_all = lambda: [r for r in original() if (r.get('payload') or {}).get('strategy_id') == STRATEGY_ID]
        try:
            return super()._audited_option_restore_plan(session_date)
        finally:
            self.step_audit.read_all = original
    def _sync_view(self):
        bullish=SessionState(session_date=self.canonical.session_date,active=self.gate.owner=='BULLISH',
                             armed='BULLISH' in self.gate.pending,session_locked=self.gate.locked)
        bearish=BearishSessionState(session_date=self.canonical.session_date,active=self.gate.owner=='BEARISH',
                             armed='BEARISH' in self.gate.pending,session_locked=self.gate.locked)
        self.directional=SimpleNamespace(trade_owner=self.gate.owner,bullish=SimpleNamespace(session=bullish),bearish=SimpleNamespace(session=bearish))
    def _decision(self, at, before, events, note):
        self._sync_view()
        return DirectionalDecision(at.isoformat(),before,self.gate.owner,tuple(events),(),
            self.directional.bullish.session.name,self.directional.bearish.session.name,
            'BULLISH' in self.gate.pending,'BEARISH' in self.gate.pending,note)
    def _advance(self, minute, bars, *, recovered):
        t=minute.timestamp.astimezone(IST);available=t+timedelta(minutes=1)
        before=self.gate.owner; events=[]
        reference=self.canonical.bullish.previous_indicators
        current=deepcopy(self.canonical.bullish.indicators).update(float(minute.close))
        bar=bars.get(t-timedelta(minutes=4)) if t.minute%5==4 else None
        if bar:
            decision=self.canonical.on_bar(bar)
            for event in decision.accepted_events:
                if event.event_type in EXIT_TYPES:
                    closed=self.gate.close(event,available,float(bar.close))
                    if closed:events.append(closed)
            for event in decision.accepted_events:
                if event.event_type in ENTRY_TYPES:self.gate.signal(event,available)
            self._last_bar_ts=bar.ts
        entries,checks=self.gate.evaluate(minute=t,current=current,reference=reference,price=float(minute.close),exit_boundary=bool(events))
        events.extend(entries)
        if available.time()>=time(14,55):self.gate.pending.clear()
        self._sync_view()
        status='RECOVERED' if recovered else 'PROCESSED'
        for check in checks:
            self._audit(available,'WMA_GAP_MINUTE_EVALUATION',status,check,checkpoint=t)
        decision=self._decision(available,before,events,'EXIT_FIRST; V2_PERSISTENCE_REQUIRED')
        if bar or events or checks:
            self._audit(available,'DIRECTIONAL_DECISION',status,{
                **self._directional_decision_payload(bar or FiveMinuteBar(t,float(minute.open),float(minute.high),float(minute.low),float(minute.close),None),decision),
                'bar_timestamp':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
                'minute_timestamp':t.isoformat(),'decision_timestamp':available.isoformat(),'nifty_close':float(minute.close),
                'wma_gap_checks':checks,'reconstructed':recovered,
                'event_details':[{'event_type':e.event_type,'entry_price':e.entry_price,'entry_time':e.entry_time.isoformat() if e.entry_time else None,'price':e.price,'points':e.points} for e in events],
            },checkpoint=t)
        if not recovered:
            # Every close is processed before starting any replacement option basket.
            for e in events:
                if e.event_type in EXIT_TYPES:self._close_option(direction=direction(e),now=available,exit_boundary=available,exit_reason=e.exit_reason or e.event_type,audit=True)
            for e in entries:
                signal_label=datetime.fromisoformat(e.details['wma_gap']['signal_timestamp'])
                signal_bar=bars[signal_label]
                self._start_option(direction=direction(e),now=available,bar=signal_bar,event=e,audit=True)
        self._last_minute=t
        return decision
    @staticmethod
    def _exact_rows(intraday,now):
        rows={}
        for c in intraday:
            t=c.timestamp.astimezone(IST)
            if t.date()!=now.date() or not time(9,15)<=t.time()<time(14,55) or t+timedelta(minutes=1)>now:continue
            if t in rows:raise ValueError('DUPLICATE_COMPLETED_MINUTE')
            rows[t]=c
        return rows
    def _consume(self,intraday,now,*,recovered):
        rows=self._exact_rows(intraday,now)
        # Aggregate only exact completed five-minute buckets. Missing evidence waits.
        bars={}
        for label in sorted({t.replace(minute=t.minute-t.minute%5) for t in rows}):
            bucket=[rows.get(label+timedelta(minutes=i)) for i in range(5)]
            if all(bucket):
                bars[label]=FiveMinuteBar(label,float(bucket[0].open),max(float(c.high) for c in bucket),min(float(c.low) for c in bucket),float(bucket[-1].close),None)
        expected=self._last_minute+timedelta(minutes=1) if self._last_minute else datetime.combine(now.date(),time(9,15),tzinfo=IST)
        processed=0
        self._missing_minute=None
        while expected in rows:
            self._advance(rows[expected],bars,recovered=recovered);processed+=1;expected+=timedelta(minutes=1)
        if expected+timedelta(minutes=1)<=now and expected.time()<time(14,55):
            self._missing_minute=expected
            self._health(now,'WAITING_FOR_EXACT_MINUTE',missing_minute=expected.isoformat())
        return processed
    def bootstrap(self,now):
        now=now.astimezone(IST)
        if self._bootstrapped_date==now.date():return {'status':'ALREADY_BOOTSTRAPPED'}
        self.canonical=ExitFirstCanonical();self.gate=WmaGapGate();self._last_minute=None;self._last_bar_ts=None;self._cutoff_done_date=None
        self._ce_last_update=self._pe_last_update=None
        from .hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
        from .hilega_milega_pe_option_shadow_lifecycle_v1 import HilegaMilegaPEOptionShadowLifecycleV1
        self.ce_shadow=HilegaMilegaOptionShadowLifecycleV1();self.pe_shadow=HilegaMilegaPEOptionShadowLifecycleV1()
        for store in (self._pending_ce_exits,self._pending_pe_exits,self._pending_ce_entries,self._pending_pe_entries,self._pending_ce_entry_exits,self._pending_pe_entry_exits):store.clear()
        day=now.date()-timedelta(days=self.warmup_calendar_days)
        while day<now.date():
            candles=self.sources.warmup_candles(day,self.cache_root) if hasattr(self.sources,'warmup_candles') else load_validated_warmup_1m(self.sources,underlying=UNDERLYING,session_date=day,cache_root=self.cache_root)
            if candles:
                for bar in aggregate_exact_5m(candles,day):self.canonical.on_bar(bar)
            day+=timedelta(days=1)
        self.canonical.bullish.session=SessionState(session_date=now.date());self.canonical.bearish.session=BearishSessionState(session_date=now.date())
        for engine in (self.canonical.bullish,self.canonical.bearish):engine.previous_indicators=None;engine.previous_bar=None
        self.canonical.trade_owner='NONE';self.canonical.session_date=now.date()
        self._consume(self.sources.nifty_intraday_1m(now=now),now,recovered=True)
        self._sync_view();restore=self._restore_audited_option_state(now=now,session_date=now.date())
        self._bootstrapped_date=now.date()
        self._audit(now,'DIRECTIONAL_LIVE_BOOTSTRAP','PASS',{'session_date':now.date().isoformat(),'trade_owner':self.gate.owner,
            'bullish_state':self.directional.bullish.session.name,'bearish_state':self.directional.bearish.session.name,
            'last_completed_bar':self._last_bar_ts.isoformat() if self._last_bar_ts else None,'reconstructed':True,'option_restore':restore})
        return {'status':'BOOTSTRAPPED'}
    def process_cutoff(self,now,*,intraday):
        at=datetime.combine(now.date(),time(14,55),tzinfo=IST)
        if now<at or self._cutoff_done_date==now.date():return None
        price=self._minute_open(intraday,at)
        if price is None:
            self._audit(now,'DIRECTIONAL_SESSION_CUTOFF','WAITING',{'cutoff_timestamp':at.isoformat(),'reason':'EXACT_1455_OPEN_UNAVAILABLE'});return None
        before=self.gate.owner;raw=self.canonical.on_session_cutoff(at,price);events=[]
        for e in raw.accepted_events:
            if e.event_type in EXIT_TYPES:
                closed=self.gate.close(e,at,price)
                if closed:events.append(closed)
        self.gate.locked=True;self.gate.pending.clear();decision=self._decision(at,before,events,'SESSION_CUTOFF_NO_REENTRY')
        for e in events:self._close_option(direction=direction(e),now=now,exit_boundary=at,exit_reason=e.event_type,audit=True)
        self._audit(now,'DIRECTIONAL_SESSION_CUTOFF','PROCESSED',{'cutoff_timestamp':at.isoformat(),'decision_timestamp':at.isoformat(),
            'accepted_events':[e.event_type for e in events],'trade_owner_before':before,'trade_owner_after':self.gate.owner,
            'session_date':now.date().isoformat(),'bullish_state':self.directional.bullish.session.name,
            'bearish_state':self.directional.bearish.session.name,'bullish_armed':False,'bearish_armed':False,
            'last_completed_bar':self._last_bar_ts.isoformat() if self._last_bar_ts else None})
        self._cutoff_done_date=now.date();return decision
    def process(self,now):
        now=now.astimezone(IST);self.bootstrap(now)
        intraday=self.sources.nifty_intraday_1m(now=now)
        count=self._consume(intraday,now,recovered=False)
        cutoff=self.process_cutoff(now,intraday=intraday)
        self._retry_pending(now);self._update_options(now)
        self._health(now,'WAITING_FOR_EXACT_MINUTE' if self._missing_minute else 'PROCESSED',missing_minute=self._missing_minute.isoformat() if self._missing_minute else None,trade_owner=self.gate.owner,bullish_state=self.directional.bullish.session.name,bearish_state=self.directional.bearish.session.name)
        return {'status':'PROCESSED','strategy_id':STRATEGY_ID,'minutes_processed':count,'trade_owner':self.gate.owner,'cutoff_processed':cutoff is not None}


def assert_forward_control_strategy(day, source=None):
    """Never relabel the new V2 execution stream as the old V1 control cohort."""
    import json
    from pathlib import Path
    path=Path(source or 'data/live-observation/hilega-directional-v1/step-audit.jsonl')
    if not path.exists():return
    for line in path.read_text().splitlines():
        if not line.strip():continue
        record=json.loads(line);payload=record.get('payload') or {}
        at=str(payload.get('minute_timestamp') or payload.get('bar_timestamp') or record.get('checkpoint') or record.get('event_time') or '')
        if payload.get('strategy_id')==STRATEGY_ID and at.startswith(day) and record.get('status')=='PROCESSED':
            raise ValueError('V2_LIVE_POLICY_REQUIRES_SEPARATE_FORWARD_COHORT: do not use V2 decisions as canonical V1 control')
