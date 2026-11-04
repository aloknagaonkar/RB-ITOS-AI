"""Live observation adapter for the tested historical alignment + dual-exit policy."""
from copy import deepcopy
from .hilega_candle_evidence_v1 import input_context, audit_fields
from datetime import datetime, timedelta, time
import json
from .hilega_v2_alignment_replay_v1 import cache_index, candles, aggregate_exact_5m
from .hilega_milega_strategy_v1 import SessionState
from .hilega_milega_bearish_strategy_v1 import BearishSessionState
from .hilega_wma_gap_live_v2 import HilegaWmaGapLiveCoordinatorV2
from .hilega_v2_alignment_replay_v1 import (
    ExitFirstCanonical, WmaGapGate, dual_exit, direction, ENTRY_TYPES, EXIT_TYPES, decision_checkpoint,
)
from .hilega_milega_strategy_v1 import FiveMinuteBar, StrategyEvent
from .domain import IST
from .hilega_opening_reference_v1 import capture_opening_reference, confirmation_reference
from .hilega_combined_policy_v1 import RULES, POLICY_ID, VERSION, PriceFrames, make_gate, advance_boundary, reset_pending
STRATEGY_ID = 'HILEGA_V2_ALIGNMENT_DUAL_EXIT'

class HilegaAlignmentDualExitLiveCoordinator(HilegaWmaGapLiveCoordinatorV2):
    strategy_id = STRATEGY_ID
    canonical_factory = ExitFirstCanonical
    gate_factory = WmaGapGate

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reset_policy_session()

    def _consume(self, intraday, now, *, recovered):
        with input_context(self, intraday):
            return super()._consume(intraday, now, recovered=recovered)

    def _audit(self, now, stage, status, payload=None, **kwargs):
        if stage in {
            "DIRECTIONAL_DECISION", "DIRECTIONAL_SESSION_CUTOFF",
            "COMBINED_PRICE_OBSERVATION", "COMBINED_FIVE_MINUTE_EVALUATION",
        }:
            fields = audit_fields(self)
            if fields:
                payload = {**(payload or {}), **fields}
        return super()._audit(now, stage, status, payload, **kwargs)

    def _reset_policy_session(self):
        self.episode = {'BULLISH': False, 'BEARISH': False}
        self.warning_time = None
        self._manual_exit_seen = set()
        if not hasattr(self,'price_frames'):
            self.price_frames=PriceFrames();self.gate=make_gate(self.price_frames.frames)

    def _safe(self):
        return {**super()._safe(), 'model':'HILEGA_ALIGNMENT_DUAL_EXIT_LIVE_V1',
                'strategy_id':STRATEGY_ID, 'strategy_version':RULES['version'],
                'policy_id':POLICY_ID, 'entry_policy':RULES['setup'],
                'exit_policy':RULES['exit'], 'same_candle_exit_entry_enabled':True,
                'strategy_rules':RULES}

    def bootstrap(self, now):
        now=now.astimezone(IST)
        if self._bootstrapped_date==now.date():return {'status':'ALREADY_BOOTSTRAPPED'}
        # Identical local warmup roots and ordering as historical auto replay.
        # No additional historical broker downloads are introduced.
        self.canonical=self.canonical_factory();self.price_frames=PriceFrames();self.gate=make_gate(self.price_frames.frames)
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
                self.price_frames.seed(bar)
            warmup_sessions+=1
        if warmup_sessions<20:raise ValueError('COMBINED_TWENTY_WARMUP_SESSIONS_REQUIRED')
        if not self.canonical.bullish.previous_indicators or not self.canonical.bullish.previous_indicators.ready:
            raise ValueError('ALIGNMENT_LIVE_LOCAL_WARMUP_NOT_READY')
        self._opening_reference = capture_opening_reference(self.canonical, now.date())
        self.canonical.bullish.session=SessionState(session_date=now.date())
        self.canonical.bearish.session=BearishSessionState(session_date=now.date())
        for engine in (self.canonical.bullish,self.canonical.bearish):
            engine.previous_indicators=None;engine.previous_bar=None
        self.canonical.trade_owner='NONE';self.canonical.session_date=now.date()
        self._reset_policy_session()
        self._consume(self.sources.nifty_intraday_1m(now=now),now,recovered=True)
        self._sync_view()
        restore=self._restore_audited_option_state(now=now,session_date=now.date())
        from .hilega_manual_exit_strategy_v1 import after_bootstrap
        after_bootstrap(self,now)
        self._bootstrapped_date=now.date()
        self._audit(now,'DIRECTIONAL_LIVE_BOOTSTRAP','PASS',{
            'session_date':now.date().isoformat(),'trade_owner':self.gate.owner,
            'bullish_state':self.directional.bullish.session.name,'bearish_state':self.directional.bearish.session.name,
            'last_completed_bar':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            'reconstructed':True,'option_restore':restore,'warmup_sessions':warmup_sessions,
            'opening_reference_timestamp':self._opening_reference.bar_timestamp.isoformat() if self._opening_reference else None,
            'opening_reference_policy':'PRIOR_SESSION_FIRST_CANDLE_ONLY',
            'warmup_policy':'HISTORICAL_LOCAL_CACHE_ORDER'})
        return {'status':'BOOTSTRAPPED'}

    def _audited_option_restore_plan(self, session_date):
        original=self.step_audit.read_all
        self.step_audit.read_all=lambda:[r for r in original() if (r.get('payload') or {}).get('strategy_version')==VERSION]
        try:return super()._audited_option_restore_plan(session_date)
        finally:self.step_audit.read_all=original

    def _advance(self, minute, bars, *, recovered):
        t=minute.timestamp.astimezone(IST);available=t+timedelta(minutes=1)
        from .hilega_manual_exit_strategy_v1 import apply_manual_control
        manual_block=apply_manual_control(self,available,recovered=recovered)
        before=self.gate.owner
        bar=bars.get(t-timedelta(minutes=4)) if t.minute%5==4 else None
        if bar is None:
            if not recovered:self._audit(available,'COMBINED_PRICE_OBSERVATION','PROCESSED',dict(decision_timestamp=available.isoformat(),nifty_close=float(minute.close),policy_id=POLICY_ID,strategy_version=VERSION,accepted_events=[]),checkpoint=t)
            self._last_minute=t
            return self._decision(available,before,[],'COMBINED_WAIT_COMPLETED_5M')
        reference=confirmation_reference(self.canonical.bullish.previous_indicators,getattr(self,'_opening_reference',None),t)
        result=advance_boundary(self.canonical,self.gate,bar,reference,self.price_frames,manual_block)
        canonical_decision=result['decision'];latest=result['current']
        entries=result['entries'];events=result['exits']+entries;checks=result['checks']
        setups=result['setups'];exit_validation=result['exit_validation'];pending_switches=result['pending_switches']
        self._last_bar_ts=bar.ts
        if exit_validation and exit_validation['rsi_opposite'] and self.warning_time is None:self.warning_time=available.isoformat()
        if entries:self.warning_time=None
        decision=self._decision(available,before,events,POLICY_ID)
        status='RECOVERED' if recovered else 'PROCESSED'
        if True:
            for check in checks:self._audit(available,'COMBINED_FIVE_MINUTE_EVALUATION',status,check,checkpoint=t)
            self._audit(available,'DIRECTIONAL_DECISION',status,{
                **self._directional_decision_payload(bar or FiveMinuteBar(t,float(minute.open),float(minute.high),float(minute.low),float(minute.close),None),decision),
                'bar_timestamp':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
                'minute_timestamp':t.isoformat(),'decision_timestamp':available.isoformat(),
                'minute_ohlcv':dict(open=float(minute.open),high=float(minute.high),low=float(minute.low),close=float(minute.close),volume=getattr(minute,'volume',None)),
                'nifty_close':float(minute.close),'wma_gap_checks':checks,'reconstructed':recovered,
                'policy_id':POLICY_ID,'strategy_version':VERSION,'strategy_rules':RULES,
                'policy_events':result['policy_events'],'price_ema_frame':result['frame'],
                'pending_candidates':{k:v['available'].isoformat() for k,v in self.gate.pending.items()},
                'followup_reference':{k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in getattr(self.gate,'followup_signal',{}).items()} if getattr(self.gate,'followup_signal',None) else None,
                'opposite_confirmation':result.get('opposite_confirmation'),
                'setup_attempts':setups,'pending_switches':pending_switches,'exit_validation':exit_validation,'exit_warning_time':self.warning_time,
                'completed_5m_indicators':dict(rsi9=latest.rsi9,ema3=latest.ema3_rsi,wma21=latest.wma21_rsi) if latest else None,
                'five_minute_changes':dict(rsi9=latest.rsi9-reference.rsi9,ema3=latest.ema3_rsi-reference.ema3_rsi,wma21=latest.wma21_rsi-reference.wma21_rsi) if latest and reference else None,
                'canonical_setup_events':[e.event_type for e in canonical_decision.accepted_events] if canonical_decision else [],
                'canonical_suppressed_events':[e.event_type for e in canonical_decision.suppressed_events] if canonical_decision else [],
                'canonical_owner':self.canonical.trade_owner,
                'canonical_bullish_conditions':dict(self.canonical.bullish.last_decision_payload or {}),
                'canonical_bearish_conditions':dict(self.canonical.bearish.last_decision_payload or {}),
                'event_details':[dict(event_type=e.event_type,event_time=e.event_time.isoformat(),entry_price=e.entry_price,
                    entry_time=e.entry_time.isoformat() if e.entry_time else None,price=e.price,points=e.points,
                    exit_reason=e.exit_reason,policy_id=POLICY_ID,strategy_version=VERSION,qualified_signal_time=e.details.get('qualified_signal_time') if e.details else None,combined_entry=e.details.get('combined_entry') if e.details else None) for e in events],
            },checkpoint=t)
        if not recovered:
            for event in events:
                if event.event_type in EXIT_TYPES:
                    self._close_option(direction=direction(event),now=available,exit_boundary=available,
                        exit_reason=event.exit_reason or event.event_type,audit=True)
            for event in entries:
                label=datetime.fromisoformat(event.details['wma_gap']['signal_timestamp'])
                qualified=event.details.get('qualified_signal_time')
                signal_bar=bars.get(datetime.fromisoformat(qualified)-timedelta(minutes=5)) if qualified else None
                signal_bar=signal_bar or bars.get(label) or (bars.get(self._last_bar_ts) if self._last_bar_ts else None)
                if signal_bar is None:raise ValueError('ENTRY_REFERENCE_BAR_UNAVAILABLE')
                self._start_option(direction=direction(event),now=available,bar=signal_bar,event=event,audit=True)
        self._last_minute=t
        return decision

    def process_cutoff(self, now, *, intraday):
        with input_context(self, intraday):
            return self._process_cutoff_from_rows(now, intraday=intraday)

    def _process_cutoff_from_rows(self, now, *, intraday):
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
        self.gate.locked=True;reset_pending(self.gate)
        decision=self._decision(at,before,events,'SESSION_CUTOFF_NO_REENTRY')
        for event in events:self._close_option(direction=direction(event),now=now,exit_boundary=at,exit_reason=event.exit_reason,audit=True)
        self._audit(now,'DIRECTIONAL_SESSION_CUTOFF','PROCESSED',{
            'cutoff_timestamp':at.isoformat(),'decision_timestamp':at.isoformat(),
            'accepted_events':[e.event_type for e in events],
            'policy_id':POLICY_ID,'strategy_version':VERSION,
            'event_details':[dict(event_type=e.event_type,event_time=e.event_time.isoformat(),entry_time=e.entry_time.isoformat(),entry_price=e.entry_price,price=e.price,points=e.points,exit_reason=e.exit_reason) for e in events],
            'trade_owner_before':before,'trade_owner_after':self.gate.owner,'session_date':now.date().isoformat(),
            'bullish_state':self.directional.bullish.session.name,'bearish_state':self.directional.bearish.session.name,
            'bullish_armed':False,'bearish_armed':False,'last_completed_bar':self._last_bar_ts.isoformat() if self._last_bar_ts else None,
        })
        self._cutoff_done_date=now.date()
        return decision
