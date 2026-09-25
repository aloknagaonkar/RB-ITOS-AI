from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

router = APIRouter(
    prefix="/api/live-shadow/hilega-directional-candles",
    tags=["hilega-directional-candles"],
)

IST = ZoneInfo("Asia/Kolkata")
HIST_ROOT = Path("data/historical-evidence/hilega-directional-replay-v1")
LIVE_BULLISH_AUDIT = Path("data/live-observation/hilega-milega-v1/step-audit.jsonl")
LIVE_DIRECTIONAL_AUDIT = Path("data/live-observation/hilega-directional-v1/step-audit.jsonl")


def _iso_session(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    head = value[:10]
    try:
        datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return None
    return head


def _hhmm(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST)
        return dt.strftime("%H:%M")
    except ValueError:
        return value[:5] if len(value) >= 5 and value[2:3] == ":" else None


def _read_audit(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    store = ShadowStepAuditStoreV1(path)
    try:
        return store.read_all()
    except Exception:
        return []


def _timestamp(row: dict[str, Any]) -> str | None:
    payload = row.get("payload") or {}
    for value in (
        payload.get("bar_timestamp"),
        payload.get("signal_bar"),
        row.get("checkpoint"),
    ):
        if isinstance(value, str):
            return value
    return None


def _action_from_directional(payload: dict[str, Any]) -> str:
    accepted = [str(x) for x in (payload.get("accepted_events") or [])]
    joined = "|".join(accepted)
    before = str(payload.get("trade_owner_before") or payload.get("owner_before") or "NONE")
    after = str(payload.get("trade_owner_after") or payload.get("owner_after") or "NONE")

    if any(x.startswith("ENTRY_BEARISH") for x in accepted):
        return "BEARISH_ENTRY"
    if any(x.startswith("ENTRY_") and not x.startswith("ENTRY_BEARISH") for x in accepted):
        return "BULLISH_ENTRY"
    if "STRUCTURAL_EXIT_BEARISH" in joined or "BEARISH_SESSION_CUTOFF_EXIT" in joined:
        return "BEARISH_EXIT"
    if "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21" in joined or "SESSION_CUTOFF_EXIT_1455_OPEN" in joined:
        if before == "BULLISH":
            return "BULLISH_EXIT"
    if before != after and after == "NONE":
        return f"{before}_EXIT" if before in {"BULLISH", "BEARISH"} else "EXIT"
    if after == "BULLISH":
        return "BULLISH_ACTIVE"
    if after == "BEARISH":
        return "BEARISH_ACTIVE"
    if payload.get("bullish_armed") or payload.get("bearish_armed"):
        return "ARMED_INFORMATION"
    return "NO_ACTION"


def _base_live_rows(session_date: str) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in _read_audit(LIVE_BULLISH_AUDIT):
        ts = _timestamp(record)
        if not ts or _iso_session(ts) != session_date:
            continue
        payload = record.get("payload") or {}
        stage = str(record.get("stage") or "")
        if stage not in {
            "UNDERLYING_5M_BUILD",
            "INDICATOR_CALCULATION",
            "STRATEGY_DECISION_RESULT",
            "STRATEGY_TRANSITION",
        }:
            continue
        row = merged.setdefault(ts, {
            "session_date": session_date,
            "time": _hhmm(ts),
            "bar_timestamp": ts,
            "open": None, "high": None, "low": None, "close": None, "volume": None,
            "rsi9": None, "ema3_rsi": None, "wma21_rsi": None,
            "owner_before": None, "owner_after": None,
            "bullish_state": None, "bearish_state": None,
            "bullish_armed": None, "bearish_armed": None,
            "action": "NO_DIRECTIONAL_AUDIT",
            "accepted_events": "",
            "suppressed_events": "",
            "note": "Directional state unavailable for this candle",
            "directional_evidence": False,
        })
        for key in ("open", "high", "low", "close", "volume", "rsi9", "ema3_rsi", "wma21_rsi"):
            if payload.get(key) is not None:
                row[key] = payload.get(key)

    return merged


def _latest_live_session() -> str | None:
    sessions: list[str] = []
    for path in (LIVE_BULLISH_AUDIT, LIVE_DIRECTIONAL_AUDIT):
        for record in _read_audit(path):
            ts = _timestamp(record)
            session = _iso_session(ts)
            if session:
                sessions.append(session)
            payload = record.get("payload") or {}
            for key in ("last_completed_bar", "cutoff_timestamp"):
                session = _iso_session(payload.get(key))
                if session:
                    sessions.append(session)
    return max(sessions) if sessions else None


def build_live_directional_candles(session_date: str | None = None) -> dict[str, Any]:
    day = session_date or _latest_live_session()
    if not day:
        return {
            "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
            "mode": "LIVE",
            "session_date": None,
            "row_count": 0,
            "directional_row_count": 0,
            "rows": [],
            "warning": "No current live candle evidence is available.",
        }

    rows = _base_live_rows(day)
    directional_count = 0

    for record in _read_audit(LIVE_DIRECTIONAL_AUDIT):
        if record.get("stage") != "DIRECTIONAL_DECISION":
            continue
        payload = record.get("payload") or {}
        ts = payload.get("bar_timestamp") or record.get("checkpoint")
        if not isinstance(ts, str) or _iso_session(ts) != day:
            continue

        row = rows.setdefault(ts, {
            "session_date": day,
            "time": _hhmm(ts),
            "bar_timestamp": ts,
            "open": None, "high": None, "low": None, "close": None, "volume": None,
            "rsi9": None, "ema3_rsi": None, "wma21_rsi": None,
        })
        row.update({
            "owner_before": payload.get("trade_owner_before"),
            "owner_after": payload.get("trade_owner_after"),
            "bullish_state": payload.get("bullish_state"),
            "bearish_state": payload.get("bearish_state"),
            "bullish_armed": payload.get("bullish_armed"),
            "bearish_armed": payload.get("bearish_armed"),
            "action": _action_from_directional(payload),
            "accepted_events": ",".join(str(x) for x in (payload.get("accepted_events") or [])),
            "suppressed_events": ",".join(str(x) for x in (payload.get("suppressed_events") or [])),
            "note": payload.get("note"),
            "directional_evidence": True,
        })
        directional_count += 1

    ordered = [rows[key] for key in sorted(rows)]
    return {
        "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
        "mode": "LIVE",
        "session_date": day,
        "row_count": len(ordered),
        "directional_row_count": directional_count,
        "rows": ordered,
        "warning": (
            "Candle/indicator evidence is shown for the current live session. "
            "Directional state is overlaid only where the directional audit contains "
            "that exact bar; earlier bars are not retroactively invented."
        ),
    }


def build_historical_directional_candles(session_date: str) -> dict[str, Any]:
    try:
        datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "session_date must be YYYY-MM-DD") from exc

    path = HIST_ROOT / session_date / "directional-candle-by-candle.json"
    if not path.is_file():
        raise HTTPException(404, f"No directional candle replay evidence for {session_date}.")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise HTTPException(422, "Directional candle replay must be a JSON list.")

    return {
        "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
        "mode": "HISTORICAL_REPLAY",
        "session_date": session_date,
        "row_count": len(data),
        "directional_row_count": len(data),
        "rows": data,
        "warning": (
            "Historical rows come directly from the recorded directional "
            "candle-by-candle replay; bullish and bearish states are both preserved."
        ),
    }


@router.get("/historical")
def historical(session_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    return build_historical_directional_candles(session_date)


@router.get("/live")
def live(session_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    return build_live_directional_candles(session_date)
