from datetime import date
import json
from pathlib import Path
import market_lab.historical_replay_operations_api_v1 as api

def test_pid_alive_false_for_impossible_pid():
    assert api._pid_alive(999999999) is False

def test_reconcile_dead_running_job(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "JOBS_ROOT", tmp_path)
    path = tmp_path / "abc.json"
    payload = {"job_id":"abc","session_date":"2026-09-18","status":"RUNNING","pid":999999999}
    path.write_text(json.dumps(payload))
    out = api._reconcile_stale(path, payload)
    assert out["status"] == "FAILED"
    assert out["stale_recovered"] is True

def test_dataset_semantics():
    rows = api._dataset_semantics({"datasets":[
        {"name":"snapshots","status":"MISSING"},
        {"name":"futures","status":"MISSING"},
        {"name":"exact_option","status":"ON_DEMAND"},
    ]})
    by = {x["name"]:x for x in rows}
    assert by["snapshots"]["operation_status"] == "NOT_DOWNLOADABLE"
    assert by["futures"]["operation_status"] == "DOWNLOADABLE"
    assert by["exact_option"]["operation_status"] == "ON_DEMAND"

def test_jobs_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "JOBS_ROOT", tmp_path)
    (tmp_path/"a.json").write_text(json.dumps({"job_id":"a","session_date":"2026-09-18","status":"COMPLETE"}))
    (tmp_path/"b.json").write_text(json.dumps({"job_id":"b","session_date":"2026-09-17","status":"COMPLETE"}))
    rows = api.replay_ops_jobs(limit=20, session_date=date(2026,9,18))["rows"]
    assert [x["job_id"] for x in rows] == ["a"]

def test_frontend_hardening_markers():
    replay = Path("frontend/src/historicalReplay.tsx").read_text()
    ops = Path("frontend/src/historicalReplayOperations.tsx").read_text()
    assert 'type="date"' in replay
    assert "<datalist" in replay
    assert "/api/live-shadow/replay-ops/jobs?limit=20&session_date=" in ops
    assert "Run / replace replay" in ops
