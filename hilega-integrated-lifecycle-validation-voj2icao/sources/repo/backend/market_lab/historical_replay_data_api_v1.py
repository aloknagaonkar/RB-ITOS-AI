from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .historical_replay_data_v1 import (
    download_exact_option,
    download_missing,
    readiness,
)

router = APIRouter(prefix="/api/live-shadow/replay-data", tags=["live-shadow-replay-data"])


class DownloadOptionRequest(BaseModel):
    session_date: date
    instrument_key: str


@router.get("/readiness")
def replay_data_readiness(session_date: date):
    return readiness(session_date)


@router.post("/download-missing")
def replay_download_missing(session_date: date):
    try:
        return download_missing(session_date)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_type": type(exc).__name__,
                "message": str(exc),
                "session_date": session_date.isoformat(),
            },
        ) from exc


@router.post("/download-option")
def replay_download_option(request: DownloadOptionRequest):
    try:
        return download_exact_option(request.session_date, request.instrument_key)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_type": type(exc).__name__,
                "message": str(exc),
                "session_date": request.session_date.isoformat(),
                "instrument_key": request.instrument_key,
            },
        ) from exc
