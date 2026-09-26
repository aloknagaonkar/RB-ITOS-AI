from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .hilega_directional_live_shadow_v1 import STRATEGY_ID, STRATEGY_VERSION
from .hilega_directional_trade_dashboard_v1 import project_directional_shadow_dashboard
from .hilega_market_evidence_v1 import verify_journal
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HILEGA_DIRECTIONAL_LIVE_SHADOW_UI_V1"
DATA_DIR = Path("data/live-observation/hilega-directional-v1")
STEP_AUDIT_PATH = DATA_DIR / "step-audit.jsonl"
EVIDENCE_ROOT = Path("data/live-observation/hilega-directional-market-evidence-v1")
router = APIRouter(prefix="/api/live-shadow/hilega-directional", tags=["live-shadow-hilega-directional"])


def _store() -> ShadowStepAuditStoreV1:
    return ShadowStepAuditStoreV1(STEP_AUDIT_PATH)


def _rows() -> list[dict[str, Any]]:
    return _store().read_all() if STEP_AUDIT_PATH.exists() else []


def _record_session(row: dict[str, Any]) -> str | None:
    payload = row.get("payload") or {}
    for value in (
        payload.get("session_date"), payload.get("bar_timestamp"), payload.get("signal_bar"),
        row.get("checkpoint"), row.get("event_time"),
    ):
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]
    return None


def _state_payload(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    state_rows = [
        row for row in rows
        if row.get("stage") in {"DIRECTIONAL_DECISION", "DIRECTIONAL_LIVE_BOOTSTRAP", "DIRECTIONAL_SESSION_CUTOFF"}
    ]
    latest = state_rows[-1] if state_rows else None
    p = (latest or {}).get("payload") or {}
    owner = p.get("trade_owner_after", p.get("trade_owner", "NONE"))
    return {
        "trade_owner": owner,
        "bullish_state": p.get("bullish_state"),
        "bearish_state": p.get("bearish_state"),
        "bullish_armed": p.get("bullish_armed"),
        "bearish_armed": p.get("bearish_armed"),
        "last_completed_bar": p.get("bar_timestamp", p.get("last_completed_bar")),
    }, latest


def _latest_event_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    accepted = suppressed = None
    for row in reversed(rows):
        if row.get("stage") != "DIRECTIONAL_DECISION":
            continue
        p = row.get("payload") or {}
        if accepted is None and p.get("accepted_events"):
            accepted = row
        if suppressed is None and p.get("suppressed_events"):
            suppressed = row
        if accepted is not None and suppressed is not None:
            break
    return accepted, suppressed


def _latest_process_start() -> dict[str, Any]:
    result = {
        "present": False, "session_date": None, "evidence_path": None,
        "evidence_chain_ok": None, "evidence_chain_issue": None,
        "expiry": None, "expiry_source": None,
    }
    if not EVIDENCE_ROOT.is_dir():
        return result
    for path in sorted(EVIDENCE_ROOT.glob("*.jsonl"), reverse=True):
        try:
            rows = verify_journal(path)
        except Exception as exc:
            return {
                **result, "present": True, "session_date": path.stem,
                "evidence_path": str(path), "evidence_chain_ok": False,
                "evidence_chain_issue": f"{type(exc).__name__}:{exc}",
            }
        starts = [r for r in rows if r.get("kind") == "process_start" and r.get("status") == "OK"]
        if not starts:
            continue
        latest = starts[-1]
        args = latest.get("args") or {}
        response = latest.get("response") or {}
        return {
            "present": True,
            "session_date": args.get("session_date") or path.stem,
            "evidence_path": str(path),
            "evidence_chain_ok": True,
            "evidence_chain_issue": None,
            "expiry": response.get("expiry"),
            "expiry_source": response.get("expiry_source"),
        }
    return result


def _latest_bootstrap(rows: list[dict[str, Any]], session_date: str | None) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if row.get("stage") == "DIRECTIONAL_LIVE_BOOTSTRAP"
        and (session_date is None or _record_session(row) == session_date)
    ]
    return candidates[-1] if candidates else None


def _restore_summary(rows: list[dict[str, Any]], *, session_date: str | None, bootstrap: dict[str, Any] | None) -> dict[str, Any]:
    base = {
        "bootstrap_present": bootstrap is not None,
        "restored_active_count": 0,
        "restored_pending_exit_count": 0,
        "blocked_restore_count": 0,
        "restored_instrument_keys": [],
        "identity_source": None,
        "contract_master_lookup": None,
    }
    if bootstrap is not None:
        restore = ((bootstrap.get("payload") or {}).get("option_restore"))
        if isinstance(restore, dict):
            base.update({
                "restored_active_count": restore.get("restored_active_count", 0),
                "restored_pending_exit_count": restore.get("restored_pending_exit_count", 0),
                "blocked_restore_count": restore.get("blocked_restore_count", 0),
                "restored_instrument_keys": restore.get("restored_instrument_keys", []),
                "contract_master_lookup": False,
            })

    restore_rows = [
        row for row in rows
        if str(row.get("stage") or "").endswith("_OPTION_SHADOW_BOOTSTRAP_RESTORE")
        and (session_date is None or _record_session(row) == session_date)
    ]
    if not restore_rows:
        return base

    active = pending = blocked = 0
    keys: list[str] = []
    identity_sources, contract_flags = set(), set()
    for row in restore_rows:
        status = str(row.get("status") or "")
        payload = row.get("payload") or {}
        if status == "RESTORED_ACTIVE":
            active += 1
        elif status == "RESTORED_PENDING_EXACT_EXIT":
            pending += 1
        elif status.startswith("BLOCKED"):
            blocked += 1
        for key in payload.get("shadow_selected_instrument_keys") or []:
            if key not in keys:
                keys.append(key)
        if payload.get("identity_source") is not None:
            identity_sources.add(payload.get("identity_source"))
        if "contract_master_lookup" in payload:
            contract_flags.add(payload.get("contract_master_lookup"))

    return {
        **base,
        "restored_active_count": active,
        "restored_pending_exit_count": pending,
        "blocked_restore_count": blocked,
        "restored_instrument_keys": keys,
        "identity_source": next(iter(identity_sources)) if len(identity_sources) == 1 else None,
        "contract_master_lookup": next(iter(contract_flags)) if len(contract_flags) == 1 else None,
    }


def _option_operational(rows: list[dict[str, Any]], session_date: str | None) -> dict[str, Any]:
    session_rows = [r for r in rows if session_date is not None and _record_session(r) == session_date]
    dashboard = project_directional_shadow_dashboard(session_rows)
    trades = dashboard.get("trades", [])
    bullish = [t for t in trades if t.get("direction") == "BULLISH"]
    bearish = [t for t in trades if t.get("direction") == "BEARISH"]

    def latest_status(items):
        if not items:
            return None
        return max(items, key=lambda x: str(x.get("signal_bar") or "")).get("status")

    option_minutes = []
    for row in session_rows:
        if "_OPTION_SHADOW_" not in str(row.get("stage") or ""):
            continue
        value = (row.get("payload") or {}).get("latest_completed_minute")
        if isinstance(value, str):
            option_minutes.append(value)

    return {
        "ce_status": latest_status(bullish),
        "pe_status": latest_status(bearish),
        "trade_count": dashboard.get("trade_count", 0),
        "active_count": dashboard.get("active_count", 0),
        "complete_closed_count": dashboard.get("complete_closed_count", 0),
        "pending_exit_count": dashboard.get("pending_exit_count", 0),
        "incomplete_count": dashboard.get("incomplete_count", 0),
        "latest_option_update_minute": max(option_minutes) if option_minutes else None,
    }


def _cutoff_operational(rows: list[dict[str, Any]], session_date: str | None) -> dict[str, Any]:
    cutoff_rows = [
        row for row in rows
        if row.get("stage") == "DIRECTIONAL_SESSION_CUTOFF"
        and session_date is not None and _record_session(row) == session_date
    ]
    latest = cutoff_rows[-1] if cutoff_rows else None
    status = latest.get("status") if latest else None
    return {"present": bool(cutoff_rows), "status": status, "processed": status == "PROCESSED", "record": latest}


def _operational_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    process_start = _latest_process_start()
    worker_session = process_start.get("session_date")
    _, latest_state = _state_payload(rows)
    state_session = _record_session(latest_state) if latest_state else None
    session_date = worker_session or state_session
    bootstrap = _latest_bootstrap(rows, session_date)
    bootstrap_payload = (bootstrap or {}).get("payload") or {}
    session_rows = [r for r in rows if session_date is not None and _record_session(r) == session_date]
    current_session_state, _ = _state_payload(session_rows)

    return {
        "session_date": session_date,
        "worker_session_date": worker_session,
        "directional_state_session_date": state_session,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "directional": {**current_session_state, "bootstrap_present": bootstrap is not None},
        "option_expiry": process_start.get("expiry"),
        "option_expiry_source": process_start.get("expiry_source"),
        "option_lifecycle": _option_operational(rows, session_date),
        "restart_restore": _restore_summary(rows, session_date=session_date, bootstrap=bootstrap),
        "cutoff": _cutoff_operational(rows, session_date),
        "bootstrap": {
            "present": bootstrap is not None,
            "historical_sessions_loaded": bootstrap_payload.get("historical_sessions_loaded"),
            "bars_replayed": bootstrap_payload.get("bars_replayed"),
            "recovered_checkpoint_count": bootstrap_payload.get("recovered_checkpoint_count"),
            "reconstructed": bootstrap_payload.get("reconstructed"),
        },
        "market_evidence": {
            "present": process_start.get("present"),
            "path": process_start.get("evidence_path"),
            "chain_ok": process_start.get("evidence_chain_ok"),
            "chain_issue": process_start.get("evidence_chain_issue"),
        },
    }


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
        "operational": _operational_payload(rows),
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
        if row.get("stage") not in {"DIRECTIONAL_DECISION", "DIRECTIONAL_LIVE_BOOTSTRAP", "DIRECTIONAL_SESSION_CUTOFF"}:
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
