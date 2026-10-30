from fastapi import FastAPI
from fastapi.testclient import TestClient
import market_lab.historical_replay_operations_api_v1 as api

def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api,"JOBS_ROOT",tmp_path/"jobs")
    monkeypatch.setattr(api,"readiness",lambda d:{
        "session_date":d.isoformat(),
        "checkpoint_replay_ready":True,
        "snapshots":{"status":"AVAILABLE","records":100},
        "futures":{"status":"AVAILABLE","records":385},
    })
    app=FastAPI(); app.include_router(api.router); return TestClient(app)

def test_readiness(tmp_path, monkeypatch):
    c=make_client(tmp_path,monkeypatch)
    body=c.get("/api/live-shadow/replay-ops/readiness?session_date=2026-09-18").json()
    assert body["readiness"]["checkpoint_replay_ready"] is True

def test_job_not_found(tmp_path, monkeypatch):
    c=make_client(tmp_path,monkeypatch)
    assert c.get("/api/live-shadow/replay-ops/job/nope").status_code==404

def test_run_launches_job(tmp_path, monkeypatch):
    c=make_client(tmp_path,monkeypatch)
    class Dummy: pass
    monkeypatch.setattr(api.subprocess,"Popen",lambda *a,**k: Dummy())
    body=c.post("/api/live-shadow/replay-ops/run",json={"session_date":"2026-09-18","overwrite":True}).json()
    assert body["status"]=="QUEUED"
    assert body["action"]=="RUN_REPLAY"
    assert (api.JOBS_ROOT/f'{body["job_id"]}.json').exists()

def test_run_blocks_when_not_ready(tmp_path, monkeypatch):
    c=make_client(tmp_path,monkeypatch)
    monkeypatch.setattr(api,"readiness",lambda d:{"checkpoint_replay_ready":False})
    r=c.post("/api/live-shadow/replay-ops/run",json={"session_date":"2026-09-18"})
    assert r.status_code==409
