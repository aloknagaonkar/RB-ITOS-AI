from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


SNAPSHOT_FILENAME = "red_bar_v2_ui_snapshot.json"


@dataclass(frozen=True)
class RedBarV2UISnapshot:
    correlation_id: str | None = None
    strategy_version: str = "RED_BAR_V2"
    mode: str = "SHADOW"
    execution_scope: str = "OBSERVATION_ONLY"
    reference_status: str = "REFERENCE_NOT_READY"
    reference_timestamp: str | None = None
    reference_high: float | None = None
    reference_low: float | None = None
    reference_midpoint: float | None = None
    index_close: float | None = None
    index_rsi: float | None = None
    futures_close: float | None = None
    futures_vwap: float | None = None
    index_timestamp: str | None = None
    futures_timestamp: str | None = None
    alignment_status: str = "UNAVAILABLE"
    directional_state: str = "REFERENCE_NOT_READY"
    direction: str | None = None
    option_side: str | None = None
    reversal_status: str = "NO_REVERSAL"
    trade_status: str = "FLAT"
    trade_id: str | None = None
    admission_allowed: bool | None = None
    admission_timestamp: str | None = None
    admission_code: str | None = None
    admission_reason: str | None = None
    # The level the *admitted entry* was judged against, frozen at that moment.
    # Distinct from the ``governing_*`` block below in both time and meaning: this
    # is the one level that can invalidate this position, and for a deputy-born
    # (WORKING) entry it is the deputy's midpoint -- a level the live block can no
    # longer name, because the replay retires a deputy the instant it produces an
    # entry. ``admission_midpoint`` therefore does not track price; it stays put
    # until the next admission replaces it.
    admission_entry_type: str | None = None
    admission_reference: str | None = None
    admission_midpoint: float | None = None
    trend_strength: str | None = None
    provisional_confirmed_state: str = "NOT_APPLICABLE"
    midpoint_confirmation: str = "WAITING"
    midpoint_aligned: bool | None = None
    # The level in force at the last completed candle, and that candle's close.
    # Unlike ``index_close``/``index_timestamp``, which are read off the latest
    # *event* and so freeze between admissions, these advance every minute --
    # which is what makes them usable as an exit rule rather than a display.
    governing_reference: str | None = None
    governing_midpoint: float | None = None
    governing_close: float | None = None
    governing_close_timestamp: str | None = None
    governing_zone_position: str | None = None
    governing_distance_points: float | None = None
    last_evaluation_timestamp: str | None = None
    session_completeness: str = "UNAVAILABLE"
    futures_instrument_key: str | None = None
    futures_symbol: str | None = None
    futures_expiry: str | None = None
    recorded_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RedBarV2UISnapshot":
        allowed = cls.__dataclass_fields__
        values = {key: payload.get(key) for key in allowed if key in payload}
        return cls(**values)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _details(event: Any | None) -> Mapping[str, Any]:
    payload = getattr(event, "details", None)
    return payload if isinstance(payload, Mapping) else {}


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _governing(replay: Any) -> Mapping[str, Any]:
    """The governing-level block, or an empty mapping if the replay has none.

    Read defensively because the snapshot is also built from replay results
    recorded before the block existed, and a missing level has to leave every
    field ``None`` rather than raise -- the structural exit then simply declines
    to act, which is the fail-closed direction.
    """
    rule_state = getattr(replay, "rule_state", None)
    block = rule_state.get("governing") if isinstance(rule_state, Mapping) else None
    return block if isinstance(block, Mapping) else {}


def build_red_bar_v2_ui_snapshot_from_replay(
    monitored: Any,
    *,
    futures_instrument_key: str,
    futures_symbol: str | None = None,
    futures_expiry: str | None = None,
    mode: str = "SHADOW",
) -> RedBarV2UISnapshot:
    replay = monitored.replay
    health = monitored.health
    events = list(getattr(replay, "events", ()) or ())
    admissions = [event for event in events if getattr(event, "event_type", None) == "CANDIDATE_ADMISSION"]
    upgrades = [event for event in events if getattr(event, "event_type", None) == "STATE_UPGRADE"]
    closures = [event for event in events if getattr(event, "event_type", None) == "TRADE_CLOSED"]
    latest_event = events[-1] if events else None
    latest_admission = admissions[-1] if admissions else None
    latest_upgrade = upgrades[-1] if upgrades else None
    admission_details = _details(latest_admission)
    # The last *allowed* admission, which is a different event from the last
    # candidate: a blocked REVERSAL fires an admission event of its own, carrying
    # its own reference, while the position that is actually open was taken on an
    # earlier one. Everything else in the ``admission_*`` block describes the last
    # candidate on purpose -- the panel has to be able to say "blocked, and why" --
    # but the level a live row is answerable to must not move when a candidate the
    # strategy refused happens to be judged against a different reference.
    entries = [
        event for event in admissions
        if getattr(event, "candidate_allowed", None) is True
    ]
    entry_details = _details(entries[-1] if entries else None)
    admitted_entry_type = str(entry_details.get("entry_type") or "").upper()
    admission_conditions = admission_details.get("conditions")
    if not isinstance(admission_conditions, Mapping):
        admission_conditions = {}

    direction = getattr(latest_admission, "direction", None)
    option_side = getattr(latest_admission, "option_side", None)
    trend_strength = admission_details.get("trend_strength")
    state = admission_details.get("state")
    if not state and direction:
        prefix = "CONFIRMED" if trend_strength == "CONFIRMED" else "PROVISIONAL"
        state = f"{prefix}_{direction}"
    if not state:
        state = "REFERENCE_READY" if replay.reference_timestamp else "REFERENCE_NOT_READY"

    entry_type = str(admission_details.get("entry_type") or "").upper()
    reversal_status = "NO_REVERSAL"
    if entry_type == "REVERSAL":
        reversal_status = "REVERSAL_ADMITTED" if getattr(latest_admission, "candidate_allowed", None) else "REVERSAL_REJECTED"
    elif any("REVERSAL" in str(getattr(event, "admission_code", "")) for event in admissions):
        reversal_status = "REVERSAL_DETECTED"

    trade_status = str(getattr(replay, "final_trade_state", None) or "FLAT")
    if closures and trade_status == "FLAT":
        trade_status = "CLOSED"

    midpoint_aligned = admission_conditions.get("midpoint_aligned")
    if midpoint_aligned is True:
        midpoint_confirmation = f"{direction}_CONFIRMED" if direction else "CONFIRMED"
    elif midpoint_aligned is False:
        midpoint_confirmation = "WAITING"
    else:
        midpoint_confirmation = "WAITING"

    provisional_confirmed = "NOT_APPLICABLE"
    if trend_strength in {"PROVISIONAL", "CONFIRMED"}:
        provisional_confirmed = str(trend_strength)
    if latest_upgrade is not None:
        provisional_confirmed = "CONFIRMED"

    latest_details = _details(latest_event)
    governing = _governing(replay)
    return RedBarV2UISnapshot(
        mode=mode,
        execution_scope=str(getattr(health, "execution_scope", None) or "HISTORICAL_REPLAY_ONLY"),
        reference_status="REFERENCE_READY" if replay.reference_timestamp else "REFERENCE_NOT_READY",
        reference_timestamp=_iso(replay.reference_timestamp),
        reference_midpoint=getattr(replay, "reference_midpoint", None),
        index_close=latest_details.get("close_price") or admission_details.get("close_price"),
        index_rsi=latest_details.get("rsi_value") or admission_details.get("rsi_value"),
        futures_close=latest_details.get("futures_close") or admission_details.get("futures_close"),
        futures_vwap=latest_details.get("vwap_value") or admission_details.get("vwap_value"),
        index_timestamp=_iso(getattr(latest_event, "timestamp", None)),
        futures_timestamp=_iso(getattr(latest_event, "timestamp", None)),
        alignment_status=str(getattr(health, "status", None) or "UNAVAILABLE"),
        directional_state=str(state),
        direction=direction,
        option_side=option_side,
        reversal_status=reversal_status,
        trade_status=trade_status,
        trade_id=getattr(latest_admission, "trade_id", None),
        admission_allowed=getattr(latest_admission, "candidate_allowed", None),
        admission_timestamp=_iso(getattr(latest_admission, "timestamp", None)),
        admission_code=getattr(latest_admission, "admission_code", None),
        admission_reason=admission_details.get("admission_reason"),
        admission_entry_type=admitted_entry_type or None,
        admission_reference=(
            str(entry_details.get("governing_reference"))
            if entry_details.get("governing_reference")
            else None
        ),
        # ``reference_midpoint`` in the admission evidence is built from the
        # reference the decision was actually judged against, so on the deputy's
        # path this is the deputy's midpoint and not the red bar's.
        admission_midpoint=_float(entry_details.get("reference_midpoint")),
        trend_strength=str(trend_strength) if trend_strength else None,
        provisional_confirmed_state=provisional_confirmed,
        midpoint_confirmation=midpoint_confirmation,
        midpoint_aligned=midpoint_aligned if isinstance(midpoint_aligned, bool) else None,
        governing_reference=_iso(governing.get("reference")),
        governing_midpoint=_float(governing.get("midpoint")),
        governing_close=_float(governing.get("close")),
        governing_close_timestamp=_iso(governing.get("close_timestamp")),
        governing_zone_position=_iso(governing.get("zone_position")),
        governing_distance_points=_float(governing.get("distance_points")),
        last_evaluation_timestamp=_iso(getattr(latest_event, "timestamp", None)),
        session_completeness="ALIGNED_SESSION" if str(getattr(health, "status", "")) == "READY" else "UNAVAILABLE",
        futures_instrument_key=futures_instrument_key,
        futures_symbol=futures_symbol,
        futures_expiry=futures_expiry,
    )


def snapshot_path(artifacts_root: str | Path) -> Path:
    return Path(artifacts_root) / "operations" / SNAPSHOT_FILENAME


def persist_red_bar_v2_ui_snapshot(
    snapshot: RedBarV2UISnapshot,
    *,
    artifacts_root: str | Path,
) -> Path:
    target = snapshot_path(artifacts_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.to_dict()
    payload["recorded_at"] = datetime.now(timezone.utc).isoformat()
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)
    return target


def read_red_bar_v2_ui_snapshot(
    artifacts_root: str | Path,
) -> RedBarV2UISnapshot | None:
    target = snapshot_path(artifacts_root)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return RedBarV2UISnapshot.from_mapping(payload)
