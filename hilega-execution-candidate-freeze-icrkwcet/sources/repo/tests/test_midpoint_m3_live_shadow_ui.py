import json
from pathlib import Path

from market_lab.midpoint_strategy import live_shadow_ui as ui


def test_empty_status_is_safe(tmp_path: Path, monkeypatch):
    p = tmp_path / "missing.jsonl"
    monkeypatch.setattr(ui, "AUDIT_PATH", p)
    s = ui.status()
    assert s["audit_record_count"] == 0
    assert s["family_b_state"] == "IDLE"
    assert s["safety"]["observation_only"] is True
    assert s["safety"]["execution_enabled"] is False
    assert s["safety"]["paper_order_enabled"] is False
    assert s["safety"]["quantity"] is None


def test_status_and_detail_projection(tmp_path: Path, monkeypatch):
    p = tmp_path / "audit.jsonl"
    row = {
        "event_id":"x1",
        "event_timestamp":"2026-09-29T09:42:00+05:30",
        "event_type":"B_ENTRY",
        "state_after":"ACTIVE",
        "result":"SHADOW_ENTRY",
        "observation_only":True,
        "execution_enabled":False,
        "paper_order_enabled":False,
        "quantity":None,
    }
    p.write_text(json.dumps(row)+"\n")
    monkeypatch.setattr(ui, "AUDIT_PATH", p)

    s = ui.status()
    assert s["latest_entry"]["event_id"] == "x1"
    assert s["family_b_state"] == "ACTIVE"
    assert ui.audit_detail("x1")["event"]["event_id"] == "x1"
