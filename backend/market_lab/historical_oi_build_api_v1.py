from __future__ import annotations
import json, subprocess, sys, uuid
from datetime import date
from pathlib import Path
from typing import Any
from fastapi import HTTPException
from pydantic import BaseModel
from .historical_oi_build_job_v1 import ROOT, build_paths, validate_request

class HistoricalOiBuildRequestV1(BaseModel):
    session_date: str
    expiry: str

def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(404, "Historical OI build job not found.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"Historical OI build status is unreadable: {exc}")

def start_build(body: HistoricalOiBuildRequestV1) -> dict[str, Any]:
    try:
        validate_request(body.session_date, body.expiry)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    paths = build_paths(body.session_date)
    if paths["status"].exists():
        old = _read(paths["status"])
        if old.get("status") in {"QUEUED","RUNNING"}:
            raise HTTPException(409, f"A build is already {old.get('status')} for {body.session_date}.")
    job_id = uuid.uuid4().hex
    queued = {"model":"HISTORICAL_OI_BUILD_API_V1","job_id":job_id,"session_date":body.session_date,"expiry":body.expiry,"status":"QUEUED","started_at":None,"completed_at":None,"result":None,"error":None}
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["status"].write_text(json.dumps(queued, indent=2) + "\n", encoding="utf-8")
    subprocess.Popen(
        [sys.executable,"-m","market_lab.historical_oi_build_job_v1","--job-id",job_id,"--session-date",body.session_date,"--expiry",body.expiry],
        cwd=".", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return queued

def build_status(session_date: str) -> dict[str, Any]:
    try:
        date.fromisoformat(session_date)
    except ValueError:
        raise HTTPException(422, "session_date must be YYYY-MM-DD.")
    return _read(build_paths(session_date)["status"])

def built_dates() -> dict[str, Any]:
    rows=[]
    if ROOT.exists():
        for child in sorted(ROOT.iterdir(), reverse=True):
            if not child.is_dir():
                continue
            try:
                date.fromisoformat(child.name)
            except ValueError:
                continue
            p=child/"build-status.json"
            if not p.exists():
                continue
            try:
                v=json.loads(p.read_text(encoding="utf-8"))
            except (OSError,json.JSONDecodeError):
                continue
            rows.append({"session_date":child.name,"expiry":v.get("expiry"),"status":v.get("status"),"row_count":(v.get("result") or {}).get("row_count"),"positioning_csv":(v.get("artifacts") or {}).get("positioning_csv")})
    return {"model":"HISTORICAL_OI_BUILD_API_V1","rows":rows}
