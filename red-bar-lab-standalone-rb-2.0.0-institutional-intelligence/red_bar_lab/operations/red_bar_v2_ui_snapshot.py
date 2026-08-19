from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


SNAPSHOT_FILENAME = "red_bar_v2_ui_snapshot.json"


@dataclass(frozen=True)
class RedBarV2UISnapshot:
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
    admission_code: str | None = None
    admission_reason: str | None = None
    trend_strength: str | None = None
    provisional_confirmed_state: str = "NOT_APPLICABLE"
    midpoint_confirmation: str = "WAITING"
    midpoint_aligned: bool | None = None
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
