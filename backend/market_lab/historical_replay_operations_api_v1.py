from __future__ import annotations
import json, subprocess, sys, uuid
from datetime import date
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .historical_replay_data_v1 import readiness

MODEL = "HISTORICAL_REPLAY_OPERATIONS_API_V1"
JOBS_ROOT = Path("data/live-observation/replay-jobs")
router = APIRouter(prefix="/api/live-shadow/replay-ops", tags=["historical-replay-operations"])

class ReplayRunRequest(BaseModel):
    session_date: date
    overwrite: bool = False

class ReplayDownloadRequest(BaseModel):
    session_date: date

def _job_path(job_id: str) -> Path:
    return JOBS_ROOT / f"{job_id}.json"

def _read_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise HTTPException(404, f"Replay job not found: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))

def _active_for_date(session_date: date) -> dict[str, Any] | None:
    if not JOBS_ROOT.exists():
        return None
    for path in sorted(JOBS_ROOT.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("session_date")==session_date.isoformat() and payload.get("status") in {"QUEUED","RUNNING"}:
            return payload
    return None

def _launch(action: str, session_date: date, *, overwrite: bool=False) -> dict[str, Any]:
    active = _active_for_date(session_date)
    if active is not None:
        raise HTTPException(409, {"message":"A replay operation is already active for this date.","job":active})
    job_id = uuid.uuid4().hex
    status_path = _job_path(job_id)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    initial = {"model":MODEL,"job_id":job_id,"action":action,
               "session_date":session_date.isoformat(),"status":"QUEUED",
               "started_at":None,"completed_at":None,"result":None,"error":None}
    status_path.write_text(json.dumps(initial, indent=2)+"\n", encoding="utf-8")
    log_dir = JOBS_ROOT/"logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir/f"{job_id}.out.log"
    stderr_path = log_dir/f"{job_id}.err.log"
    cmd = [sys.executable,"-m","market_lab.historical_replay_operations_worker_v1",
           "--job-id",job_id,"--action",action,"--date",session_date.isoformat(),
           "--status-path",str(status_path)]
    if overwrite:
        cmd.append("--overwrite")
    with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
    return {**initial,"stdout_log":str(stdout_path),"stderr_log":str(stderr_path)}

@router.get("/readiness")
def replay_ops_readiness(session_date: date):
    return {"model":MODEL,"session_date":session_date.isoformat(),"readiness":readiness(session_date)}

@router.post("/download-missing")
def replay_ops_download_missing(request: ReplayDownloadRequest):
    return _launch("DOWNLOAD_MISSING", request.session_date)

@router.post("/run")
def replay_ops_run(request: ReplayRunRequest):
    current = readiness(request.session_date)
    ready = bool(current.get("checkpoint_replay_ready") or current.get("checkpoint_ready")
                 or current.get("full_replay_prerequisites_ready")
                 or current.get("full_trade_replay_prerequisites_ready"))
    if not ready:
        raise HTTPException(409, {"message":"Replay prerequisites are not ready. Check readiness/download missing first.","readiness":current})
    return _launch("RUN_REPLAY", request.session_date, overwrite=request.overwrite)

@router.get("/job/{job_id}")
def replay_ops_job(job_id: str):
    return _read_job(job_id)

@router.get("/jobs")
def replay_ops_jobs(limit: int=20):
    limit=max(1,min(limit,100))
    rows=[]
    if JOBS_ROOT.exists():
        paths=sorted(JOBS_ROOT.glob("*.json"), key=lambda p:p.stat().st_mtime, reverse=True)[:limit]
        for path in paths:
            try: rows.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception: pass
    return {"model":MODEL,"rows":rows}
