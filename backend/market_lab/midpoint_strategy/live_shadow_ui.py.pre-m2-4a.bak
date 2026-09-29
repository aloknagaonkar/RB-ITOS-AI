from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from .config import MidpointShadowConfig
from .replay import load_audit_jsonl
from .workspace_contract import midpoint_workspace_status

MODEL = "MIDPOINT_STRATEGY_LIVE_SHADOW_UI_V2"
DATA_DIR = Path("data/live-observation/midpoint-strategy-v1")
AUDIT_PATH = DATA_DIR / "audit.jsonl"
HIST_ROOT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1")
HIST_MANIFEST = HIST_ROOT / "manifest.json"

router = APIRouter(prefix="/api/live-shadow/midpoint-strategy", tags=["live-shadow-midpoint-strategy"])


def _all_rows(path: Path | None = None) -> list[dict[str, Any]]:
    resolved = AUDIT_PATH if path is None else path
    return load_audit_jsonl(resolved) if resolved.exists() else []


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, f"Midpoint replay data unreadable: {path.name}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _row_day(row: dict[str, Any]) -> str | None:
    for key in ("session_date", "event_timestamp", "source_candle_timestamp"):
        value = str(row.get(key) or "")
        if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
            return value[:10]
    return None


def _recent_session_days(rows: list[dict[str, Any]], keep: int = 2) -> list[str]:
    return sorted({d for r in rows if (d := _row_day(r))}, reverse=True)[:keep]


def _recent_rows(rows: list[dict[str, Any]], keep: int = 2) -> list[dict[str, Any]]:
    days = set(_recent_session_days(rows, keep))
    return rows if not days else [r for r in rows if _row_day(r) in days]


def _rows() -> list[dict[str, Any]]:
    return _recent_rows(_all_rows(), keep=2)


def _latest(rows, event_type):
    for row in reversed(rows):
        if row.get("event_type") == event_type:
            return row
    return None


def _latest_any(rows, types):
    wanted = set(types)
    for row in reversed(rows):
        if row.get("event_type") in wanted:
            return row
    return None


def _latest_family_state(rows):
    for row in reversed(rows):
        if row.get("state_after"):
            return str(row["state_after"])
    return "IDLE"


def _display_owner(row: dict[str, Any]) -> str | None:
    if (
        str(row.get("event_type") or "").upper() == "BOUNDARY_OWNER_OTHER"
        and str(row.get("reason") or "").upper() == "FRESH_CANDIDATE_A_AT_BOUNDARY"
    ):
        return "FRESH A"
    family = row.get("family")
    if str(family or "").upper() == "OTHER_FRESH_A":
        return "FRESH A"
    return str(family) if family is not None else None


def _timeline_projection(rows):
    return [
        {
            "event_id": r.get("event_id"),
            "session_date": _row_day(r),
            "timestamp": r.get("event_timestamp"),
            "event_type": r.get("event_type"),
            "family": r.get("family"),
            "display_owner": _display_owner(r),
            "direction": r.get("direction"),
            "state_before": r.get("state_before"),
            "state_after": r.get("state_after"),
            "result": r.get("result"),
            "reason": r.get("reason"),
            "underlying_price": r.get("underlying_price"),
            "directional_points": r.get("directional_points"),
            "reference_type": r.get("reference_type"),
        }
        for r in rows
    ]


def _status_payload(rows, mode, *, audit_path: Path | None = None):
    cfg = MidpointShadowConfig()
    cfg.assert_safe()
    resolved_path = AUDIT_PATH if audit_path is None else audit_path
    return {
        "model": MODEL,
        "mode": mode,
        "workspace": midpoint_workspace_status(cfg),
        "audit_path": str(resolved_path),
        "audit_exists": resolved_path.exists(),
        "audit_record_count": len(rows),
        "session_dates": (
            _recent_session_days(rows, 2)
            if mode == "LIVE"
            else sorted({d for r in rows if (d := _row_day(r))}, reverse=True)
        ),
        "event_counts": dict(Counter(str(r.get("event_type")) for r in rows)),
        "family_b_state": _latest_family_state(rows),
        "latest_event": rows[-1] if rows else None,
        "latest_entry": _latest_any(rows, ("B_ENTRY", "E_ENTRY")),
        "latest_plus20": _latest(rows, "PLUS20_PROOF"),
        "latest_classifier": _latest(rows, "RUNNER_CLASSIFICATION"),
        "latest_degraded": _latest(rows, "DEGRADED_STARTED"),
        "latest_recovery": _latest(rows, "DEGRADED_TARGET_RECOVERED"),
        "latest_rescue": _latest_any(rows, ("CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT")),
        "latest_reentry": _latest_any(
            rows,
            ("POST_CAP20_REENTRY_TRIGGERED", "POST_RESCUE_REENTRY_TRIGGERED", "REENTRY_COUNT_1"),
        ),
        "latest_terminal": _latest(rows, "STRUCTURAL_TERMINAL"),
        "safety": {
            "observation_only": cfg.observation_only,
            "execution_enabled": cfg.execution_enabled,
            "paper_order_enabled": cfg.paper_order_enabled,
            "quantity": cfg.quantity,
        },
    }


@router.get("/status")
def status():
    return _status_payload(_rows(), "LIVE")


@router.get("/events")
def events(limit: Annotated[int, Query(ge=1, le=2000)] = 200, event_type: str | None = None):
    rows = _rows()
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    return {"model": MODEL, "count": min(len(rows), limit), "events": rows[-limit:]}


@router.get("/timeline")
def timeline(limit: Annotated[int, Query(ge=1, le=5000)] = 200):
    rows = _rows()[-limit:]
    return {"model": MODEL, "count": len(rows), "timeline": _timeline_projection(rows)}


@router.get("/audit-detail")
def audit_detail(event_id: str):
    for row in _all_rows():
        if row.get("event_id") == event_id:
            return {"model": MODEL, "event": row, "display_owner": _display_owner(row)}
    raise HTTPException(404, "Midpoint audit event not found")


def _manifest():
    if not HIST_MANIFEST.exists():
        return {"model": "MIDPOINT_UI_REPLAY_MANIFEST_V1", "sessions": []}
    try:
        return json.loads(HIST_MANIFEST.read_text())
    except Exception as exc:
        raise HTTPException(422, f"Midpoint historical manifest unreadable: {type(exc).__name__}") from exc


def _historical_session_dir(session_date: str) -> Path:
    allowed = {str(x.get("session_date")) for x in _manifest().get("sessions", [])}
    if session_date not in allowed:
        raise HTTPException(404, "Midpoint historical session not found")
    return HIST_ROOT / session_date


def _historical_audit_path(session_date: str) -> Path:
    p = _historical_session_dir(session_date) / "audit.jsonl"
    if not p.exists():
        raise HTTPException(404, "Midpoint historical audit not materialized")
    return p


def _historical_minutes_path(session_date: str) -> Path:
    return _historical_session_dir(session_date) / "minutes.jsonl"


def _minute_token(value: Any) -> str:
    text = str(value or "").strip().replace(" ", "T", 1)
    return text[:16] if len(text) >= 16 else text


def _merge_minutes_with_events(minutes: list[dict[str, Any]], timeline_rows: list[dict[str, Any]]):
    by_minute: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in timeline_rows:
        by_minute[_minute_token(event.get("timestamp"))].append(event)

    merged = []
    for row in minutes:
        item = dict(row)
        item["events"] = by_minute.get(_minute_token(row.get("timestamp")), [])
        merged.append(item)
    return merged


@router.get("/historical/sessions")
def historical_sessions():
    m = _manifest()
    s = m.get("sessions", [])
    return {"model": m.get("model"), "count": len(s), "sessions": s}


@router.get("/historical/session")
def historical_session(session_date: str):
    audit_path = _historical_audit_path(session_date)
    rows = _all_rows(audit_path)
    projected = _timeline_projection(rows)
    minutes_path = _historical_minutes_path(session_date)
    minutes = _load_jsonl(minutes_path)
    merged_minutes = _merge_minutes_with_events(minutes, projected)
    return {
        "model": MODEL,
        "mode": "HISTORICAL_REPLAY",
        "session_date": session_date,
        "status": _status_payload(rows, "HISTORICAL_REPLAY", audit_path=audit_path),
        "count": len(rows),
        "timeline": projected,
        "minute_count": len(merged_minutes),
        "minutes": merged_minutes,
    }


@router.get("/historical/audit-detail")
def historical_audit_detail(session_date: str, event_id: str):
    for row in _all_rows(_historical_audit_path(session_date)):
        if row.get("event_id") == event_id:
            return {
                "model": MODEL,
                "mode": "HISTORICAL_REPLAY",
                "event": row,
                "display_owner": _display_owner(row),
            }
    raise HTTPException(404, "Midpoint historical audit event not found")
