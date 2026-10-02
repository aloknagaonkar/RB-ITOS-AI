"""Session-centric, read-only Hilega historical/live replay API.

The historical page selects a trading day, not a capture folder.

Source precedence for a selected day:
1. Rich Phase-7D historical capture
2. Completed Hilega live-shadow audit
3. Per-session canonical Hilega replay
4. 120-session research summary fallback

This module never calls broker APIs, never starts/restarts a worker and never
submits orders. Existing append-only evidence is read without mutation.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from .hilega_milega_audit_report_v1 import build_audit_index
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

router = APIRouter(prefix="/api/live-shadow/hilega-historical", tags=["hilega-historical"])

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path("data/historical-evidence")
REPLAY_ROOT = ROOT / "hilega-milega-replay-v1"
RESEARCH_ROOT = ROOT / "hilega-milega-bullish-expansion-multisession-v1"
LIVE_AUDIT = Path("data/live-observation/hilega-milega-v1/step-audit.jsonl")

NAME_RE = re.compile(r"^hilega-phase7d-(\d{4}-\d{2}-\d{2})(?:-[a-zA-Z0-9_-]+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SOURCE_RANK = {
    "PHASE7D": 400,
    "LIVE_SHADOW": 300,
    "SESSION_REPLAY": 200,
    "RESEARCH_120": 100,
}


def _json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise HTTPException(422, f"Invalid historical artifact {path.name}: {type(exc).__name__}") from exc


def _row_day(row: dict) -> str | None:
    for key in ("checkpoint", "event_time"):
        value = str(row.get(key) or "")
        if len(value) >= 10 and DATE_RE.fullmatch(value[:10]):
            return value[:10]
    return None


def _read_audit(path: Path):
    store = ShadowStepAuditStoreV1(path)
    try:
        chain_ok, chain_issue = store.verify_chain()
        rows = store.read_all()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise HTTPException(422, f"Historical audit unreadable: {type(exc).__name__}") from exc
    return chain_ok, chain_issue, rows


def _phase7d_candidates(root: Path = ROOT):
    found = []
    if not root.is_dir():
        return found
    for child in root.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        match = NAME_RE.fullmatch(child.name)
        if not match or not (child / "step-audit.jsonl").is_file():
            continue
        try:
            day = date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            continue
        manifest_path = child / "source-manifest.json"
        manifest = _json_file(manifest_path) if manifest_path.is_file() else {}
        found.append({
            "session_date": day,
            "source": "PHASE7D",
            "source_id": child.name,
            "path": child / "step-audit.jsonl",
            "manifest": manifest,
            "has_report": (child / "detailed-audit-report.json").is_file(),
            "has_manifest": manifest_path.is_file(),
            "ce_available": True,
            "evidence_level": "FULL",
            "status": "COMPLETE",
        })
    return found


def _replay_candidates(root: Path = REPLAY_ROOT):
    found = []
    if not root.is_dir():
        return found
    for child in root.iterdir():
        if not child.is_dir() or child.is_symlink() or not DATE_RE.fullmatch(child.name):
            continue
        audit = child / "step-audit.jsonl"
        if not audit.is_file():
            continue
        found.append({
            "session_date": child.name,
            "source": "SESSION_REPLAY",
            "source_id": f"replay:{child.name}",
            "path": audit,
            "manifest": {},
            "has_report": (child / "detailed-audit-report.json").is_file(),
            "has_manifest": False,
            "ce_available": False,
            "evidence_level": "STRATEGY",
            "status": "COMPLETE",
        })
    return found


def _live_is_complete(rows: list[dict]) -> bool:
    for row in rows:
        payload = row.get("payload") or {}
        if str(payload.get("state_after") or "").upper() == "SESSION_LOCKED":
            return True
        events = payload.get("events_emitted") or []
        if any(str(x).upper() == "SESSION_LOCKED_1455" for x in events):
            return True
        if str(row.get("status") or "").upper() == "SESSION_LOCKED_1455":
            return True
    return False


def _live_candidates(path: Path = LIVE_AUDIT):
    if not path.is_file():
        return []
    chain_ok, chain_issue, rows = _read_audit(path)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        day = _row_day(row)
        if day:
            grouped[day].append(row)

    today = datetime.now(IST).date().isoformat()
    found = []
    for day, day_rows in grouped.items():
        complete = _live_is_complete(day_rows)
        # Today's live session becomes historical automatically only after the
        # strategy/session lock is actually recorded. Older incomplete evidence
        # remains discoverable as PARTIAL rather than being silently lost.
        if day == today and not complete:
            continue
        found.append({
            "session_date": day,
            "source": "LIVE_SHADOW",
            "source_id": f"live:{day}",
            "path": path,
            "manifest": {},
            "has_report": True,
            "has_manifest": False,
            "ce_available": any("OPTION_" in str(r.get("stage") or "") for r in day_rows),
            "evidence_level": "FULL" if complete else "PARTIAL",
            "status": "COMPLETE" if complete else "PARTIAL",
            "live_chain_ok": chain_ok,
            "live_chain_issue": chain_issue,
        })
    return found


def _research_files(root: Path = RESEARCH_ROOT):
    return root / "day-summary.csv", root / "trade-expansion-details.csv"


def _read_csv(path: Path):
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise HTTPException(422, f"Historical CSV unreadable: {path.name}") from exc


def _research_candidates(root: Path = RESEARCH_ROOT):
    day_summary, trades = _research_files(root)
    dates = set()
    for row in _read_csv(day_summary):
        value = str(row.get("session_date") or row.get("date") or "")
        if DATE_RE.fullmatch(value):
            dates.add(value)
    for row in _read_csv(trades):
        value = str(row.get("session_date") or "")
        if DATE_RE.fullmatch(value):
            dates.add(value)
    return [{
        "session_date": day,
        "source": "RESEARCH_120",
        "source_id": f"research120:{day}",
        "path": trades,
        "manifest": {},
        "has_report": False,
        "has_manifest": False,
        "ce_available": False,
        "evidence_level": "SUMMARY",
        "status": "COMPLETE",
    } for day in dates]


def _all_candidates(root: Path = ROOT, replay_root: Path = REPLAY_ROOT,
                    research_root: Path = RESEARCH_ROOT, live_path: Path = LIVE_AUDIT):
    return (
        _phase7d_candidates(root)
        + _live_candidates(live_path)
        + _replay_candidates(replay_root)
        + _research_candidates(research_root)
    )


def _best_for_day(rows: list[dict]):
    def score(x):
        rich = 20 if x.get("has_report") else 0
        manifest = 5 if x.get("has_manifest") else 0
        # For Phase-7D variants, later/richer capture IDs (e.g. d4) sort last.
        return (SOURCE_RANK.get(x["source"], 0) + rich + manifest, x.get("source_id", ""))
    return sorted(rows, key=score, reverse=True)[0]


def list_sessions(root: Path = ROOT, replay_root: Path = REPLAY_ROOT,
                  research_root: Path = RESEARCH_ROOT, live_path: Path = LIVE_AUDIT):
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in _all_candidates(root, replay_root, research_root, live_path):
        grouped[row["session_date"]].append(row)

    sessions = []
    for day, rows in grouped.items():
        best = _best_for_day(rows)
        alternatives = sorted({x["source"] for x in rows})
        sessions.append({
            "session_date": day,
            "source": best["source"],
            "source_id": best["source_id"],
            "status": best["status"],
            "evidence_level": best["evidence_level"],
            "ce_available": bool(best.get("ce_available")),
            "expiry": (best.get("manifest") or {}).get("expiry"),
            "available_sources": alternatives,
        })
    return sorted(sessions, key=lambda x: x["session_date"], reverse=True)


def _load_audit_candidate(candidate: dict):
    chain_ok, chain_issue, rows = _read_audit(candidate["path"])
    day = candidate["session_date"]
    rows = [r for r in rows if _row_day(r) == day]
    reports = build_audit_index(
        rows,
        mode="HISTORICAL_SESSION_REGISTRY_V1",
        chain_ok=chain_ok,
        chain_issue=chain_issue,
    )
    reports.sort(key=lambda x: x["checkpoint"])
    return {
        "session_date": day,
        "source": candidate["source"],
        "source_id": candidate["source_id"],
        "evidence_level": candidate["evidence_level"],
        "ce_available": bool(candidate.get("ce_available")),
        "manifest": candidate.get("manifest") or {},
        "audit_chain_ok": chain_ok,
        "audit_chain_issue": chain_issue,
        "reports": reports,
        "report_count": len(reports),
        "observation_only": True,
        "execution_enabled": False,
        "warning": (
            "Read-only session view. Source evidence is preserved as recorded. "
            "No broker request, replay worker or execution action is started."
        ),
    }


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(day: str, hhmm: str):
    if not hhmm:
        return None
    return f"{day}T{hhmm}:00+05:30"


def _entry_event(source: str):
    value = source.upper()
    if "ROUTE_A" in value:
        return "ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21", "ROUTE_A"
    if "ROUTE_B" in value:
        return "ENTRY_PATH1_ROUTE_B_STRUCTURAL", "ROUTE_B"
    return "ENTRY_OPENING_BULLISH_CONFIRMED", "OPENING_PATH"


def _summary_report(checkpoint: str, *, close, state_before, state_after,
                    selected_route, event_type, price, points=None,
                    original_entry_time=None):
    event = {
        "event_time": checkpoint,
        "event_type": event_type,
        "price": price,
        "entry_price": price if event_type.startswith("ENTRY_") else None,
        "entry_time": checkpoint if event_type.startswith("ENTRY_") else None,
        "exit_reason": "RSI_CROSS_BELOW_WMA21" if "STRUCTURAL_EXIT" in event_type else None,
        "points": points,
        "source": selected_route,
        "state_before": state_before,
        "state_after": state_after,
        "details": {"original_entry_time": original_entry_time} if original_entry_time else None,
    }
    return {
        "checkpoint": checkpoint,
        "bar": {"open": None, "high": None, "low": None, "close": close, "volume": None},
        "indicators": {},
        "conditions": {},
        "strategy": {
            "state_before": state_before,
            "state_after": state_after,
            "selected_route": selected_route if event_type.startswith("ENTRY_") else None,
            "events_emitted": [event_type],
        },
        "route_a": {},
        "route_b": {},
        "transitions": [event],
        "option_candidate": None,
        "option_market_snapshot": None,
        "option_lifecycle": {},
        "audit_integrity": {
            "source": "RESEARCH_120_SUMMARY",
            "canonical_step_audit_available": False,
        },
        "safety": {"observation_only": True, "execution_enabled": False},
    }


def _load_research_summary(candidate: dict, research_root: Path = RESEARCH_ROOT):
    _, trades_path = _research_files(research_root)
    day = candidate["session_date"]
    reports = []
    for row in _read_csv(trades_path):
        if str(row.get("session_date") or "") != day:
            continue
        entry_time = str(row.get("entry_time") or "")
        exit_time = str(row.get("exit_time") or "")
        entry_cp = _iso(day, entry_time)
        exit_cp = _iso(day, exit_time)
        if not entry_cp:
            continue
        event_type, route = _entry_event(str(row.get("source") or ""))
        entry_close = _float(row.get("entry_close"))
        exit_close = _float(row.get("exit_close"))
        points = _float(row.get("points"))
        reports.append(_summary_report(
            entry_cp, close=entry_close, state_before="PATH1_IDLE",
            state_after="BULLISH_ACTIVE", selected_route=route,
            event_type=event_type, price=entry_close,
        ))
        if exit_cp:
            reports.append(_summary_report(
                exit_cp, close=exit_close, state_before="BULLISH_ACTIVE",
                state_after="PATH1_IDLE", selected_route=route,
                event_type="STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
                price=exit_close, points=points, original_entry_time=entry_cp,
            ))
    reports.sort(key=lambda x: x["checkpoint"])
    return {
        "session_date": day,
        "source": "RESEARCH_120",
        "source_id": candidate["source_id"],
        "evidence_level": "SUMMARY",
        "ce_available": False,
        "manifest": {},
        "audit_chain_ok": None,
        "audit_chain_issue": "Canonical per-candle step audit was not recorded for this research-only session.",
        "reports": reports,
        "report_count": len(reports),
        "observation_only": True,
        "execution_enabled": False,
        "warning": (
            "120-session research fallback: entry/exit summary only. "
            "Full five-minute conditions and exact ATM±2 CE lifecycle are unavailable "
            "unless a richer replay/capture exists for this day."
        ),
    }


def load_session(session_date: str, root: Path = ROOT, replay_root: Path = REPLAY_ROOT,
                 research_root: Path = RESEARCH_ROOT, live_path: Path = LIVE_AUDIT):
    try:
        day = date.fromisoformat(session_date).isoformat()
    except ValueError as exc:
        raise HTTPException(422, "Invalid session date") from exc

    candidates = [
        x for x in _all_candidates(root, replay_root, research_root, live_path)
        if x["session_date"] == day
    ]
    if not candidates:
        raise HTTPException(404, "Hilega session not found")
    best = _best_for_day(candidates)
    if best["source"] == "RESEARCH_120":
        result = _load_research_summary(best, research_root)
    else:
        result = _load_audit_candidate(best)
    result["available_sources"] = sorted({x["source"] for x in candidates})
    return result


# Backward-compatible capture discovery remains available for old bookmarks/tests.
def _candidate_dirs(root: Path = ROOT):
    return [(x["session_date"], x["path"].parent) for x in _phase7d_candidates(root)]


def list_available(root: Path = ROOT):
    sessions = []
    for row in _phase7d_candidates(root):
        sessions.append({
            "session_date": row["session_date"],
            "capture_id": row["source_id"],
            "has_report": row["has_report"],
            "has_manifest": row["has_manifest"],
            "expiry": (row.get("manifest") or {}).get("expiry"),
            "audit_path_present": True,
        })
    return sorted(sessions, key=lambda x: (x["session_date"], x["capture_id"]), reverse=True)


def load_capture(capture_id: str, root: Path = ROOT):
    valid = {x["source_id"]: x for x in _phase7d_candidates(root)}
    if capture_id not in valid:
        raise HTTPException(404, "Historical Hilega capture not found")
    result = _load_audit_candidate(valid[capture_id])
    result["capture_id"] = capture_id
    return result


@router.get("/sessions")
def sessions():
    return {
        "model": "HILEGA_SESSION_REGISTRY_V1",
        "sessions": list_sessions(),
    }


@router.get("/session")
def session(session_date: str = Query(..., min_length=10, max_length=10)):
    return load_session(session_date)


@router.get("/capture")
def capture(capture_id: str = Query(..., max_length=120)):
    return load_capture(capture_id)
