from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(label, "already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(label, "patched")
    return text.replace(old, new, 1)

# Production wiring
p = Path("backend/market_lab/live_shadow_production_wiring_v1.py")
text = p.read_text()
if "from .live_shadow_step_audit_v1 import" not in text:
    anchor = "from .live_shadow_source_integration_v1 import to_shadow_option_minute\n"
    if anchor not in text:
        raise SystemExit("wiring import anchor not found")
    text = text.replace(anchor, anchor + "from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1, normalized_checkpoint_payload\n", 1)

text = replace_once(text,
'''    def __init__(self, *, engine, config_id:int, market_sources, events_path, health_path):
        self.engine=engine; self.config_id=config_id; self.sources=market_sources
        self.adapter=LiveShadowRuntimeAdapterV1(events_path)
        self.features=LiveNormalizedFeatureProducerV1()
        self.health=HealthJournal(health_path)
        self._bootstrapped=False
''',
'''    def __init__(self, *, engine, config_id:int, market_sources, events_path, health_path, step_audit_path="data/live-observation/shadow-v1/step-audit.jsonl"):
        self.engine=engine; self.config_id=config_id; self.sources=market_sources
        self.adapter=LiveShadowRuntimeAdapterV1(events_path)
        self.features=LiveNormalizedFeatureProducerV1()
        self.health=HealthJournal(health_path)
        self.step_audit=ShadowStepAuditStoreV1(step_audit_path)
        self._bootstrapped=False
''', "coordinator init")

text = replace_once(text,
'''        if snap is None:
            self.health.append({"model":MODEL,"checkpoint":checkpoint.isoformat(),"state":"MISSING","reason":"NO_SNAPSHOT_WITHIN_30S"})
            return {"status":"MISSING_SNAPSHOT"}
''',
'''        if snap is None:
            self.health.append({"model":MODEL,"checkpoint":checkpoint.isoformat(),"state":"MISSING","reason":"NO_SNAPSHOT_WITHIN_30S"})
            self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="SNAPSHOT_SELECTION", status="MISSING", payload={"reason":"NO_SNAPSHOT_WITHIN_30S","max_delay_seconds":30})
            return {"status":"MISSING_SNAPSHOT"}
''', "missing snapshot audit")

text = replace_once(text,
'''        self.features.add_snapshot(snap,checkpoint_timestamp=checkpoint)
        cp=self.features.build_current()
        self.health.append({
''',
'''        self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="SNAPSHOT_SELECTION", status="SELECTED", payload={"received_at":snap.received_at.isoformat(),"delay_ms":(snap.received_at-checkpoint).total_seconds()*1000.0})
        self.features.add_snapshot(snap,checkpoint_timestamp=checkpoint)
        cp=self.features.build_current()
        self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="NORMALIZED_FEATURES", status="CALCULATED", payload=normalized_checkpoint_payload(cp))
        self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="DATA_HEALTH", status="ALLOWED" if cp.health_allowed else "BLOCKED", payload={"health_state":cp.health_state,"health_reason":cp.health_reason,"source_delay_ms":cp.source_delay_ms})
        self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="ALL3_DECISION", status=cp.all3_state, payload={"state_5m":cp.state_5m,"state_10m":cp.state_10m,"state_15m":cp.state_15m,"previous_directional_all3":cp.previous_directional_all3})
        self.health.append({
''', "checkpoint feature audit")

text = replace_once(text,
'''            futures=self.sources.futures_oi_at_checkpoint(checkpoint)
            shadow_cp=to_shadow_checkpoint(cp,futures_oi_state=futures.state if futures.health_allowed else None)
            outcome=self.adapter.on_candle2(oid,shadow_cp)
''',
'''            self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="C2_ELIGIBILITY", status="DUE", observation_id=oid, payload={"candle1_timestamp":s.all3_candle1_timestamp})
            try:
                futures=self.sources.futures_oi_at_checkpoint(checkpoint)
            except Exception as exc:
                self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="FUTURES_FETCH", status="FAILED", observation_id=oid, payload={"error":str(exc)})
                self.adapter.shadow.incomplete(oid,checkpoint,"FUTURES_FETCH_FAILED")
                continue
            self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="FUTURES_FETCH", status="AVAILABLE" if futures.health_allowed else "BLOCKED", observation_id=oid, payload={"instrument_key":futures.instrument_key,"state":futures.state,"price_change":futures.price_change,"oi_change":futures.oi_change,"previous_close":futures.previous_close,"close":futures.close,"previous_oi":futures.previous_oi,"oi":futures.oi,"health_state":futures.health_state,"health_reason":futures.health_reason})
            shadow_cp=to_shadow_checkpoint(cp,futures_oi_state=futures.state if futures.health_allowed else None)
            outcome=self.adapter.on_candle2(oid,shadow_cp)
            self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="C2_DECISION", status=outcome, observation_id=oid, payload={"all3_state":cp.all3_state,"futures_state":futures.state,"spot_c2":cp.spot})
''', "C2/futures audit")

text = replace_once(text,
'''                if not instrument:
                    self.adapter.shadow.incomplete(oid,checkpoint,"NO_EXACT_ATM_INSTRUMENT")
                else:
                    self.adapter.on_exact_option_resolved(oid,ExactOptionResolution(
                        timestamp=checkpoint,atm_strike=cp.moving_atm,option_instrument_key=instrument
                    ))
''',
'''                if not instrument:
                    self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="OPTION_RESOLUTION", status="MISSING", observation_id=oid, payload={"atm_strike":cp.moving_atm,"direction":s.direction})
                    self.adapter.shadow.incomplete(oid,checkpoint,"NO_EXACT_ATM_INSTRUMENT")
                else:
                    resolved=self.adapter.on_exact_option_resolved(oid,ExactOptionResolution(timestamp=checkpoint,atm_strike=cp.moving_atm,option_instrument_key=instrument))
                    self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="OPTION_RESOLUTION", status=resolved, observation_id=oid, payload={"atm_strike":cp.moving_atm,"direction":s.direction,"instrument_key":instrument})
''', "option resolution audit")

text = replace_once(text,
'''        shadow_cp=to_shadow_checkpoint(cp,futures_oi_state=None)
        oid=self.adapter.on_new_all3(shadow_cp,cp.previous_directional_all3)
        return {"status":"PROCESSED","checkpoint":checkpoint.isoformat(),"all3":cp.all3_state,"observation_id":oid}
''',
'''        shadow_cp=to_shadow_checkpoint(cp,futures_oi_state=None)
        oid=self.adapter.on_new_all3(shadow_cp,cp.previous_directional_all3)
        self.step_audit.append(event_time=datetime.now(IST), checkpoint=checkpoint, stage="CANDIDATE_DETECTION", status="DETECTED" if oid else "NO_NEW_CANDIDATE", observation_id=oid, payload={"all3_state":cp.all3_state,"previous_directional_all3":cp.previous_directional_all3,"spot":cp.spot})
        return {"status":"PROCESSED","checkpoint":checkpoint.isoformat(),"all3":cp.all3_state,"observation_id":oid}
''', "candidate audit")

text = replace_once(text,
'''                if len(match)==1:
                    self.adapter.on_exact_next_minute_open(oid,ExactNextMinuteOpen(timestamp=entry_ts,price=match[0].open))
                elif now>=entry_ts+timedelta(minutes=2):
                    self.adapter.shadow.incomplete(oid,now,"MISSING_EXACT_NEXT_MINUTE_OPEN")
''',
'''                if len(match)==1:
                    opened=self.adapter.on_exact_next_minute_open(oid,ExactNextMinuteOpen(timestamp=entry_ts,price=match[0].open))
                    self.step_audit.append(event_time=now, checkpoint=confirmation, stage="ENTRY_OPEN", status=opened, observation_id=oid, payload={"entry_timestamp":entry_ts.isoformat(),"entry_price":match[0].open,"instrument_key":s.option_instrument_key})
                elif now>=entry_ts+timedelta(minutes=2):
                    self.step_audit.append(event_time=now, checkpoint=confirmation, stage="ENTRY_OPEN", status="MISSING", observation_id=oid, payload={"expected_entry_timestamp":entry_ts.isoformat()})
                    self.adapter.shadow.incomplete(oid,now,"MISSING_EXACT_NEXT_MINUTE_OPEN")
''', "entry audit")

text = replace_once(text,
'''                status=self.adapter.on_option_minute(oid,to_shadow_option_minute(bar,h))
                if status in FINAL:
                    break
''',
'''                status=self.adapter.on_option_minute(oid,to_shadow_option_minute(bar,h))
                current=self.adapter.states()[oid]
                self.step_audit.append(event_time=now, checkpoint=None, stage="OPTION_MINUTE", status=status, observation_id=oid, payload={"bar_timestamp":bar.timestamp.isoformat(),"open":bar.open,"high":bar.high,"low":bar.low,"close":bar.close,"active_stop_price":current.active_stop_price,"best_price_seen":current.best_price_seen,"breakeven_armed":current.breakeven_armed,"trail_armed":current.trail_armed,"exit_reason":current.exit_reason,"net_return_pct":current.net_return_pct})
                if status in FINAL:
                    break
''', "option minute audit")

p.write_text(text)
print("production wiring updated")

# Worker
p=Path("backend/market_lab/live_shadow_worker_v1.py")
text=p.read_text()
text=replace_once(text,
'''        health_path='data/live-observation/shadow-v1/data-health.jsonl',
    )
''',
'''        health_path='data/live-observation/shadow-v1/data-health.jsonl',
        step_audit_path='data/live-observation/shadow-v1/step-audit.jsonl',
    )
''', "shadow worker audit path")
p.write_text(text)

# API
p=Path("backend/market_lab/live_shadow_ui_v1.py")
text=p.read_text()
if "from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1" not in text:
    text="from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1\n"+text
if "STEP_AUDIT_PATH =" not in text:
    text=text.replace('HEALTH_PATH = DATA_DIR / "data-health.jsonl"\n','HEALTH_PATH = DATA_DIR / "data-health.jsonl"\nSTEP_AUDIT_PATH = DATA_DIR / "step-audit.jsonl"\n',1)
if '"step_audit_file_present"' not in text:
    text=text.replace('        "health_file_present": HEALTH_PATH.exists(),\n','        "health_file_present": HEALTH_PATH.exists(),\n        "step_audit_file_present": STEP_AUDIT_PATH.exists(),\n',1)
if '@router.get("/step-audit")' not in text:
    text += '''\n\n@router.get("/step-audit")\ndef live_shadow_step_audit(limit: int = 200):\n    if limit < 1 or limit > 2000:\n        raise HTTPException(422, "limit must be between 1 and 2000")\n    if not STEP_AUDIT_PATH.exists():\n        return {"chain_ok": True, "chain_issue": None, "rows": []}\n    store = ShadowStepAuditStoreV1(STEP_AUDIT_PATH)\n    ok, issue = store.verify_chain()\n    rows = store.read_all()[-limit:]\n    rows.reverse()\n    return {"chain_ok": ok, "chain_issue": issue, "rows": rows}\n'''
p.write_text(text)
print("live shadow API updated")

# Frontend
p=Path("frontend/src/liveShadow.tsx")
text=p.read_text()
if "import LiveShadowStepAudit from './liveShadowStepAudit'" not in text:
    text="import LiveShadowStepAudit from './liveShadowStepAudit'\n"+text
if "<LiveShadowStepAudit/>" not in text:
    anchor='''    <section className="panel shadow-panel">\n      <div className="panel-heading"><div><h2>Live observations</h2>'''
    if anchor not in text:
        raise SystemExit("frontend live observations anchor not found")
    text=text.replace(anchor,'''    <LiveShadowStepAudit/>\n\n    <section className="panel shadow-panel">\n      <div className="panel-heading"><div><h2>Live observations</h2>''',1)
p.write_text(text)
styles=Path("frontend/src/styles.css")
current=styles.read_text()
addition=Path("frontend/src/liveShadowStepAudit.css").read_text()
if "/* LIVE_SHADOW_STEP_AUDIT_V1 */" not in current:
    styles.write_text(current.rstrip()+"\n\n"+addition.strip()+"\n")
print("frontend updated")
