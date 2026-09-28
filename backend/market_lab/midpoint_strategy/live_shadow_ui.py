from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .config import MidpointShadowConfig
from .replay import load_audit_jsonl
from .workspace_contract import midpoint_workspace_status

MODEL = "MIDPOINT_STRATEGY_LIVE_SHADOW_UI_V1"
DATA_DIR = Path("data/live-observation/midpoint-strategy-v1")
AUDIT_PATH = DATA_DIR / "audit.jsonl"

router = APIRouter(
    prefix="/api/live-shadow/midpoint-strategy",
    tags=["live-shadow-midpoint-strategy"],
)


def _rows() -> list[dict[str, Any]]:
    return load_audit_jsonl(AUDIT_PATH) if AUDIT_PATH.exists() else []


def _latest(rows: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for row in reversed(rows):
        if row.get("event_type") == event_type:
            return row
    return None


def _latest_family_state(rows: list[dict[str, Any]]) -> str:
    for row in reversed(rows):
        state = row.get("state_after")
        if state:
            return str(state)
    return "IDLE"


@router.get("/status")
def status():
    cfg = MidpointShadowConfig()
    cfg.assert_safe()

    rows = _rows()
    counts = Counter(str(row.get("event_type")) for row in rows)

    latest = rows[-1] if rows else None
    latest_entry = _latest(rows, "B_ENTRY")
    latest_plus20 = _latest(rows, "PLUS20_PROOF")
    latest_classifier = _latest(rows, "RUNNER_CLASSIFICATION")
    latest_degraded = _latest(rows, "DEGRADED_STARTED")
    latest_recovery = _latest(rows, "DEGRADED_TARGET_RECOVERED")
    latest_rescue = _latest(rows, "CAP20_RESCUE_TRIGGERED")
    latest_reentry = _latest(rows, "POST_CAP20_REENTRY_TRIGGERED")

    workspace = midpoint_workspace_status(cfg)

    return {
        "model": MODEL,
        "workspace": workspace,
        "audit_path": str(AUDIT_PATH),
        "audit_exists": AUDIT_PATH.exists(),
        "audit_record_count": len(rows),
        "event_counts": dict(counts),
        "family_b_state": _latest_family_state(rows),
        "latest_event": latest,
        "latest_entry": latest_entry,
        "latest_plus20": latest_plus20,
        "latest_classifier": latest_classifier,
        "latest_degraded": latest_degraded,
        "latest_recovery": latest_recovery,
        "latest_rescue": latest_rescue,
        "latest_reentry": latest_reentry,
        "safety": {
            "observation_only": cfg.observation_only,
            "execution_enabled": cfg.execution_enabled,
            "paper_order_enabled": cfg.paper_order_enabled,
            "quantity": cfg.quantity,
        },
    }


@router.get("/events")
def events(
    limit: int = Query(default=200, ge=1, le=2000),
    event_type: str | None = None,
):
    rows = _rows()
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]

    return {
        "model": MODEL,
        "count": min(len(rows), limit),
        "events": rows[-limit:],
    }


@router.get("/timeline")
def timeline(limit: int = Query(default=500, ge=1, le=5000)):
    rows = _rows()
    return {
        "model": MODEL,
        "count": min(len(rows), limit),
        "timeline": [
            {
                "event_id": r.get("event_id"),
                "timestamp": r.get("event_timestamp"),
                "event_type": r.get("event_type"),
                "direction": r.get("direction"),
                "state_before": r.get("state_before"),
                "state_after": r.get("state_after"),
                "result": r.get("result"),
                "reason": r.get("reason"),
                "underlying_price": r.get("underlying_price"),
                "directional_points": r.get("directional_points"),
            }
            for r in rows[-limit:]
        ],
    }


@router.get("/audit-detail")
def audit_detail(event_id: str):
    rows = _rows()
    for row in rows:
        if row.get("event_id") == event_id:
            return {
                "model": MODEL,
                "event": row,
            }
    raise HTTPException(status_code=404, detail="Midpoint audit event not found")
