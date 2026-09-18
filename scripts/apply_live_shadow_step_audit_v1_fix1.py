from pathlib import Path
import re

p = Path("backend/market_lab/live_shadow_production_wiring_v1.py")
text = p.read_text()

# 1) Import
imp = "from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1, normalized_checkpoint_payload\n"
if imp not in text:
    m = re.search(r"^from \.live_shadow_source_integration_v1 import .+$", text, re.M)
    if not m:
        raise SystemExit("step-audit import: semantic anchor not found")
    text = text[:m.end()] + "\n" + imp.rstrip("\n") + text[m.end():]

# 2) Coordinator __init__ signature — tolerate formatting differences.
if "step_audit_path" not in text:
    pat = re.compile(
        r"(class LiveShadowProductionCoordinatorV1:.*?"
        r"def __init__\(\s*self\s*,\s*\*\s*,\s*engine\s*,\s*config_id\s*:\s*int\s*,"
        r"\s*market_sources\s*,\s*events_path\s*,\s*health_path)(\s*\)\s*:)",
        re.S,
    )
    m = pat.search(text)
    if not m:
        # Print the real signature to make any future mismatch immediately visible.
        sig = re.search(
            r"class LiveShadowProductionCoordinatorV1:.*?(def __init__\([^\n]+\):)",
            text,
            re.S,
        )
        actual = sig.group(1) if sig else "NOT FOUND"
        raise SystemExit(f"coordinator init: semantic match failed; actual={actual}")
    replacement = (
        m.group(1)
        + ', step_audit_path="data/live-observation/shadow-v1/step-audit.jsonl"'
        + m.group(2)
    )
    text = text[:m.start()] + replacement + text[m.end():]

# 3) Store
if "self.step_audit" not in text:
    m = re.search(
        r"^(?P<indent>\s*)self\.health\s*=\s*HealthJournal\(health_path\)\s*$",
        text,
        re.M,
    )
    if not m:
        raise SystemExit("coordinator health store semantic anchor not found")
    insert = (
        m.group(0)
        + "\n"
        + m.group("indent")
        + "self.step_audit = ShadowStepAuditStoreV1(step_audit_path)"
    )
    text = text[:m.start()] + insert + text[m.end():]

# 4) Missing snapshot audit.
if 'stage="SNAPSHOT_SELECTION", status="MISSING"' not in text:
    pat = re.compile(
        r'(?P<indent>\s*)self\.health\.append\(\{"model":MODEL,"checkpoint":checkpoint\.isoformat\(\),'
        r'"state":"MISSING","reason":"NO_SNAPSHOT_WITHIN_30S"\}\)\s*\n'
        r'(?P=indent)return \{"status":"MISSING_SNAPSHOT"\}'
    )
    m = pat.search(text)
    if not m:
        raise SystemExit("missing snapshot semantic anchor not found")
    i = m.group("indent")
    repl = (
        f'{i}self.health.append({{"model":MODEL,"checkpoint":checkpoint.isoformat(),"state":"MISSING","reason":"NO_SNAPSHOT_WITHIN_30S"}})\n'
        f'{i}self.step_audit.append(\n'
        f'{i}    event_time=datetime.now(IST), checkpoint=checkpoint,\n'
        f'{i}    stage="SNAPSHOT_SELECTION", status="MISSING",\n'
        f'{i}    payload={{"reason":"NO_SNAPSHOT_WITHIN_30S","max_delay_seconds":30}},\n'
        f'{i})\n'
        f'{i}return {{"status":"MISSING_SNAPSHOT"}}'
    )
    text = text[:m.start()] + repl + text[m.end():]

# 5) Selected snapshot + normalized features + health + ALL3 audit.
if 'stage="NORMALIZED_FEATURES"' not in text:
    pat = re.compile(
        r'(?P<indent>\s*)self\.features\.add_snapshot\(snap,\s*checkpoint_timestamp=checkpoint\)\s*\n'
        r'(?P=indent)cp\s*=\s*self\.features\.build_current\(\)\s*\n'
        r'(?P=indent)self\.health\.append\(\{'
    )
    m = pat.search(text)
    if not m:
        raise SystemExit("normalized feature semantic anchor not found")
    i = m.group("indent")
    repl = (
        f'{i}self.step_audit.append(\n'
        f'{i}    event_time=datetime.now(IST), checkpoint=checkpoint,\n'
        f'{i}    stage="SNAPSHOT_SELECTION", status="SELECTED",\n'
        f'{i}    payload={{"received_at":snap.received_at.isoformat(),'
        f'"delay_ms":(snap.received_at-checkpoint).total_seconds()*1000.0}},\n'
        f'{i})\n'
        f'{i}self.features.add_snapshot(snap, checkpoint_timestamp=checkpoint)\n'
        f'{i}cp = self.features.build_current()\n'
        f'{i}self.step_audit.append(\n'
        f'{i}    event_time=datetime.now(IST), checkpoint=checkpoint,\n'
        f'{i}    stage="NORMALIZED_FEATURES", status="CALCULATED",\n'
        f'{i}    payload=normalized_checkpoint_payload(cp),\n'
        f'{i})\n'
        f'{i}self.step_audit.append(\n'
        f'{i}    event_time=datetime.now(IST), checkpoint=checkpoint,\n'
        f'{i}    stage="DATA_HEALTH", status="ALLOWED" if cp.health_allowed else "BLOCKED",\n'
        f'{i}    payload={{"health_state":cp.health_state,"health_reason":cp.health_reason,'
        f'"source_delay_ms":cp.source_delay_ms}},\n'
        f'{i})\n'
        f'{i}self.step_audit.append(\n'
        f'{i}    event_time=datetime.now(IST), checkpoint=checkpoint,\n'
        f'{i}    stage="ALL3_DECISION", status=cp.all3_state,\n'
        f'{i}    payload={{"state_5m":cp.state_5m,"state_10m":cp.state_10m,'
        f'"state_15m":cp.state_15m,"previous_directional_all3":cp.previous_directional_all3}},\n'
        f'{i})\n'
        f'{i}self.health.append({{'
    )
    text = text[:m.start()] + repl + text[m.end():]

# 6) Candidate detection audit.
if 'stage="CANDIDATE_DETECTION"' not in text:
    pat = re.compile(
        r'(?P<indent>\s*)shadow_cp\s*=\s*to_shadow_checkpoint\(cp,\s*futures_oi_state=None\)\s*\n'
        r'(?P=indent)oid\s*=\s*self\.adapter\.on_new_all3\(shadow_cp,\s*cp\.previous_directional_all3\)\s*\n'
        r'(?P=indent)return \{"status":"PROCESSED","checkpoint":checkpoint\.isoformat\(\),"all3":cp\.all3_state,"observation_id":oid\}'
    )
    m = pat.search(text)
    if not m:
        raise SystemExit("candidate detection semantic anchor not found")
    i = m.group("indent")
    repl = (
        f'{i}shadow_cp = to_shadow_checkpoint(cp, futures_oi_state=None)\n'
        f'{i}oid = self.adapter.on_new_all3(shadow_cp, cp.previous_directional_all3)\n'
        f'{i}self.step_audit.append(\n'
        f'{i}    event_time=datetime.now(IST), checkpoint=checkpoint,\n'
        f'{i}    stage="CANDIDATE_DETECTION",\n'
        f'{i}    status="DETECTED" if oid else "NO_NEW_CANDIDATE",\n'
        f'{i}    observation_id=oid,\n'
        f'{i}    payload={{"all3_state":cp.all3_state,'
        f'"previous_directional_all3":cp.previous_directional_all3,"spot":cp.spot}},\n'
        f'{i})\n'
        f'{i}return {{"status":"PROCESSED","checkpoint":checkpoint.isoformat(),'
        f'"all3":cp.all3_state,"observation_id":oid}}'
    )
    text = text[:m.start()] + repl + text[m.end():]

p.write_text(text)
print("Patched production wiring with semantic/regex matching.")
print("Step-audit coordinator init is now installed.")
