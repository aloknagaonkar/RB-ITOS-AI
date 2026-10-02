from pathlib import Path
import shutil
T=Path("backend/market_lab/live_shadow_production_wiring_v1.py")
B=T.with_suffix(T.suffix+".pre-anchor-recovery-v1")
I="from .live_fixed_session_anchor_recovery_v1 import LiveFixedSessionAnchorManagerV1\n"
INIT='        self.engine=engine;self.config_id=config_id;self.sources=market_sources;self.adapter=LiveShadowRuntimeAdapterV1(events_path);self.features=LiveNormalizedFeatureProducerV1();self.health=HealthJournal(health_path);self._bootstrapped=False\n'
BUILD='        self.features.add_snapshot(snap,checkpoint_timestamp=checkpoint)\n        cp=self.features.build_current()\n'
HEALTH='        self.health.append({"model":MODEL,"checkpoint":checkpoint.isoformat(),"source_received_at":cp.source_received_at.isoformat(),"source_delay_ms":cp.source_delay_ms,"health_state":cp.health_state,"health_allowed":cp.health_allowed,"health_reason":cp.health_reason,"all3_state":cp.all3_state})\n'
if not T.exists(): raise SystemExit(f"ABORT: missing {T}")
s=T.read_text()
if "FIXED_SESSION_ANCHOR" in s and "LiveFixedSessionAnchorManagerV1" in s: print("Already patched:",T); raise SystemExit(0)
if not B.exists(): shutil.copy2(T,B); print("Backup:",B)
a="from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1, normalized_checkpoint_payload\n"
if a not in s: raise SystemExit("ABORT: import anchor not found")
s=s.replace(a,a+I,1)
if s.count(INIT)!=1: raise SystemExit(f"ABORT: init anchor count {s.count(INIT)}")
s=s.replace(INIT,INIT+'        self.fixed_session_anchor=LiveFixedSessionAnchorManagerV1(engine=engine,config_id=config_id)\n',1)
if s.count(BUILD)!=1: raise SystemExit(f"ABORT: build anchor count {s.count(BUILD)}")
extra='''        fixed_anchor=self.fixed_session_anchor.ensure(checkpoint)\n        fixed_metrics=self.fixed_session_anchor.metrics(snap,checkpoint)\n        self.step_audit.append(\n            event_time=datetime.now(IST),checkpoint=checkpoint,stage="FIXED_SESSION_ANCHOR",status=fixed_anchor.status,\n            payload={"provenance":fixed_anchor.provenance,"checkpoint_time":fixed_anchor.checkpoint_time,"source_candle_time":fixed_anchor.source_candle_time,"source_semantics":fixed_anchor.source_semantics,"provider":fixed_anchor.provider,"spot":fixed_anchor.spot,"atm":fixed_anchor.atm,"strikes":list(fixed_anchor.strikes),"contract_count":len(fixed_anchor.legs),"ce_total":fixed_anchor.ce_total,"pe_total":fixed_anchor.pe_total,"fixed_pcr":fixed_anchor.fixed_pcr,"fallback_used":fixed_anchor.fallback_used,"issue":fixed_anchor.issue,"fixed_session":fixed_metrics.payload() if fixed_metrics is not None else None},\n        )\n'''
s=s.replace(BUILD,BUILD+extra,1)
if s.count(HEALTH)!=1: raise SystemExit(f"ABORT: health anchor count {s.count(HEALTH)}")
new='''        self.health.append({"model":MODEL,"checkpoint":checkpoint.isoformat(),"source_received_at":cp.source_received_at.isoformat(),"source_delay_ms":cp.source_delay_ms,"health_state":cp.health_state,"health_allowed":cp.health_allowed,"health_reason":cp.health_reason,"all3_state":cp.all3_state,"fixed_session_anchor":{"status":fixed_anchor.status,"provenance":fixed_anchor.provenance,"checkpoint_time":fixed_anchor.checkpoint_time,"source_candle_time":fixed_anchor.source_candle_time,"source_semantics":fixed_anchor.source_semantics,"provider":fixed_anchor.provider,"spot":fixed_anchor.spot,"atm":fixed_anchor.atm,"strikes":list(fixed_anchor.strikes),"contract_count":len(fixed_anchor.legs),"ce_total":fixed_anchor.ce_total,"pe_total":fixed_anchor.pe_total,"fixed_pcr":fixed_anchor.fixed_pcr,"fallback_used":fixed_anchor.fallback_used,"issue":fixed_anchor.issue},"fixed_session":fixed_metrics.payload() if fixed_metrics is not None else None})\n'''
s=s.replace(HEALTH,new,1)
T.write_text(s)
print("Patched:",T)
print("ALL3/candidate/order logic unchanged; fixed-session recovery is audit/health sidecar data.")
