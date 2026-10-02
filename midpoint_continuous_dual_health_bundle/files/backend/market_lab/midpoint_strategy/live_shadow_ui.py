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


def _market_health_payload(audit_path: Path) -> dict[str, Any] | None:
    path = audit_path.with_name("market-health.json")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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


def _causal_option_tapes(payload: dict[str, Any], as_of: str) -> list[dict]:
    """Sort eligible tapes by entry time, never by JSON append order."""
    return sorted(
        (tape for tape in payload["tapes"]
         if tape["entry_timestamp"] <= as_of),
        key=lambda tape: (
            str(tape.get("entry_timestamp") or ""),
            str(tape.get("entry_event_id") or ""),
        ),
    )


def _latest_family_state(rows):
    for row in reversed(rows):
        event_type = str(row.get("event_type") or "")
        if (
            event_type.startswith("NORMAL_B_PROVED_")
            or event_type == "DEGRADED_EXIT_CANDIDATE_TRIGGERED"
            or event_type.startswith("HEALTH_")
            or event_type.startswith("CONTINUOUS_HEALTH_")
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


_HEALTH_EVENT_TYPES = {
    "PRE_ENTRY_HEALTH_SNAPSHOT",
    "ENTRY_HEALTH_SNAPSHOT",
    "T5_HEALTH_CHECK",
    "T5_TWO_OF_THREE_EXIT_CANDIDATE",
    "T5_COMBINED_EDGE_EXIT_CANDIDATE",
    "T5_PROVED_BYPASS",
    "T5_HEALTH_UNAVAILABLE",
}

# These are health observations, not lifecycle decisions.  They remain in the
# immutable audit and in the full minute replay, but the primary decision table
# projects them into its dedicated Health column instead of allowing them to
# replace Event / Reason rows.
_HEALTH_SNAPSHOT_ONLY_TYPES = {
    "PRE_ENTRY_HEALTH_SNAPSHOT",
    "ENTRY_HEALTH_SNAPSHOT",
    "T5_HEALTH_CHECK",
    "T5_PROVED_BYPASS",
    "T5_HEALTH_UNAVAILABLE",
    "CONTINUOUS_HEALTH_CHECK",
}

_TRADE_ENTRY_TYPES = {
    "A_ENTRY", "B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_B_ENTRY", "PM_E_ENTRY",
    "B_REARM_ENTRY", "E_REARM_ENTRY",
}
_TRADE_TERMINAL_TYPES = {"STRUCTURAL_TERMINAL", "CAP20_SHADOW_EXIT"}


def _trade_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    """Identity shared by one independently managed trade lane."""
    return (
        _row_day(row),
        row.get("family"),
        row.get("direction"),
        row.get("reference_type"),
    )


def _selected_trade_view(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return one causally coherent lane for the dashboard summary.

    A, canonical B/E, repeated B/E and PM lifecycles may coexist in the audit.
    Global ``latest_*`` fields therefore cannot safely be combined. Events are
    assigned to the newest still-open entry with the exact same session,
    family, direction and reference. The newest active lane wins; otherwise
    the most recently updated completed lane is shown.
    """
    lanes: list[dict[str, Any]] = []
    open_by_identity: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)

    for order, original in enumerate(rows):
        event_type = str(original.get("event_type") or "").upper()
        identity = _trade_identity(original)
        if event_type in _TRADE_ENTRY_TYPES:
            lane = {
                "identity": identity,
                "entry": dict(original),
                "events": [dict(original)],
                "entry_order": order,
                "last_order": order,
                "terminal": None,
            }
            lanes.append(lane)
            open_by_identity[identity].append(lane)
            continue

        candidates = open_by_identity.get(identity) or []
        if not candidates:
            continue
        lane = candidates[-1]
        lane["events"].append(dict(original))
        lane["last_order"] = order
        if event_type in _TRADE_TERMINAL_TYPES:
            lane["terminal"] = dict(original)
            candidates.pop()

    if not lanes:
        return None
    latest_day = max(str(lane["identity"][0] or "") for lane in lanes)
    current_day_lanes = [
        lane for lane in lanes if str(lane["identity"][0] or "") == latest_day
    ]
    active = [lane for lane in current_day_lanes if lane["terminal"] is None]
    selected = max(active or current_day_lanes, key=lambda lane: lane["last_order"])
    entry = selected["entry"]
    entry_price = _num(entry.get("underlying_price"))
    direction = entry.get("direction")
    sign = 1 if direction == "BULLISH" else -1
    lane_rows: list[dict[str, Any]] = []
    for original in selected["events"]:
        row = dict(original)
        price = _num(row.get("underlying_price"))
        points = (
            round(sign * (price - entry_price), 4)
            if entry_price is not None and price is not None
            and direction in {"BULLISH", "BEARISH"}
            else None
        )
        row["nifty_points_from_entry"] = points
        row["nifty_entry_price"] = entry_price if points is not None else None
        lane_rows.append(row)

    def latest(*types: str) -> dict[str, Any] | None:
        wanted = set(types)
        return next(
            (row for row in reversed(lane_rows)
             if str(row.get("event_type") or "").upper() in wanted),
            None,
        )

    health = next(
        (row for row in reversed(lane_rows)
         if _timeline_health(row)[0] is not None),
        None,
    )
    return {
        "trade_id": entry.get("event_id"),
        "status": "ACTIVE" if selected["terminal"] is None else "CLOSED",
        "entry": lane_rows[0],
        "latest_event": lane_rows[-1],
        "plus20": latest("PLUS20_PROOF"),
        "classifier": latest("RUNNER_CLASSIFICATION"),
        "management_route": latest("MANAGEMENT_ROUTE_SELECTED"),
        "degraded": latest("DEGRADED_STARTED"),
        "degraded_exit": latest("DEGRADED_EXIT_CANDIDATE_TRIGGERED"),
        "recovery": latest("DEGRADED_TARGET_RECOVERED"),
        "rescue": latest("CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT"),
        "normal_b_step": latest(
            "NORMAL_B_PROVED_STARTED", "NORMAL_B_PROVED_TIER2",
            "NORMAL_B_PROVED_TIER3", "NORMAL_B_PROVED_EXIT_CANDIDATE",
            "NORMAL_B_PROVED_UNAVAILABLE",
        ),
        "health": health,
        "health_immediate_exit": latest(
            "HEALTH_IMMEDIATE_CONFIRMATION_EXIT_CANDIDATE"
        ),
        "health_two_close_exit": latest(
            "HEALTH_TWO_CLOSE_CONFIRMATION_EXIT_CANDIDATE"
        ),
        "terminal": latest(*_TRADE_TERMINAL_TYPES),
        "event_count": len(lane_rows),
    }


def _timeline_health(row: dict[str, Any]) -> tuple[str | None, int | None]:
    """Project only health evidence recorded on this exact event."""
    evidence = row.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    event_type = str(row.get("event_type") or "").upper()
    if event_type not in _HEALTH_EVENT_TYPES and "health" not in evidence:
        return None, None

    health = evidence.get("health")
    support_count = evidence.get("support_count")
    if health is None and evidence.get("available") is False:
        health = "UNAVAILABLE"
    if health is None and evidence.get("failure_count") is not None:
        failures = int(evidence["failure_count"])
        health = "UNHEALTHY" if failures >= 2 else "HEALTHY"
        support_count = 3 - failures if support_count is None else support_count
    if health is None and event_type in _HEALTH_EVENT_TYPES:
        result = str(row.get("result") or "").upper()
        if result in {"HEALTHY", "UNHEALTHY", "UNAVAILABLE"}:
            health = result

    return (
        str(health) if health is not None else None,
        int(support_count) if support_count is not None else None,
    )


def _with_nifty_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Presentation-only close points, independently tracked per trade lane."""
    active: dict[tuple[Any, ...], dict[str, Any]] = {}
    projected = []
    for original in rows:
        row = dict(original)
        kind = row.get("event_type")
        identity = _trade_identity(row)
        if kind in _TRADE_ENTRY_TYPES:
            entry_price = _num(row.get("underlying_price"))
            if entry_price is not None:
                active[identity] = {
                    "entry": entry_price,
                    "direction": row.get("direction"),
                }
        lane = active.get(identity)
        price = _num(row.get("underlying_price"))
        move = None
        if lane and price is not None:
            sign = 1 if lane["direction"] == "BULLISH" else -1
            move = round(sign * (price - lane["entry"]), 4)
        row["nifty_points_from_entry"] = move
        row["nifty_entry_price"] = lane["entry"] if move is not None else None
        projected.append(row)
        if kind in _TRADE_TERMINAL_TYPES:
            active.pop(identity, None)
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
            "health": _timeline_health(r)[0],
            "health_support_count": _timeline_health(r)[1],
        }
        for r in rows
    ]


def _decision_timeline_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep lifecycle rows primary and causally project health onto every signal.

    The raw audit is deliberately unchanged.  Each decision receives the latest
    already-observed health for its own lane.  A snapshot written after several
    decisions for the same completed minute is attached to every matching
    decision in that minute, but never rewrites an earlier minute (no future
    leakage).  Candidate exit events remain first-class decision rows.
    """
    output: list[dict[str, Any]] = []
    latest_health: dict[tuple[Any, ...], dict[str, Any]] = {}
    active_lanes: set[tuple[Any, ...]] = set()
    decisions_by_lane_minute: dict[tuple[tuple[Any, ...], Any], list[int]] = defaultdict(list)

    def lane(row: dict[str, Any]) -> tuple[Any, ...]:
        # Family is deliberately excluded: midpoint/boundary qualification can
        # be logged under B before the same reference is finally owned by E/A.
        # The reference and its direction are the stable trade identity.
        return (
            _row_day(row),
            row.get("direction"),
            row.get("reference_type"),
        )

    def health_payload(row: dict[str, Any]) -> dict[str, Any]:
        health, support_count = _timeline_health(row)
        return {
            "health": health,
            "health_support_count": support_count,
            "health_event_id": row.get("event_id"),
            "health_timestamp": row.get("event_timestamp"),
        }

    def attach(index: int, payload: dict[str, Any]) -> None:
        output[index].update(payload)

    for row in rows:
        event_type = str(row.get("event_type") or "").upper()
        row_lane = lane(row)
        row_minute = row.get("event_timestamp")
        is_entry = event_type in {
            "A_ENTRY", "B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_B_ENTRY",
            "PM_E_ENTRY", "B_REARM_ENTRY", "E_REARM_ENTRY",
        }
        if is_entry:
            active_lanes.add(row_lane)
        if event_type in _HEALTH_SNAPSHOT_ONLY_TYPES:
            payload = health_payload(row)
            latest_health[row_lane] = payload
            for target in decisions_by_lane_minute.get((row_lane, row_minute), []):
                attach(target, payload)
            continue

        projected = _timeline_projection([row])[0]
        if projected.get("health") is not None:
            payload = health_payload(row)
            latest_health[row_lane] = payload
            projected.update(payload)
        elif row_lane in active_lanes and row_lane in latest_health:
            projected.update(latest_health[row_lane])
        else:
            projected["health_event_id"] = None
            projected["health_timestamp"] = None
        output.append(projected)
        decisions_by_lane_minute[(row_lane, row_minute)].append(len(output) - 1)
        if event_type in {"STRUCTURAL_TERMINAL", "CAP20_SHADOW_EXIT"}:
            active_lanes.discard(row_lane)
            latest_health.pop(row_lane, None)

    return output


def _matching_health_detail(
    decision: dict[str, Any], candidate: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Accept only same-lane health known no later than the decision minute."""
    if candidate is None:
        return None
    same_lane = (
        _row_day(candidate) == _row_day(decision)
        and candidate.get("direction") == decision.get("direction")
        and candidate.get("reference_type") == decision.get("reference_type")
    )
    causal = str(candidate.get("event_timestamp") or "") <= str(
        decision.get("event_timestamp") or ""
    )
    return candidate if same_lane and causal else None


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
        "selected_trade": _selected_trade_view(rows),
        "system_health": (
            _market_health_payload(resolved_path) if mode == "LIVE" else None
        ),
        "latest_event": rows[-1] if rows else None,
        "latest_entry": _latest_any(
            rows, (
                "A_ENTRY", "B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_B_ENTRY", "PM_E_ENTRY",
                "B_REARM_ENTRY", "E_REARM_ENTRY",
            )
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
        "latest_t5_health_check": _latest(rows, "T5_HEALTH_CHECK"),
        "latest_t5_two_of_three": _latest(
            rows, "T5_TWO_OF_THREE_EXIT_CANDIDATE"
        ),
        "latest_t5_combined_edge": _latest(
            rows, "T5_COMBINED_EDGE_EXIT_CANDIDATE"
        ),
        "latest_t5_proved_bypass": _latest(rows, "T5_PROVED_BYPASS"),
        "latest_t5_unavailable": _latest(rows, "T5_HEALTH_UNAVAILABLE"),
        "latest_pre_entry_health": _latest(
            rows, "PRE_ENTRY_HEALTH_SNAPSHOT"
        ),
        "latest_entry_health": _latest(rows, "ENTRY_HEALTH_SNAPSHOT"),
        "latest_continuous_health": _latest(rows, "CONTINUOUS_HEALTH_CHECK"),
        "latest_health_immediate_exit": _latest(
            rows, "HEALTH_IMMEDIATE_CONFIRMATION_EXIT_CANDIDATE"
        ),
        "latest_health_two_close_exit": _latest(
            rows, "HEALTH_TWO_CLOSE_CONFIRMATION_EXIT_CANDIDATE"
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

    if event_type == "A_ENTRY":
        strategy_checks.append(
            _check(
                "Family A parallel entry",
                passed=True,
                observed="A ENTRY · OBSERVATION ONLY",
                required=(
                    "fresh Candidate A at boundary; canonical B/E lane remains unchanged"
                ),
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
    active_health: str | None = None
    active_health_support: int | None = None
    active_health_event_id: str | None = None
    result: list[dict[str, Any]] = []

    for minute in minutes:
        item = dict(minute)
        events = by_minute.get(_minute_token(minute.get("timestamp")), [])
        item["events"] = events

        presentation: dict[str, Any] | None = None

        for event in events:
            et = str(event.get("event_type") or "")

            if event.get("health") is not None:
                active_health = str(event.get("health"))
                active_health_support = event.get("health_support_count")
                active_health_event_id = event.get("event_id")

            if et in (
                "A_ENTRY", "B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_B_ENTRY",
                "PM_E_ENTRY", "B_REARM_ENTRY", "E_REARM_ENTRY",
            ):
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
                "health": active_health,
                "health_support_count": active_health_support,
                "health_event_id": active_health_event_id,
            }

            item["nifty_points_from_entry"] = round(directional_move, 4) if directional_move is not None else None
            item["nifty_entry_price"] = entry

        item["health"] = active_health if active is not None else None
        item["health_support_count"] = active_health_support if active is not None else None
        item["health_event_id"] = active_health_event_id if active is not None else None

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
            active_health = None
            active_health_support = None
            active_health_event_id = None

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
    projected = _decision_timeline_projection(_with_nifty_points(_rows()))[-limit:]
    return {"model": MODEL, "count": len(projected), "timeline": projected}


@router.get("/audit-detail")
def audit_detail(event_id: str, health_event_id: str | None = None):
    rows = _with_nifty_points(_all_rows())
    health_row = next(
        (row for row in rows if row.get("event_id") == health_event_id), None
    ) if health_event_id else None
    for row in rows:
        if row.get("event_id") == event_id:
            health_row = _matching_health_detail(row, health_row)
            enriched = dict(row)
            health_source = health_row or row
            health, support_count = _timeline_health(health_source)
            enriched["health"] = health
            enriched["health_support_count"] = support_count
            if health_row is not None:
                enriched["health_event_id"] = health_row.get("event_id")
                enriched["health_timestamp"] = health_row.get("event_timestamp")
                enriched["health_evidence"] = health_row.get("evidence") or {}
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
        tapes = _causal_option_tapes(payload, as_of)
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


def _historical_health_path(session_date: str) -> Path:
    return _historical_session_dir(session_date) / "trade-health.jsonl"


def _historical_rows(session_date: str) -> list[dict[str, Any]]:
    """Merge immutable strategy audit with a separate health overlay.

    Health rows sort before decisions from the same completed minute so every
    same-minute decision can receive that completed-close health without
    making a later minute visible early.  Neither source file is rewritten.
    """
    audit = _all_rows(_historical_audit_path(session_date))
    health = _load_jsonl(_historical_health_path(session_date))
    tagged = [(row, 1, index) for index, row in enumerate(audit)]
    tagged.extend((row, 0, index) for index, row in enumerate(health))
    tagged.sort(key=lambda item: (
        str(item[0].get("event_timestamp") or ""), item[1], item[2]
    ))
    return [row for row, _, _ in tagged]


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
    rows = _with_nifty_points(_historical_rows(session_date))
    raw_projected = _timeline_projection(rows)
    projected = _decision_timeline_projection(rows)
    minutes_path = _historical_minutes_path(session_date)
    minutes = _load_jsonl(minutes_path)
    merged_minutes = _presentation_for_replay(minutes, raw_projected)
    return {
        "model": MODEL,
        "mode": "HISTORICAL_REPLAY",
        "session_date": session_date,
        "status": _status_payload(rows, "HISTORICAL_REPLAY", audit_path=audit_path),
        "count": len(projected),
        "timeline": projected,
        "minute_count": len(merged_minutes),
        "minutes": merged_minutes,
        "health_overlay": {
            "available": _historical_health_path(session_date).exists(),
            "event_count": sum(
                1 for row in rows
                if str(row.get("event_type") or "") in _HEALTH_SNAPSHOT_ONLY_TYPES
            ),
            "source": "SAME_LIVE_DIRECTIONAL_HEALTH_ENGINE",
            "observation_only": True,
        },
    }


@router.get("/historical/audit-detail")
def historical_audit_detail(
    session_date: str, event_id: str, health_event_id: str | None = None
):
    rows = _with_nifty_points(_historical_rows(session_date))
    health_row = next(
        (row for row in rows if row.get("event_id") == health_event_id), None
    ) if health_event_id else None
    for row in rows:
        if row.get("event_id") == event_id:
            health_row = _matching_health_detail(row, health_row)
            health_source = health_row or row
            health, support_count = _timeline_health(health_source)
            return {
                "model": MODEL,
                "mode": "HISTORICAL_REPLAY",
                "event": {
                    **row,
                    "health": health,
                    "health_support_count": support_count,
                    "health_event_id": (
                        health_row.get("event_id") if health_row else None
                    ),
                    "health_timestamp": (
                        health_row.get("event_timestamp") if health_row else None
                    ),
                    "health_evidence": (
                        health_row.get("evidence") or {} if health_row else None
                    ),
                    "ui": _audit_ui_detail(row),
                },
                "display_owner": _display_owner(row),
            }
    raise HTTPException(404, "Midpoint historical audit event not found")
