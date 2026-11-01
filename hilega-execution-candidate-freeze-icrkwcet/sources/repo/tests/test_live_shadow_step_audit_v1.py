from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

IST = ZoneInfo("Asia/Kolkata")


def test_step_audit_hash_chain(tmp_path: Path):
    p = tmp_path / "step.jsonl"
    s = ShadowStepAuditStoreV1(p)
    t = datetime(2026, 9, 18, 11, 5, tzinfo=IST)
    s.append(event_time=t, checkpoint=t, stage="SNAPSHOT_SELECTION", status="SELECTED", payload={"delay_ms": 9000})
    s.append(event_time=t, checkpoint=t, stage="ALL3_DECISION", status="BEARISH_ALL_3", payload={"state_5m": "BEARISH"})
    ok, issue = s.verify_chain()
    assert ok is True and issue is None


def test_step_audit_detects_edit(tmp_path: Path):
    p = tmp_path / "step.jsonl"
    s = ShadowStepAuditStoreV1(p)
    t = datetime(2026, 9, 18, 11, 5, tzinfo=IST)
    s.append(event_time=t, checkpoint=t, stage="DATA_HEALTH", status="ALLOWED", payload={"x": 1})
    p.write_text(p.read_text().replace('"x": 1', '"x": 2'))
    ok, issue = s.verify_chain()
    assert ok is False
    assert "hash mismatch" in issue


def test_step_audit_api_empty(tmp_path: Path, monkeypatch):
    import market_lab.live_shadow_ui_v1 as ui
    monkeypatch.setattr(ui, "STEP_AUDIT_PATH", tmp_path / "missing.jsonl")
    out = ui.live_shadow_step_audit(limit=10)
    assert out["chain_ok"] is True
    assert out["rows"] == []
