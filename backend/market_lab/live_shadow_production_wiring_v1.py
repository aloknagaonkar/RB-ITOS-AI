from __future__ import annotations
import json
from datetime import datetime,timedelta
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from .domain import IST,Snapshot
from .live_normalized_feature_producer_v1 import LiveNormalizedFeatureProducerV1
from .live_normalized_shadow_bridge_v1 import to_shadow_checkpoint
from .live_observational_shadow_runtime_adapter_v1 import ExactNextMinuteOpen,ExactOptionResolution,LiveShadowRuntimeAdapterV1
from .live_option_minute_source_v1 import LiveOptionMinuteSourceV1
from .live_shadow_source_integration_v1 import to_shadow_option_minute
from .storage import Observation
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1, normalized_checkpoint_payload
from .live_fixed_session_anchor_recovery_v1 import LiveFixedSessionAnchorManagerV1
MODEL="LIVE_SHADOW_PRODUCTION_WIRING_V1";FINAL={"CLOSED","REJECTED","INCOMPLETE"}

def floor_5m(ts):
    local=ts.astimezone(IST);m=local.minute-local.minute%5;return local.replace(minute=m,second=0,microsecond=0)

def select_first_snapshot_at_or_after(engine,config_id,checkpoint,*,max_delay_seconds=30):
    session_date=checkpoint.astimezone(IST).date().isoformat()
    with Session(engine) as s:rows=s.scalars(select(Observation).where(Observation.config_id==config_id,Observation.session_date==session_date).order_by(Observation.id)).all()
    candidates=[]
    for row in rows:
        snap=Snapshot.model_validate(row.snapshot)
        if snap.received_at>=checkpoint and (snap.received_at-checkpoint).total_seconds()<=max_delay_seconds:candidates.append((snap.received_at,snap))
    return min(candidates,key=lambda x:x[0])[1] if candidates else None
class HealthJournal:
    def __init__(self,path):self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
    def append(self,payload):
        with self.path.open('a') as f:f.write(json.dumps(payload,sort_keys=True,default=str)+'\n')
class LiveShadowProductionCoordinatorV1:
    def __init__(self,*,engine,config_id,market_sources,events_path,health_path, step_audit_path="data/live-observation/shadow-v1/step-audit.jsonl"):
        self.engine=engine;self.config_id=config_id;self.sources=market_sources;self.adapter=LiveShadowRuntimeAdapterV1(events_path);self.features=LiveNormalizedFeatureProducerV1();self.health=HealthJournal(health_path);self._bootstrapped=False
        self.fixed_session_anchor=LiveFixedSessionAnchorManagerV1(engine=engine,config_id=config_id)
        self.step_audit = ShadowStepAuditStoreV1(step_audit_path)
    def bootstrap(self,checkpoint,*,lookback_minutes=30):
        if self._bootstrapped:return
        t=checkpoint-timedelta(minutes=lookback_minutes)
        while t<checkpoint:
            snap=select_first_snapshot_at_or_after(self.engine,self.config_id,t)
            if snap is not None:
                try:self.features.add_snapshot(snap,checkpoint_timestamp=t);self.features.build_current()
                except ValueError:pass
            t+=timedelta(minutes=5)
        self._bootstrapped=True
    def process_checkpoint(self,checkpoint):
        checkpoint=floor_5m(checkpoint)
        self.bootstrap(checkpoint)
        snap=select_first_snapshot_at_or_after(self.engine,self.config_id,checkpoint)

        if snap is None:
            self.health.append({"model":MODEL,"checkpoint":checkpoint.isoformat(),"state":"MISSING","reason":"NO_SNAPSHOT_WITHIN_30S"})
            self.step_audit.append(
                event_time=datetime.now(IST),
                checkpoint=checkpoint,
                stage="SNAPSHOT_SELECTION",
                status="MISSING",
                payload={"reason":"NO_SNAPSHOT_WITHIN_30S"},
            )
            return {"status":"MISSING_SNAPSHOT"}

        self.step_audit.append(
            event_time=datetime.now(IST),
            checkpoint=checkpoint,
            stage="SNAPSHOT_SELECTION",
            status="SELECTED",
            payload={
                "source_received_at":snap.received_at.isoformat(),
                "source_delay_ms":(snap.received_at-checkpoint).total_seconds()*1000.0,
            },
        )

        self.features.add_snapshot(snap,checkpoint_timestamp=checkpoint)
        cp=self.features.build_current()
        fixed_anchor=self.fixed_session_anchor.ensure(checkpoint)
        fixed_metrics=self.fixed_session_anchor.metrics(snap,checkpoint)
        self.step_audit.append(
            event_time=datetime.now(IST),checkpoint=checkpoint,stage="FIXED_SESSION_ANCHOR",status=fixed_anchor.status,
            payload={"provenance":fixed_anchor.provenance,"checkpoint_time":fixed_anchor.checkpoint_time,"source_candle_time":fixed_anchor.source_candle_time,"source_semantics":fixed_anchor.source_semantics,"provider":fixed_anchor.provider,"spot":fixed_anchor.spot,"atm":fixed_anchor.atm,"strikes":list(fixed_anchor.strikes),"contract_count":len(fixed_anchor.legs),"ce_total":fixed_anchor.ce_total,"pe_total":fixed_anchor.pe_total,"fixed_pcr":fixed_anchor.fixed_pcr,"fallback_used":fixed_anchor.fallback_used,"issue":fixed_anchor.issue,"fixed_session":fixed_metrics.payload() if fixed_metrics is not None else None},
        )

        self.step_audit.append(
            event_time=datetime.now(IST),
            checkpoint=checkpoint,
            stage="NORMALIZED_FEATURES",
            status="CALCULATED",
            payload=normalized_checkpoint_payload(cp),
        )

        self.step_audit.append(
            event_time=datetime.now(IST),
            checkpoint=checkpoint,
            stage="DATA_HEALTH",
            status="ALLOWED" if cp.health_allowed else "BLOCKED",
            payload={
                "health_state":cp.health_state,
                "health_reason":cp.health_reason,
                "source_delay_ms":cp.source_delay_ms,
            },
        )

        self.step_audit.append(
            event_time=datetime.now(IST),
            checkpoint=checkpoint,
            stage="ALL3_DECISION",
            status=cp.all3_state,
            payload={
                "state_5m":cp.state_5m,
                "state_10m":cp.state_10m,
                "state_15m":cp.state_15m,
                "previous_directional_all3":cp.previous_directional_all3,
            },
        )

        self.health.append({"model":MODEL,"checkpoint":checkpoint.isoformat(),"source_received_at":cp.source_received_at.isoformat(),"source_delay_ms":cp.source_delay_ms,"health_state":cp.health_state,"health_allowed":cp.health_allowed,"health_reason":cp.health_reason,"all3_state":cp.all3_state,"fixed_session_anchor":{"status":fixed_anchor.status,"provenance":fixed_anchor.provenance,"checkpoint_time":fixed_anchor.checkpoint_time,"source_candle_time":fixed_anchor.source_candle_time,"source_semantics":fixed_anchor.source_semantics,"provider":fixed_anchor.provider,"spot":fixed_anchor.spot,"atm":fixed_anchor.atm,"strikes":list(fixed_anchor.strikes),"contract_count":len(fixed_anchor.legs),"ce_total":fixed_anchor.ce_total,"pe_total":fixed_anchor.pe_total,"fixed_pcr":fixed_anchor.fixed_pcr,"fallback_used":fixed_anchor.fallback_used,"issue":fixed_anchor.issue},"fixed_session":fixed_metrics.payload() if fixed_metrics is not None else None})
        for oid,s in list(self.adapter.states().items()):
            if s.status!="DETECTED" or not s.candle1_timestamp:continue
            c1=datetime.fromisoformat(s.candle1_timestamp)
            if c1+timedelta(minutes=5)!=checkpoint:continue
            self.step_audit.append(
                event_time=datetime.now(IST),
                checkpoint=checkpoint,
                stage="C2_ELIGIBILITY",
                status="DUE",
                observation_id=oid,
                payload={
                    "direction":s.direction,
                    "candle1_timestamp":s.candle1_timestamp,
                },
            )

            try:
                futures=self.sources.futures_oi_at_checkpoint(checkpoint)
                fstate=futures.state if futures.health_allowed else None

                self.step_audit.append(
                    event_time=datetime.now(IST),
                    checkpoint=checkpoint,
                    stage="FUTURES_FETCH",
                    status="AVAILABLE" if futures.health_allowed else "BLOCKED",
                    observation_id=oid,
                    payload={
                        "state":getattr(futures,"state",None),
                        "price_change":getattr(futures,"price_change",None),
                        "oi_change":getattr(futures,"oi_change",None),
                        "health_state":getattr(futures,"health_state",None),
                        "health_reason":getattr(futures,"health_reason",None),
                    },
                )

            except Exception as exc:
                self.step_audit.append(
                    event_time=datetime.now(IST),
                    checkpoint=checkpoint,
                    stage="FUTURES_FETCH",
                    status="FAILED",
                    observation_id=oid,
                    payload={
                        "error_type":type(exc).__name__,
                        "error":str(exc),
                    },
                )

                self.adapter.shadow.incomplete(
                    oid,
                    checkpoint,
                    "FUTURES_DATA_UNAVAILABLE",
                )
                continue

            outcome=self.adapter.on_candle2(
                oid,
                to_shadow_checkpoint(
                    cp,
                    futures_oi_state=fstate,
                ),
            )

            self.step_audit.append(
                event_time=datetime.now(IST),
                checkpoint=checkpoint,
                stage="C2_DECISION",
                status=outcome,
                observation_id=oid,
                payload={
                    "direction":s.direction,
                    "all3_state":cp.all3_state,
                    "futures_state":fstate,
                    "spot_c2":cp.spot,
                },
            )

            if outcome=="CLASSIFIED":
                instrument=(
                    cp.ce_instrument_key
                    if s.direction=="BULLISH"
                    else cp.pe_instrument_key
                )

                if not instrument:
                    self.step_audit.append(
                        event_time=datetime.now(IST),
                        checkpoint=checkpoint,
                        stage="OPTION_RESOLUTION",
                        status="MISSING",
                        observation_id=oid,
                        payload={
                            "direction":s.direction,
                            "moving_atm":cp.moving_atm,
                        },
                    )

                    self.adapter.shadow.incomplete(
                        oid,
                        checkpoint,
                        "NO_EXACT_ATM_INSTRUMENT",
                    )

                else:
                    resolved=self.adapter.on_exact_option_resolved(
                        oid,
                        ExactOptionResolution(
                            checkpoint,
                            cp.moving_atm,
                            instrument,
                        ),
                    )

                    self.step_audit.append(
                        event_time=datetime.now(IST),
                        checkpoint=checkpoint,
                        stage="OPTION_RESOLUTION",
                        status=resolved,
                        observation_id=oid,
                        payload={
                            "direction":s.direction,
                            "moving_atm":cp.moving_atm,
                            "instrument_key":instrument,
                        },
                    )
        oid=self.adapter.on_new_all3(
            to_shadow_checkpoint(
                cp,
                futures_oi_state=None,
            ),
            cp.previous_directional_all3,
        )

        self.step_audit.append(
            event_time=datetime.now(IST),
            checkpoint=checkpoint,
            stage="CANDIDATE_DETECTION",
            status="DETECTED" if oid else "NO_NEW_CANDIDATE",
            observation_id=oid,
            payload={
                "all3_state":cp.all3_state,
                "previous_directional_all3":cp.previous_directional_all3,
                "spot":cp.spot,
            },
        )

        return {
            "status":"PROCESSED",
            "checkpoint":checkpoint.isoformat(),
            "all3":cp.all3_state,
            "observation_id":oid,
        }
    def process_entries_and_open_trades(self,now):
        now=now.astimezone(IST);results=[]
        for oid,s in list(self.adapter.states().items()):
            if s.status=="OPTION_RESOLVED" and s.confirmation_timestamp and s.option_instrument_key:
                entry_ts=datetime.fromisoformat(s.confirmation_timestamp).astimezone(IST)+timedelta(minutes=1)
                if now<entry_ts+timedelta(minutes=1):continue
                bars=self.sources.option_intraday_1m(s.option_instrument_key);match=[b for b in bars if b.timestamp==entry_ts]
                if len(match)==1:
                    opened=self.adapter.on_exact_next_minute_open(
                        oid,
                        ExactNextMinuteOpen(
                            entry_ts,
                            match[0].open,
                        ),
                    )

                    self.step_audit.append(
                        event_time=now,
                        checkpoint=None,
                        stage="ENTRY_OPEN",
                        status=opened,
                        observation_id=oid,
                        payload={
                            "instrument_key":s.option_instrument_key,
                            "entry_timestamp":entry_ts.isoformat(),
                            "entry_price":match[0].open,
                        },
                    )

                elif now>=entry_ts+timedelta(minutes=2):
                    self.step_audit.append(
                        event_time=now,
                        checkpoint=None,
                        stage="ENTRY_OPEN",
                        status="MISSING",
                        observation_id=oid,
                        payload={
                            "instrument_key":s.option_instrument_key,
                            "expected_entry_timestamp":entry_ts.isoformat(),
                        },
                    )

                    self.adapter.shadow.incomplete(
                        oid,
                        now,
                        "MISSING_EXACT_NEXT_MINUTE_OPEN",
                    )
                results.append((oid,self.adapter.states()[oid].status))
        for oid,s in list(self.adapter.states().items()):
            if s.status not in {"OPEN","BE_ARMED","TRAIL_ARMED"} or not s.option_instrument_key or not s.entry_timestamp:continue
            entry=datetime.fromisoformat(s.entry_timestamp).astimezone(IST);previous=datetime.fromisoformat(s.last_bar_timestamp).astimezone(IST) if s.last_bar_timestamp else entry
            bars=self.sources.option_intraday_1m(s.option_instrument_key);completed=sorted([b for b in bars if b.timestamp>previous and b.timestamp+timedelta(minutes=1)<=now],key=lambda b:b.timestamp)
            source=LiveOptionMinuteSourceV1(s.option_instrument_key,previous_timestamp=previous)
            for bar in completed:
                h=source.process(bar)

                self.step_audit.append(
                    event_time=now,
                    checkpoint=None,
                    stage="OPTION_MINUTE_HEALTH",
                    status="ALLOWED" if h.allowed else "BLOCKED",
                    observation_id=oid,
                    payload={
                        "bar_timestamp":bar.timestamp.isoformat(),
                        "health_reason":getattr(h,"reason",None),
                    },
                )

                if not h.allowed:
                    self.step_audit.append(
                        event_time=now,
                        checkpoint=None,
                        stage="OPTION_MINUTE",
                        status="INCOMPLETE",
                        observation_id=oid,
                        payload={
                            "bar_timestamp":bar.timestamp.isoformat(),
                            "reason":h.reason or "OPTION_MINUTE_UNHEALTHY",
                        },
                    )

                    self.adapter.shadow.incomplete(
                        oid,
                        bar.timestamp,
                        h.reason or "OPTION_MINUTE_UNHEALTHY",
                    )
                    break

                status=self.adapter.on_option_minute(
                    oid,
                    to_shadow_option_minute(bar,h),
                )

                self.step_audit.append(
                    event_time=now,
                    checkpoint=None,
                    stage="OPTION_MINUTE",
                    status=status,
                    observation_id=oid,
                    payload={
                        "bar_timestamp":bar.timestamp.isoformat(),
                        "open":bar.open,
                        "high":bar.high,
                        "low":bar.low,
                        "close":bar.close,
                    },
                )

                if status in FINAL:
                    break
            results.append((oid,self.adapter.states()[oid].status))
        return results
