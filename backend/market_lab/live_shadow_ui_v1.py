from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .live_observational_shadow_v1 import (
    AuditStore,
    daily_summary,
    reconstruct_states,
)

MODEL = "LIVE_SHADOW_UI_V1"
router = APIRouter(prefix="/api/live-shadow", tags=["live-shadow"])

DATA_DIR = Path("data/live-observation/shadow-v1")
EVENTS_PATH = DATA_DIR / "events.jsonl"
HEALTH_PATH = DATA_DIR / "data-health.jsonl"


def _states() -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    store = AuditStore(EVENTS_PATH)
    values = reconstruct_states(store.read_all()).values()
    rows = [asdict(x) for x in values]
    rows.sort(
        key=lambda x: (
            x.get("all3_candle1_timestamp") or "",
            x.get("observation_id") or "",
        ),
        reverse=True,
    )
    return rows


def _read_jsonl(path: Path, limit: int = 300) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append(
                    {
                        "state": "UNHEALTHY",
                        "reason": "MALFORMED_HEALTH_RECORD",
                        "raw": line[:500],
                    }
                )
    return rows[-limit:]


def _event_history(observation_id: str) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    return [
        x
        for x in AuditStore(EVENTS_PATH).read_all()
        if x.get("observation_id") == observation_id
    ]


@router.get("/status")
def live_shadow_status():
    states = _states()
    open_states = {"OPEN", "BE_ARMED", "TRAIL_ARMED"}
    store = AuditStore(EVENTS_PATH)
    chain_ok, chain_issue = store.verify_chain() if EVENTS_PATH.exists() else (True, None)
    health = _read_jsonl(HEALTH_PATH, 1)
    latest_health = health[-1] if health else None

    return {
        "model": MODEL,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "event_file_present": EVENTS_PATH.exists(),
        "health_file_present": HEALTH_PATH.exists(),
        "event_chain_ok": chain_ok,
        "event_chain_issue": chain_issue,
        "observation_count": len(states),
        "open_trade_count": sum(x.get("status") in open_states for x in states),
        "closed_trade_count": sum(x.get("status") == "CLOSED" for x in states),
        "rejected_count": sum(x.get("status") == "REJECTED" for x in states),
        "incomplete_count": sum(x.get("status") == "INCOMPLETE" for x in states),
        "latest_health": latest_health,
    }


@router.get("/observations")
def live_shadow_observations(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(422, "limit must be between 1 and 1000")
    return _states()[:limit]


@router.get("/trades")
def live_shadow_trades(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(422, "limit must be between 1 and 1000")
    trade_states = {"OPEN", "BE_ARMED", "TRAIL_ARMED", "CLOSED"}
    return [x for x in _states() if x.get("status") in trade_states][:limit]


@router.get("/health")
def live_shadow_health(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(422, "limit must be between 1 and 1000")
    rows = _read_jsonl(HEALTH_PATH, limit)
    rows.reverse()
    return rows


@router.get("/daily-summary")
def live_shadow_daily_summary(session_date: date):
    states = reconstruct_states(AuditStore(EVENTS_PATH).read_all()).values() if EVENTS_PATH.exists() else []
    return daily_summary(states, session_date.isoformat())


@router.get("/observation/{observation_id}")
def live_shadow_observation(observation_id: str):
    matches = [x for x in _states() if x.get("observation_id") == observation_id]
    if not matches:
        raise HTTPException(404, "Shadow observation not found")
    return {
        "observation": matches[0],
        "events": _event_history(observation_id),
    }
