from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .hilega_directional_live_shadow_v1 import (
    STRATEGY_ID,
    STRATEGY_VERSION,
)
from .hilega_directional_trade_dashboard_v1 import (
    project_directional_shadow_dashboard,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HILEGA_DIRECTIONAL_LIVE_SHADOW_UI_V1"
DATA_DIR = Path("data/live-observation/hilega-directional-v1")
STEP_AUDIT_PATH = DATA_DIR / "step-audit.jsonl"
router = APIRouter(
    prefix="/api/live-shadow/hilega-directional",
    tags=["live-shadow-hilega-directional"],
)


def _store() -> ShadowStepAuditStoreV1:
    return ShadowStepAuditStoreV1(STEP_AUDIT_PATH)


def _rows() -> list[dict[str, Any]]:
    return _store().read_all() if STEP_AUDIT_PATH.exists() else []


def _state_payload(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    # A cutoff/acquisition record may be the newest audit record without carrying
    # coordinator state. Never replace the last known directional state with
    # synthetic NONE/null values merely because such a record was appended later.
    state_rows = []
    for row in rows:
        if row.get("stage") not in {
            "DIRECTIONAL_DECISION",
            "DIRECTIONAL_LIVE_BOOTSTRAP",
            "DIRECTIONAL_SESSION_CUTOFF",
        }:
            continue

        payload = row.get("payload") or {}

        carries_directional_state = any(
            key in payload
            for key in (
                "trade_owner_after",
                "trade_owner",
                "bullish_state",
                "bearish_state",
            )
        )

        if carries_directional_state:
            state_rows.append(row)

    latest = state_rows[-1] if state_rows else None
    payload = (latest or {}).get("payload") or {}

    owner = payload.get(
        "trade_owner_after",
        payload.get("trade_owner", "NONE"),
    )

    return {
        "trade_owner": owner,
        "bullish_state": payload.get("bullish_state"),
        "bearish_state": payload.get("bearish_state"),
        "bullish_armed": payload.get("bullish_armed"),
        "bearish_armed": payload.get("bearish_armed"),
        "last_completed_bar": payload.get(
            "bar_timestamp",
            payload.get("last_completed_bar"),
        ),
    }, latest


def _latest_event_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    accepted = suppressed = None
    for row in reversed(rows):
        if row.get("stage") not in {
            "DIRECTIONAL_DECISION",
            "DIRECTIONAL_SESSION_CUTOFF",
        }:
            continue
        p = row.get("payload") or {}
        if accepted is None and p.get("accepted_events"):
            accepted = row
        if suppressed is None and p.get("suppressed_events"):
            suppressed = row
        if accepted is not None and suppressed is not None:
            break
    return accepted, suppressed


@router.get("/status")
def status():
    rows = _rows()
    store = _store()
    chain_ok, chain_issue = store.verify_chain() if STEP_AUDIT_PATH.exists() else (True, None)
    current, latest_state = _state_payload(rows)
    latest_accepted, latest_suppressed = _latest_event_rows(rows)
    counts = Counter(row.get("stage") for row in rows)
    selected = os.getenv("LIVE_SHADOW_STRATEGY", "").strip().upper()
    return {
        "model": MODEL,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "selected_live_shadow_strategy": selected or None,
        "directional_mode_active": selected == STRATEGY_ID,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "quantity": None,
        "account_pnl_rupees": None,
        "step_audit_present": STEP_AUDIT_PATH.exists(),
        "step_audit_chain_ok": chain_ok,
        "step_audit_chain_issue": chain_issue,
        "record_counts": dict(counts),
        "current": current,
        "latest_state_record": latest_state,
        "latest_accepted_record": latest_accepted,
        "latest_suppressed_record": latest_suppressed,
    }


@router.get("/events")
def events(limit: int = 200):
    if limit < 1 or limit > 2000:
        raise HTTPException(422, "limit must be between 1 and 2000")
    out = []
    for row in _rows():
        if row.get("stage") not in {
            "DIRECTIONAL_DECISION",
            "DIRECTIONAL_LIVE_BOOTSTRAP",
            "DIRECTIONAL_SESSION_CUTOFF",
        }:
            continue
        p = row.get("payload") or {}
        out.append({
            "event_time": row.get("event_time"),
            "checkpoint": row.get("checkpoint"),
            "stage": row.get("stage"),
            "status": row.get("status"),
            "bar_timestamp": p.get("bar_timestamp", p.get("last_completed_bar")),
            "trade_owner_before": p.get("trade_owner_before"),
            "trade_owner_after": p.get("trade_owner_after", p.get("trade_owner")),
            "bullish_state": p.get("bullish_state"),
            "bearish_state": p.get("bearish_state"),
            "bullish_armed": p.get("bullish_armed"),
            "bearish_armed": p.get("bearish_armed"),
            "accepted_events": p.get("accepted_events") or [],
            "suppressed_events": p.get("suppressed_events") or [],
            "note": p.get("note"),
        })
    return out[-limit:][::-1]


@router.get("/trade-dashboard")
def trade_dashboard():
    return project_directional_shadow_dashboard(_rows())
