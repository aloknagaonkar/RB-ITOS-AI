from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HISTORICAL_REPLAY_UI_API_V1"
REPLAY_ROOT = Path("data/live-observation/replay")
SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

router = APIRouter(prefix="/api/live-shadow/replay", tags=["live-shadow-replay"])


def _session_dir(session_date: str, replay_root: Path = REPLAY_ROOT) -> Path:
    try:
        parsed = date.fromisoformat(session_date)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid session date: {session_date}") from exc

    canonical = parsed.isoformat()
    if canonical != session_date:
        raise HTTPException(400, f"Session date must be YYYY-MM-DD: {session_date}")

    root = replay_root.resolve()
    target = (replay_root / canonical).resolve()
    if root != target.parent:
        raise HTTPException(400, "Invalid replay path")
    return target


def _read_json(path: Path, *, missing_ok: bool = False) -> Any:
    if not path.exists():
        if missing_ok:
            return None
        raise HTTPException(404, f"Replay file not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Invalid replay JSON: {path.name}") from exc


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                500, f"Invalid JSONL in {path.name} line {line_no}"
            ) from exc
        if isinstance(value, dict):
            rows.append(value)
    if limit is not None and limit >= 0:
        rows = rows[-limit:]
    return rows


def list_sessions(replay_root: Path = REPLAY_ROOT) -> list[dict[str, Any]]:
    if not replay_root.exists():
        return []

    sessions = []
    for child in replay_root.iterdir():
        if not child.is_dir() or not SESSION_RE.match(child.name):
            continue
        try:
            date.fromisoformat(child.name)
        except ValueError:
            continue

        status = _read_json(child / "replay-status.json", missing_ok=True) or {}
        sessions.append({
            "session_date": child.name,
            "status": status.get("status", "UNKNOWN"),
            "model": status.get("model"),
            "checkpoint_count": status.get("checkpoint_count"),
            "processed_checkpoint_count": status.get("processed_checkpoint_count"),
            "missing_checkpoint_count": status.get("missing_checkpoint_count"),
            "observation_count": status.get("observation_count"),
            "state_counts": status.get("state_counts") or {},
            "step_audit_chain_ok": status.get("step_audit_chain_ok"),
        })

    return sorted(sessions, key=lambda row: row["session_date"], reverse=True)


def _event_index(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        oid = event.get("observation_id")
        if oid:
            index[str(oid)].append(event)
    return index


def build_timeline(session_dir: Path) -> list[dict[str, Any]]:
    audit = _read_jsonl(session_dir / "step-audit.jsonl")
    events = _read_jsonl(session_dir / "events.jsonl")
    event_index = _event_index(events)

    checkpoints: dict[str, dict[str, Any]] = {}
    observation_checkpoint: dict[str, str] = {}

    for row in audit:
        checkpoint = row.get("checkpoint")
        stage = row.get("stage")
        if not checkpoint or not stage:
            continue

        entry = checkpoints.setdefault(checkpoint, {
            "checkpoint": checkpoint,
            "snapshot_selection": None,
            "normalized_features": None,
            "data_health": None,
            "all3_decision": None,
            "candidate_detection": None,
            "candidate_steps": [],
            "observation_ids": [],
        })

        normalized_stage = str(stage).lower()
        if stage == "SNAPSHOT_SELECTION":
            entry["snapshot_selection"] = row
        elif stage == "NORMALIZED_FEATURES":
            entry["normalized_features"] = row
        elif stage == "DATA_HEALTH":
            entry["data_health"] = row
        elif stage == "ALL3_DECISION":
            entry["all3_decision"] = row
        elif stage == "CANDIDATE_DETECTION":
            entry["candidate_detection"] = row
        else:
            entry["candidate_steps"].append(row)

        oid = row.get("observation_id")
        if oid:
            oid = str(oid)
            if oid not in entry["observation_ids"]:
                entry["observation_ids"].append(oid)
            observation_checkpoint.setdefault(oid, checkpoint)

    # Some lifecycle audit rows have checkpoint=None. Attach them to the
    # candidate checkpoint using observation_id.
    for row in audit:
        if row.get("checkpoint") is not None:
            continue
        oid = row.get("observation_id")
        if not oid:
            continue
        checkpoint = observation_checkpoint.get(str(oid))
        if checkpoint and checkpoint in checkpoints:
            checkpoints[checkpoint]["candidate_steps"].append(row)
            if str(oid) not in checkpoints[checkpoint]["observation_ids"]:
                checkpoints[checkpoint]["observation_ids"].append(str(oid))

    result = []
    for checkpoint in sorted(checkpoints):
        entry = checkpoints[checkpoint]
        features = (entry.get("normalized_features") or {}).get("payload") or {}
        all3 = entry.get("all3_decision") or {}
        detection = entry.get("candidate_detection") or {}

        entry["summary"] = {
            "spot": features.get("spot"),
            "moving_atm": features.get("moving_atm"),
            "state_5m": features.get("state_5m"),
            "state_10m": features.get("state_10m"),
            "state_15m": features.get("state_15m"),
            "all3_state": all3.get("status") or features.get("all3_state"),
            "candidate": detection.get("status"),
            "health": (entry.get("data_health") or {}).get("status"),
        }

        entry["observation_events"] = {
            oid: event_index.get(oid, [])
            for oid in entry["observation_ids"]
        }
        result.append(entry)

    return result


@router.get("/sessions")
def replay_sessions():
    return {
        "model": MODEL,
        "sessions": list_sessions(),
    }


@router.get("/status")
def replay_status(session_date: str = Query(..., alias="date")):
    directory = _session_dir(session_date)
    payload = _read_json(directory / "replay-status.json")
    return {
        "model": MODEL,
        "session_date": session_date,
        "status": payload,
    }


@router.get("/checkpoints")
def replay_checkpoints(session_date: str = Query(..., alias="date")):
    directory = _session_dir(session_date)
    rows = _read_json(directory / "checkpoints.json")
    return {
        "model": MODEL,
        "session_date": session_date,
        "rows": rows if isinstance(rows, list) else [],
    }


@router.get("/events")
def replay_events(
    session_date: str = Query(..., alias="date"),
    limit: int = Query(1000, ge=1, le=10000),
):
    directory = _session_dir(session_date)
    return {
        "model": MODEL,
        "session_date": session_date,
        "rows": _read_jsonl(directory / "events.jsonl", limit=limit),
    }


@router.get("/health")
def replay_health(
    session_date: str = Query(..., alias="date"),
    limit: int = Query(1000, ge=1, le=10000),
):
    directory = _session_dir(session_date)
    return {
        "model": MODEL,
        "session_date": session_date,
        "rows": _read_jsonl(directory / "health.jsonl", limit=limit),
    }


@router.get("/step-audit")
def replay_step_audit(
    session_date: str = Query(..., alias="date"),
    limit: int = Query(5000, ge=1, le=20000),
):
    directory = _session_dir(session_date)
    store = ShadowStepAuditStoreV1(directory / "step-audit.jsonl")
    chain_ok, chain_issue = store.verify_chain()
    rows = store.read_all()
    if limit:
        rows = rows[-limit:]
    return {
        "model": MODEL,
        "session_date": session_date,
        "chain_ok": chain_ok,
        "chain_issue": chain_issue,
        "rows": rows,
    }


@router.get("/timeline")
def replay_timeline(session_date: str = Query(..., alias="date")):
    directory = _session_dir(session_date)
    if not directory.exists():
        raise HTTPException(404, f"Replay session not found: {session_date}")
    return {
        "model": MODEL,
        "session_date": session_date,
        "rows": build_timeline(directory),
    }
