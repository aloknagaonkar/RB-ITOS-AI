from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/live-shadow/replay-ops/historical-oi/enriched")
ROOT = Path("data/historical-evidence/historical-oi-enrichment")


@router.get("/sessions")
def enriched_sessions():
    sessions = []
    if ROOT.exists():
        for p in sorted(ROOT.glob("*/enriched.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            sessions.append({
                "session_date": doc.get("session_date") or p.parent.name,
                "rows": doc.get("row_count", len(doc.get("rows") or [])),
                "source_mode": doc.get("source_mode"),
                "fixed_atm": doc.get("fixed_atm"),
                "status_counts": doc.get("status_counts") or {},
            })
    return {"source":"ENRICHED","sessions":sessions}


@router.get("/rows")
def enriched_rows(session_date: str = Query(..., alias="date")):
    p = ROOT / session_date / "enriched.json"
    if not p.exists():
        raise HTTPException(404, f"Enriched Historical OI session not found: {session_date}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {
        "source":"ENRICHED",
        "session_date":session_date,
        "source_mode":doc.get("source_mode"),
        "fixed_atm":doc.get("fixed_atm"),
        "status_counts":doc.get("status_counts") or {},
        "rows":doc.get("rows") or [],
    }
