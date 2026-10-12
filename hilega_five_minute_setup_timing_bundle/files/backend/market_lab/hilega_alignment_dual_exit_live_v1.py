"""Live observation adapter for the tested historical alignment + dual-exit policy."""
from copy import deepcopy
from datetime import datetime, timedelta, time
import json
from .hilega_v2_alignment_replay_v1 import cache_index, candles, aggregate_exact_5m
from .hilega_milega_strategy_v1 import SessionState
from .hilega_milega_bearish_strategy_v1 import BearishSessionState
from .hilega_wma_gap_live_v2 import HilegaWmaGapLiveCoordinatorV2
from .hilega_v2_alignment_replay_v1 import (
    ExitFirstCanonical, WmaGapGate, dual_exit, direction, ENTRY_TYPES, EXIT_TYPES, RULES, decision_checkpoint,
)
from .hilega_milega_strategy_v1 import FiveMinuteBar, StrategyEvent
from .domain import IST
STRATEGY_ID = 'HILEGA_V2_ALIGNMENT_DUAL_EXIT'

class HilegaAlignmentDualExitLiveCoordinator(HilegaWmaGapLiveCoordinatorV2):
    strategy_id = STRATEGY_ID
    canonical_factory = ExitFirstCanonical
    gate_factory = WmaGapGate

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reset_policy_session()

    def _reset_policy_session(self):
        self.episode = {'BULLISH': False, 'BEARISH': False}
        self.warning_time = None

    def _safe(self):
        return {**super()._safe(), 'model':'HILEGA_ALIGNMENT_DUAL_EXIT_LIVE_V1',
                'strategy_id':STRATEGY_ID, 'strategy_version':RULES['version'],
                'policy_id':STRATEGY_ID, 'entry_policy':RULES['setup'],
                'exit_policy':RULES['exit'], 'same_candle_exit_entry_enabled':True,
                'strategy_rules':RULES}

    def bootstrap(self, now):
        now=now.astimezone(IST)
        if self._bootstrapped_date==now.date():return {'status':'ALREADY_BOOTSTRAPPED'}
        # Identical local warmup roots and ordering as historical auto replay.
        # No additional historical broker downloads are introduced.
        self.canonical=self.canonical_factory();self.gate=self.gate_factory()
        self._last_minute=None;self._last_bar_ts=None;self._cutoff_done_date=None
        self._ce_last_update=self._pe_last_update=None
        from .hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
        from .hilega_milega_pe_option_shadow_lifecycle_v1 import HilegaMilegaPEOptionShadowLifecycleV1
        self.ce_shadow=HilegaMilegaOptionShadowLifecycleV1();self.pe_shadow=HilegaMilegaPEOptionShadowLifecycleV1()
        for store in (self._pending_ce_exits,self._pending_pe_exits,self._pending_ce_entries,self._pending_pe_entries,self._pending_ce_entry_exits,self._pending_pe_entry_exits):store.clear()
        warmup_sessions=0
        for day,path in sorted(cache_index().items()):
            if day>=now.date().isoformat():continue
            rows=json.loads(path.read_text()).get('candles') or []
            if not rows:continue
            from datetime import date
            for bar in aggregate_exact_5m(candles(rows),date.fromisoformat(day)):
                self.canonical.on_bar(bar)
            warmup_sessions+=1
        if not self.canonical.bullish.previous_indicators or not self.canonical.bullish.previous_indicators.ready:
            raise ValueError('ALIGNMENT_LIVE_LOCAL_WARMUP_NOT_READY')
        self.canonical.bullish.session=SessionState(session_date=now.date())
        self.canonical.bearish.session=BearishSessionState(session_date=now.date())
        for engine in (self.canonical.bullish,self.canonical.bearish):
            engine.previous_indicators=None;engine.previous_bar=None
        self.canonical.trade_owner='NONE';self.canonical.session_date=now.date()
        self._reset_policy_session()
        self._consume(self.sources.nifty_intraday_1m(now=now),now,recovered=True)
        self._sync_view()
        restore=self._restore_audited_option_state(now=now,session_date=now.date())
        self._bootstrapped_date=now.date()
        self._audit(now,'DIRECTIONAL_LIVE_BOOTSTRAP','PASS',{
            'session_date':now.date().isoformat(),'trade_owner':self.gate.owner,
            'bullish_state':self.directional.bullish.session.name,'bearish_state':self.directional.bearish.session.name,
            'last_completed_bar':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            'reconstructed':True,'option_restore':restore,'warmup_sessions':warmup_sessions,
            'warmup_policy':'HISTORICAL_LOCAL_CACHE_ORDER'})
        return {'status':'BOOTSTRAPPED'}

    def _advance(self, minute, bars, *, recovered):
        t=minute.timestamp.astimezone(IST);available=t+timedelta(minutes=1)
        before=self.gate.owner;events=[];canonical_decision=None;exit_validation=None;setups=[]
        reference=self.canonical.bullish.previous_indicators
        current=deepcopy(self.canonical.bullish.indicators).update(float(minute.close))
        bar=bars.get(t-timedelta(minutes=4)) if t.minute%5==4 else None
        if bar:
            canonical_decision=self.canonical.on_bar(bar)
            for event in canonical_decision.accepted_events:
                if event.event_type in EXIT_TYPES:self.gate.pending.pop(direction(event),None)
            if self.gate.owner!='NONE':
                snap=self.canonical.bullish.previous_indicators;side=self.gate.owner
                sign=1 if side=='BULLISH' else -1
                exit_validation=dict(direction=side,rsi9=snap.rsi9,ema3=snap.ema3_rsi,
                    wma21=snap.wma21_rsi,rsi_opposite=sign*(snap.rsi9-snap.wma21_rsi)<0,
                    ema_opposite=sign*(snap.ema3_rsi-snap.wma21_rsi)<0,
                    dual_exit_pass=dual_exit(side,snap))
                if exit_validation['rsi_opposite'] and self.warning_time is None:
                    self.warning_time=available.isoformat()
                if dual_exit(side,snap):
                    event=StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if side=='BULLISH'
                        else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',available,None,'ACTIVE','IDLE',
                        exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
                    closed=self.gate.close(event,available,float(bar.close))
                    if closed:events.append(closed)
            for event in canonical_decision.accepted_events:
                if event.event_type in ENTRY_TYPES and self.gate.owner=='NONE' and direction(event) not in self.gate.pending:
                    self.gate.signal(event,available)
                    setups.append(dict(time=available.isoformat(),direction=direction(event),source='V1_CANONICAL'))
            self._last_bar_ts=bar.ts
        latest=self.canonical.bullish.previous_indicators
        for side in ('BULLISH','BEARISH'):
            sign=1 if side=='BULLISH' else -1
            aligned=latest and latest.ready and sign*(latest.rsi9-latest.ema3_rsi)>0 and sign*(latest.ema3_rsi-latest.wma21_rsi)>0
            if not aligned:self.episode[side]=False
            prev=self.gate.previous
            gap=sign*(current.ema3_rsi-current.wma21_rsi) if current.ready else None
            pg=sign*(prev['snapshot'].ema3_rsi-prev['snapshot'].wma21_rsi) if prev and prev['snapshot'].ready else None
            expanding=pg is not None and gap is not None and gap>pg and prev['minute']==t-timedelta(minutes=1)
            if bar and aligned and gap is not None and gap>0 and expanding and not self.episode[side] and self.gate.owner=='NONE' and side not in self.gate.pending and available.time()<time(14,55):
                self.episode[side]=True
                event=StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH'
                    else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',t,'ALTERNATIVE_ALIGNMENT','IDLE','ARMED',details={'alternative':True})
                self.gate.signal(event,available)
                setups.append(dict(time=available.isoformat(),direction=side,source='ALTERNATIVE_ALIGNMENT'))
        entries,checks=self.gate.evaluate(minute=t,current=current,reference=reference,
            price=float(minute.close),exit_boundary=bool(events))
        events.extend(entries)
        if entries:
            self.warning_time=None
            self.gate.pending.clear()
        if available.time()>=time(14,55):self.gate.pending.clear()
        decision=self._decision(available,before,events,'EXIT_FIRST; HISTORICAL_ALIGNMENT_DUAL_EXIT')
        status='RECOVERED' if recovered else 'PROCESSED'
        if decision_checkpoint(boundary=bar is not None, checks=checks, entries=entries, exits=events):
            for check in checks:self._audit(available,'WMA_GAP_MINUTE_EVALUATION',status,check,checkpoint=t)
            self._audit(available,'DIRECTIONAL_DECISION',status,{
                **self._directional_decision_payload(bar or FiveMinuteBar(t,float(minute.open),float(minute.high),float(minute.low),float(minute.close),None),decision),
                'bar_timestamp':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
                'minute_timestamp':t.isoformat(),'decision_timestamp':available.isoformat(),
                'minute_ohlcv':dict(open=float(minute.open),high=float(minute.high),low=float(minute.low),close=float(minute.close),volume=getattr(minute,'volume',None)),
                'nifty_close':float(minute.close),'wma_gap_checks':checks,'reconstructed':recovered,
                'setup_attempts':setups,'exit_validation':exit_validation,'exit_warning_time':self.warning_time,
                'completed_5m_indicators':dict(rsi9=latest.rsi9,ema3=latest.ema3_rsi,wma21=latest.wma21_rsi) if latest else None,
                'canonical_setup_events':[e.event_type for e in canonical_decision.accepted_events] if canonical_decision else [],
                'canonical_suppressed_events':[e.event_type for e in canonical_decision.suppressed_events] if canonical_decision else [],
                'canonical_owner':self.canonical.trade_owner,
                'canonical_bullish_conditions':dict(self.canonical.bullish.last_decision_payload or {}),
                'canonical_bearish_conditions':dict(self.canonical.bearish.last_decision_payload or {}),
                'event_details':[dict(event_type=e.event_type,entry_price=e.entry_price,
                    entry_time=e.entry_time.isoformat() if e.entry_time else None,price=e.price,points=e.points,
                    exit_reason=e.exit_reason) for e in events],
            },checkpoint=t)
        if not recovered:
            for event in events:
                if event.event_type in EXIT_TYPES:
                    self._close_option(direction=direction(event),now=available,exit_boundary=available,
                        exit_reason=event.exit_reason or event.event_type,audit=True)
            for event in entries:
                label=datetime.fromisoformat(event.details['wma_gap']['signal_timestamp'])
                signal_bar=bars.get(label) or (bars.get(self._last_bar_ts) if self._last_bar_ts else None)
                if signal_bar is None:raise ValueError('ENTRY_REFERENCE_BAR_UNAVAILABLE')
                self._start_option(direction=direction(event),now=available,bar=signal_bar,event=event,audit=True)
        self._last_minute=t
        return decision

    def process_cutoff(self, now, *, intraday):
        at=datetime.combine(now.date(),time(14,55),tzinfo=IST)
        if now<at or self._cutoff_done_date==now.date():return None
        price=self._minute_open(intraday,at)
        if price is None:
            self._audit(now,'DIRECTIONAL_SESSION_CUTOFF','WAITING',dict(cutoff_timestamp=at.isoformat(),reason='EXACT_1455_OPEN_UNAVAILABLE'))
            return None
        before=self.gate.owner;events=[]
        if before!='NONE':
            event=StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if before=='BULLISH'
                else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',at,None,'ACTIVE','IDLE',exit_reason='SESSION_CUTOFF_1455')
            closed=self.gate.close(event,at,price)
            if closed:events.append(closed)
        self.canonical.on_session_cutoff(at,price)
        self.gate.locked=True;self.gate.pending.clear()
        decision=self._decision(at,before,events,'SESSION_CUTOFF_NO_REENTRY')
        for event in events:self._close_option(direction=direction(event),now=now,exit_boundary=at,exit_reason=event.exit_reason,audit=True)
        self._audit(now,'DIRECTIONAL_SESSION_CUTOFF','PROCESSED',{
            'cutoff_timestamp':at.isoformat(),'decision_timestamp':at.isoformat(),
            'accepted_events':[e.event_type for e in events],
            'event_details':[dict(event_type=e.event_type,entry_time=e.entry_time.isoformat(),entry_price=e.entry_price,price=e.price,points=e.points,exit_reason=e.exit_reason) for e in events],
            'trade_owner_before':before,'trade_owner_after':self.gate.owner,'session_date':now.date().isoformat(),
            'bullish_state':self.directional.bullish.session.name,'bearish_state':self.directional.bearish.session.name,
            'bullish_armed':False,'bearish_armed':False,'last_completed_bar':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
        })
        self._cutoff_done_date=now.date()
        return decision
