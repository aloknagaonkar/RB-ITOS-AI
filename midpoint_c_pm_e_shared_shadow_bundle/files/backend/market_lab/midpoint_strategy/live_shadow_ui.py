from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from .config import live_shadow_config_from_env
from .replay import load_audit_jsonl
from .workspace_contract import midpoint_workspace_status
from .option_observation import project_tape

MODEL = "MIDPOINT_STRATEGY_LIVE_SHADOW_UI_V2"
DATA_DIR = Path("data/live-observation/midpoint-strategy-v1")
AUDIT_PATH = DATA_DIR / "audit.jsonl"
HIST_ROOT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1")
HIST_MANIFEST = HIST_ROOT / "manifest.json"
OPTION_TAPE_ROOT = DATA_DIR / "option-observation"

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
        event_type = str(row.get("event_type") or "")
        if (
            event_type.startswith("NORMAL_B_PROVED_")
            or event_type == "DEGRADED_EXIT_CANDIDATE_TRIGGERED"
        ):
            continue
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


def _with_nifty_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Presentation-only, close-based points for each event of an active B/E leg."""
    active: dict[str, Any] | None = None
    day: str | None = None
    projected = []
    for original in rows:
        row = dict(original)
        event_day = _row_day(row)
        if event_day != day:
            active = None
            day = event_day
        kind = row.get("event_type")
        if kind in ("B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_E_ENTRY"):
            entry_price = _num(row.get("underlying_price"))
            active = {"entry": entry_price, "direction": row.get("direction"),
                      "family": row.get("family")} if entry_price is not None else None
        price = _num(row.get("underlying_price"))
        move = None
        if active and price is not None and row.get("direction") == active["direction"] and row.get("family") == active["family"]:
            sign = 1 if active["direction"] == "BULLISH" else -1
            move = round(sign * (price - active["entry"]), 4)
        row["nifty_points_from_entry"] = move
        row["nifty_entry_price"] = active["entry"] if move is not None else None
        projected.append(row)
        if kind in ("CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT", "STRUCTURAL_TERMINAL"):
            active = None
    return projected


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
            "nifty_points_from_entry": r.get("nifty_points_from_entry"),
            "nifty_entry_price": r.get("nifty_entry_price"),
            "reference_type": r.get("reference_type"),
        }
        for r in rows
    ]


def _status_payload(rows, mode, *, audit_path: Path | None = None):
    rows = _with_nifty_points(rows)
    cfg = live_shadow_config_from_env()
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
        "latest_entry": _latest_any(
            rows, ("B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_E_ENTRY")
        ),
        "latest_plus20": _latest(rows, "PLUS20_PROOF"),
        "latest_classifier": _latest(rows, "RUNNER_CLASSIFICATION"),
        "latest_management_route": _latest(rows, "MANAGEMENT_ROUTE_SELECTED"),
        "latest_normal_b_proved": _latest(rows, "NORMAL_B_PROVED_STARTED"),
        "latest_normal_b_tier2": _latest(rows, "NORMAL_B_PROVED_TIER2"),
        "latest_normal_b_tier3": _latest(rows, "NORMAL_B_PROVED_TIER3"),
        "latest_normal_b_exit": _latest(rows, "NORMAL_B_PROVED_EXIT_CANDIDATE"),
        "latest_normal_b_unavailable": _latest(rows, "NORMAL_B_PROVED_UNAVAILABLE"),
        "latest_degraded": _latest(rows, "DEGRADED_STARTED"),
        "latest_degraded_exit_candidate": _latest(
            rows, "DEGRADED_EXIT_CANDIDATE_TRIGGERED"
        ),
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


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _raw_vwap_diff(row: dict[str, Any]) -> float | None:
    futures = _num(row.get("futures_price"))
    vwap = _num(row.get("futures_vwap"))
    if futures is None or vwap is None:
        return None
    return futures - vwap


def _option_intent(row: dict[str, Any]) -> str | None:
    direction = str(row.get("direction") or "").upper()
    if direction == "BULLISH":
        return "BUY CE"
    if direction == "BEARISH":
        return "BUY PE"
    return None


def _check(
    name: str,
    *,
    passed: bool | None,
    observed: str,
    required: str,
    why: str = "",
    gap: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "result": (
            "PASS"
            if passed is True
            else "FAIL"
            if passed is False
            else "INFO"
        ),
        "observed": observed,
        "required": required,
        "why": why,
        "gap": gap,
    }


def _audit_ui_detail(row: dict[str, Any]) -> dict[str, Any]:
    direction = str(row.get("direction") or "").upper()
    event_type = str(row.get("event_type") or "")
    reason = str(row.get("reason") or "")
    evidence = row.get("evidence") or {}

    price = _num(row.get("underlying_price"))
    midpoint = _num(row.get("midpoint"))
    boundary = _num(row.get("original_boundary"))
    high = _num(row.get("reference_high"))
    low = _num(row.get("reference_low"))

    futures = _num(row.get("futures_price"))
    vwap = _num(row.get("futures_vwap"))
    raw_diff = _raw_vwap_diff(row)
    directional_vwap = _num(row.get("directional_vwap_value"))

    structure_checks: list[dict[str, Any]] = []
    strategy_checks: list[dict[str, Any]] = []
    management_checks: list[dict[str, Any]] = []

    if price is not None and midpoint is not None and direction in ("BEARISH", "BULLISH"):
        if direction == "BEARISH":
            midpoint_pass = price <= midpoint
            required = f"close <= {midpoint:.2f}"
            gap_value = max(0.0, price - midpoint)
            gap = f"{gap_value:.2f} points lower required" if not midpoint_pass else ""
        else:
            midpoint_pass = price >= midpoint
            required = f"close >= {midpoint:.2f}"
            gap_value = max(0.0, midpoint - price)
            gap = f"{gap_value:.2f} points higher required" if not midpoint_pass else ""

        structure_checks.append(
            _check(
                "Midpoint structural close",
                passed=midpoint_pass,
                observed=f"close {price:.2f}",
                required=required,
                gap=gap,
            )
        )

    if price is not None and boundary is not None and direction in ("BEARISH", "BULLISH"):
        if direction == "BEARISH":
            boundary_pass = price < boundary
            required = f"close < {boundary:.2f}"
            gap_value = max(0.0, price - boundary)
            gap = f"{gap_value:.2f} points lower required" if not boundary_pass else ""
        else:
            boundary_pass = price > boundary
            required = f"close > {boundary:.2f}"
            gap_value = max(0.0, boundary - price)
            gap = f"{gap_value:.2f} points higher required" if not boundary_pass else ""

        structure_checks.append(
            _check(
                "Original boundary close",
                passed=boundary_pass,
                observed=f"close {price:.2f}",
                required=required,
                gap=gap,
            )
        )

    if raw_diff is not None and direction in ("BEARISH", "BULLISH"):
        if direction == "BEARISH":
            mature_pass = raw_diff < -5.0
            gap_value = max(0.0, raw_diff + 5.0)
            required = "raw futures - VWAP < -5.00"
            gap = (
                f"{gap_value:.2f} additional bearish VWAP points required"
                if not mature_pass else ""
            )
        else:
            mature_pass = raw_diff > 5.0
            gap_value = max(0.0, 5.0 - raw_diff)
            required = "raw futures - VWAP > +5.00"
            gap = (
                f"{gap_value:.2f} additional bullish VWAP points required"
                if not mature_pass else ""
            )

        strategy_checks.append(
            _check(
                "Mature directional VWAP",
                passed=mature_pass,
                observed=f"{raw_diff:+.2f}",
                required=required,
                gap=gap,
            )
        )

    candidate_a = evidence.get("candidate_a_at_boundary")
    if candidate_a is not None:
        strategy_checks.append(
            _check(
                "Fresh Candidate A at boundary",
                passed=bool(candidate_a),
                observed="TRUE" if candidate_a else "FALSE",
                required=(
                    "fresh directional VWAP transition: "
                    "BEAR prior >= -5 then current < -5; "
                    "BULL prior <= +5 then current > +5"
                ),
                why=(
                    "Fresh Candidate A owns the boundary."
                    if candidate_a
                    else "No fresh Candidate A at this boundary."
                ),
            )
        )

    if "still_beyond_original_boundary" in evidence:
        value = bool(evidence.get("still_beyond_original_boundary"))
        strategy_checks.append(
            _check(
                "Still beyond original boundary",
                passed=value,
                observed="YES" if value else "NO",
                required="must remain beyond original boundary during B watch",
                why="" if value else "B delayed confirmation cannot qualify after boundary is lost.",
            )
        )

    if "minutes_since_boundary_break" in evidence:
        minutes = _num(evidence.get("minutes_since_boundary_break"))
        if minutes is not None:
            strategy_checks.append(
                _check(
                    "B confirmation window",
                    passed=minutes <= 10.0,
                    observed=f"{minutes:.0f} min elapsed",
                    required="<= 10 minutes from original boundary break",
                    gap="" if minutes <= 10.0 else f"{minutes - 10.0:.0f} min beyond allowed window",
                )
            )

    if "condition_progress_positive" in evidence:
        value = bool(evidence.get("condition_progress_positive"))
        management_checks.append(
            _check(
                "Net directional progress",
                passed=value,
                observed="POSITIVE" if value else "NOT POSITIVE",
                required="> 0 at exact +10m classifier",
            )
        )

    if "condition_vwap_change_positive" in evidence:
        value = bool(evidence.get("condition_vwap_change_positive"))
        management_checks.append(
            _check(
                "Directional futures-VWAP change",
                passed=value,
                observed="POSITIVE" if value else "NOT POSITIVE",
                required="> 0 at exact +10m classifier",
            )
        )

    if "condition_prior_minute_vwap_change_negative" in evidence:
        value = bool(evidence.get("condition_prior_minute_vwap_change_negative"))
        management_checks.append(
            _check(
                "VWAP deterioration",
                passed=value,
                observed="NEGATIVE" if value else "NOT NEGATIVE",
                required="< 0 for DEGRADED",
            )
        )

    if "condition_rebreak" in evidence:
        management_checks.append(
            _check(
                "CAP20 target rebreak",
                passed=bool(evidence.get("condition_rebreak")),
                observed="YES" if evidence.get("condition_rebreak") else "NO",
                required="first strict close back through degraded target",
            )
        )

    if "condition_age_ge_10" in evidence:
        management_checks.append(
            _check(
                "CAP20 recovery age",
                passed=bool(evidence.get("condition_age_ge_10")),
                observed=str(evidence.get("minutes_since_recovery", "—")),
                required=">= 10 minutes since degraded-target recovery",
            )
        )

    if "condition_points_le_20" in evidence:
        management_checks.append(
            _check(
                "CAP20 rescue point cap",
                passed=bool(evidence.get("condition_points_le_20")),
                observed=str(row.get("directional_points") or "—"),
                required="directional move <= +20 at first eligible rebreak",
            )
        )

    if event_type == "BOUNDARY_OWNER_OTHER" and reason == "FRESH_CANDIDATE_A_AT_BOUNDARY":
        strategy_checks.append(
            _check(
                "Boundary ownership",
                passed=True,
                observed="FRESH A",
                required="Fresh Candidate A owns boundary; B/E not assigned",
            )
        )

    if event_type == "E_ENTRY":
        strategy_checks.append(
            _check(
                "Family E entry",
                passed=True,
                observed="E ENTRY",
                required="Candidate A false + mature directional VWAP",
            )
        )

    if event_type == "B_ENTRY":
        strategy_checks.append(
            _check(
                "Family B delayed entry",
                passed=True,
                observed="B ENTRY",
                required="full Candidate A appears within B watch while structure remains valid",
            )
        )

    if event_type == "B_WATCH_STARTED":
        strategy_checks.append(
            _check(
                "Family B watch",
                passed=True,
                observed="WATCH STARTED",
                required="Candidate A false + E not mature at boundary",
            )
        )

    if event_type == "PLUS20_PROOF":
        management_checks.append(
            _check(
                "+20 proof",
                passed=True,
                observed=f"{row.get('directional_points', '—')} directional points",
                required="first favorable intrabar excursion >= +20",
            )
        )

    if event_type == "RUNNER_CLASSIFICATION":
        management_checks.append(
            _check(
                "Runner classifier",
                passed=True,
                observed=str(row.get("result") or row.get("reason") or "—"),
                required="exact +10m classifier after +20 proof",
            )
        )

    if event_type == "DEGRADED_STARTED":
        management_checks.append(
            _check(
                "Degraded state",
                passed=True,
                observed="DEGRADED",
                required="drawdown from running MFE + VWAP deterioration",
            )
        )

    if event_type == "CAP20_RESCUE_TRIGGERED":
        management_checks.append(
            _check(
                "CAP20 rescue",
                passed=True,
                observed="SHADOW EXIT",
                required="eligible first rebreak with directional move <= +20",
            )
        )

    if event_type == "STRUCTURAL_TERMINAL":
        management_checks.append(
            _check(
                "Structural terminal",
                passed=True,
                observed=str(reason or "MIDPOINT INVALIDATION"),
                required="first adverse midpoint close",
            )
        )

    if raw_diff is None:
        vwap_position = "NOT AVAILABLE"
    elif raw_diff > 0:
        vwap_position = "ABOVE VWAP"
    elif raw_diff < 0:
        vwap_position = "BELOW VWAP"
    else:
        vwap_position = "AT VWAP"

    return {
        "market": {
            "nifty": price,
            "reference_type": row.get("reference_type"),
            "reference_high": high,
            "reference_low": low,
            "midpoint": midpoint,
            "boundary": boundary,
            "directional_points": _num(row.get("directional_points")),
        },
        "vwap": {
            "futures_close": futures,
            "futures_vwap": vwap,
            "raw_diff": raw_diff,
            "directional_value": directional_vwap,
            "position": vwap_position,
        },
        "strategy": {
            "owner": _display_owner(row),
            "direction": row.get("direction"),
            "event_type": event_type,
            "result": row.get("result"),
            "reason": reason,
        },
        "option": {
            "intent": _option_intent(row),
            "exact_contract_available": False,
            "expiry": None,
            "strike": None,
            "instrument_key": None,
            "entry_premium": None,
            "exit_premium": None,
            "note": (
                "Exact CE/PE contract selection is not part of the current "
                "Midpoint evidence. Intent only; no contract is fabricated."
            ),
        },
        "checks": {
            "structure": structure_checks,
            "strategy": strategy_checks,
            "management": management_checks,
        },
    }


def _presentation_for_replay(
    minutes: list[dict[str, Any]],
    timeline_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_minute: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in timeline_rows:
        by_minute[_minute_token(event.get("timestamp"))].append(event)

    active: dict[str, Any] | None = None
    result: list[dict[str, Any]] = []

    for minute in minutes:
        item = dict(minute)
        events = by_minute.get(_minute_token(minute.get("timestamp")), [])
        item["events"] = events

        presentation: dict[str, Any] | None = None

        for event in events:
            et = str(event.get("event_type") or "")

            if et in ("B_ENTRY", "E_ENTRY"):
                active = {
                    "family": event.get("family"),
                    "direction": event.get("direction"),
                    "entry_timestamp": event.get("timestamp"),
                    "entry_underlying": event.get("underlying_price"),
                    "plus20": False,
                    "classifier": None,
                    "degraded": False,
                    "recovered": False,
                }

            if active is not None:
                if et == "PLUS20_PROOF":
                    active["plus20"] = True
                elif et == "RUNNER_CLASSIFICATION":
                    active["classifier"] = event.get("result") or event.get("reason")
                elif et == "DEGRADED_STARTED":
                    active["degraded"] = True
                elif et == "DEGRADED_TARGET_RECOVERED":
                    active["recovered"] = True

        if active is not None:
            direction = str(active.get("direction") or "")
            entry = _num(active.get("entry_underlying"))
            current = _num(item.get("underlying_close"))

            directional_move = None
            if entry is not None and current is not None:
                directional_move = (
                    current - entry
                    if direction == "BULLISH"
                    else entry - current
                    if direction == "BEARISH"
                    else None
                )

            raw = None
            fc = _num(item.get("futures_close"))
            fv = _num(item.get("futures_vwap"))
            if fc is not None and fv is not None:
                raw = fc - fv

            presentation = {
                "status": "ACTIVE",
                "label": f"CONTINUE · {direction}_ACTIVE",
                "family": active.get("family"),
                "direction": direction,
                "entry_timestamp": active.get("entry_timestamp"),
                "entry_underlying": entry,
                "current_underlying": current,
                "directional_move": directional_move,
                "plus20": bool(active.get("plus20")),
                "classifier": active.get("classifier"),
                "degraded": bool(active.get("degraded")),
                "recovered": bool(active.get("recovered")),
                "option_intent": (
                    "BUY CE"
                    if direction == "BULLISH"
                    else "BUY PE"
                    if direction == "BEARISH"
                    else None
                ),
                "futures_close": fc,
                "futures_vwap": fv,
                "raw_vwap_diff": raw,
                "vwap_position": (
                    "ABOVE VWAP"
                    if raw is not None and raw > 0
                    else "BELOW VWAP"
                    if raw is not None and raw < 0
                    else "AT VWAP"
                    if raw == 0
                    else "NOT AVAILABLE"
                ),
            }

            item["nifty_points_from_entry"] = round(directional_move, 4) if directional_move is not None else None
            item["nifty_entry_price"] = entry

        terminal = any(
            str(e.get("event_type") or "")
            in ("CAP20_RESCUE_TRIGGERED", "STRUCTURAL_TERMINAL")
            for e in events
        )

        if terminal and presentation is not None:
            presentation = dict(presentation)
            presentation["status"] = "EXIT"
            presentation["label"] = "EXIT"

        item["presentation"] = presentation
        result.append(item)

        if terminal:
            active = None

    return result


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
    rows = _with_nifty_points(_rows())[-limit:]
    return {"model": MODEL, "count": len(rows), "timeline": _timeline_projection(rows)}


@router.get("/audit-detail")
def audit_detail(event_id: str):
    for row in _with_nifty_points(_all_rows()):
        if row.get("event_id") == event_id:
            enriched = dict(row)
            enriched["ui"] = _audit_ui_detail(row)
            return {
                "model": MODEL,
                "event": enriched,
                "display_owner": _display_owner(row),
            }
    raise HTTPException(404, "Midpoint audit event not found")


@router.get("/option-observation")
def option_observation(session_date: str, as_of: str):
    """Read a previously acquired exact tape; never call a provider in a UI request."""
    from datetime import date, datetime
    try:
        day = date.fromisoformat(session_date)
        cutoff = datetime.fromisoformat(as_of)
        if cutoff.tzinfo is None or cutoff.date() != day:
            raise ValueError("AS_OF_REQUIRES_SESSION_DATE_AND_TIMEZONE")
    except ValueError as exc:
        raise HTTPException(422, "Invalid option observation date/as_of") from exc
    path = OPTION_TAPE_ROOT / f"{day.isoformat()}.json"
    if not path.exists():
        return {"model": "MIDPOINT_EXACT_OPTION_OBSERVATION_V1", "status": "UNAVAILABLE",
                "reason": "EXACT_OPTION_TAPE_NOT_MATERIALIZED", "as_of": as_of, "legs": []}
    try:
        payload = json.loads(path.read_text())
        tapes = [t for t in payload["tapes"] if t["entry_timestamp"] <= as_of]
        if not tapes:
            return {"model": "MIDPOINT_EXACT_OPTION_OBSERVATION_V1", "status": "NO_ENTRY_YET",
                    "as_of": as_of, "legs": []}
        return project_tape(tapes[-1], as_of)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Exact option observation tape unreadable") from exc


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
    rows = _with_nifty_points(_all_rows(audit_path))
    projected = _timeline_projection(rows)
    minutes_path = _historical_minutes_path(session_date)
    minutes = _load_jsonl(minutes_path)
    merged_minutes = _presentation_for_replay(minutes, projected)
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
    for row in _with_nifty_points(_all_rows(_historical_audit_path(session_date))):
        if row.get("event_id") == event_id:
            return {
                "model": MODEL,
                "mode": "HISTORICAL_REPLAY",
                "event": {**row, "ui": _audit_ui_detail(row)},
                "display_owner": _display_owner(row),
            }
    raise HTTPException(404, "Midpoint historical audit event not found")
