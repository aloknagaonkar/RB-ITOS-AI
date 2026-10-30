import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import market_lab.historical_replay_ui_api_v1 as api


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in rows) + "\n")


def fixture(root: Path):
    d = root / "2026-09-18"
    d.mkdir(parents=True)
    (d / "replay-status.json").write_text(json.dumps({
        "status": "COMPLETE",
        "model": "HISTORICAL_REPLAY_ENGINE_V1_1",
        "checkpoint_count": 2,
        "processed_checkpoint_count": 2,
        "observation_count": 1,
        "state_counts": {"CLOSED": 1},
        "step_audit_chain_ok": True,
    }))
    (d / "checkpoints.json").write_text(json.dumps([
        {"status": "PROCESSED", "checkpoint": "2026-09-18T09:55:00+05:30"}
    ]))
    write_jsonl(d / "health.jsonl", [{"checkpoint":"2026-09-18T09:55:00+05:30","health_state":"DEGRADED"}])
    write_jsonl(d / "events.jsonl", [{
        "event_time":"2026-09-18T09:55:00+05:30",
        "event_type":"OBSERVATION_DETECTED",
        "observation_id":"OBS-1",
        "payload":{"direction":"BULLISH"},
    }])
    # We don't use verify_chain in timeline tests, so synthetic audit hashes are unnecessary here.
    write_jsonl(d / "step-audit.jsonl", [
        {"checkpoint":"2026-09-18T09:55:00+05:30","event_time":"2026-09-18T09:55:00+05:30","stage":"NORMALIZED_FEATURES","status":"CALCULATED","observation_id":None,"payload":{"spot":23327.6,"moving_atm":23350,"state_5m":"BULLISH","state_10m":"BULLISH","state_15m":"BULLISH","all3_state":"BULLISH_ALL_3","horizons":{}}},
        {"checkpoint":"2026-09-18T09:55:00+05:30","event_time":"2026-09-18T09:55:00+05:30","stage":"ALL3_DECISION","status":"BULLISH_ALL_3","observation_id":None,"payload":{}},
        {"checkpoint":"2026-09-18T09:55:00+05:30","event_time":"2026-09-18T09:55:00+05:30","stage":"CANDIDATE_DETECTION","status":"DETECTED","observation_id":"OBS-1","payload":{}},
    ])
    return d


def client(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr(api, "REPLAY_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_sessions(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    body = c.get("/api/live-shadow/replay/sessions").json()
    assert body["sessions"][0]["session_date"] == "2026-09-18"
    assert body["sessions"][0]["status"] == "COMPLETE"


def test_status(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    body = c.get("/api/live-shadow/replay/status?date=2026-09-18").json()
    assert body["status"]["observation_count"] == 1


def test_timeline_aggregates_strategy_stages(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    rows = c.get("/api/live-shadow/replay/timeline?date=2026-09-18").json()["rows"]
    assert len(rows) == 1
    assert rows[0]["summary"]["state_5m"] == "BULLISH"
    assert rows[0]["summary"]["all3_state"] == "BULLISH_ALL_3"
    assert rows[0]["summary"]["candidate"] == "DETECTED"
    assert rows[0]["observation_events"]["OBS-1"][0]["event_type"] == "OBSERVATION_DETECTED"


def test_invalid_date_rejected(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.get("/api/live-shadow/replay/status?date=../../etc").status_code == 400
