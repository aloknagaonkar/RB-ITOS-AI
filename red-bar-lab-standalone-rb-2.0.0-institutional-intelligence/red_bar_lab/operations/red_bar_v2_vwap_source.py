from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2VwapSourceHealth,
)


HEALTH_FILENAME = "red_bar_v2_vwap_source_health.json"


@dataclass(frozen=True)
class PersistedRedBarV2VwapHealth:
    payload: dict[str, Any]
    path: Path

    @property
    def status(self) -> str:
        return str(self.payload.get("status") or "UNAVAILABLE")


def health_path(artifacts_root: str | Path) -> Path:
    return Path(artifacts_root) / "operations" / HEALTH_FILENAME


def persist_red_bar_v2_vwap_health(
    health: RedBarV2VwapSourceHealth,
    *,
    artifacts_root: str | Path,
    trading_date: str,
    futures_symbol: str | None = None,
    futures_expiry: str | None = None,
) -> Path:
    """Atomically persist the exact replay health payload for Operations UI."""
    target = health_path(artifacts_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = health.to_dict()
    payload.update(
        {
            "consumer": "RED_BAR_V2",
            "trading_date": trading_date,
            "futures_symbol": futures_symbol,
            "futures_expiry": futures_expiry,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def read_red_bar_v2_vwap_health(
    artifacts_root: str | Path,
) -> PersistedRedBarV2VwapHealth | None:
    target = health_path(artifacts_root)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return PersistedRedBarV2VwapHealth(payload=payload, path=target)


def operations_health_row(
    artifacts_root: str | Path,
) -> dict[str, object]:
    """Return a UI-safe row for the existing Operations Center health table."""
    persisted = read_red_bar_v2_vwap_health(artifacts_root)
    if persisted is None:
        return {
            "Service": "Red Bar V2 Futures VWAP",
            "State": "WARNING",
            "Detail": "No historical replay VWAP-source health has been recorded yet.",
        }
    payload = persisted.payload
    status = persisted.status.upper()
    state = "HEALTHY" if status == "READY" else "CRITICAL" if status == "BLOCKED" else "WARNING"
    detail = (
        f"{payload.get('vwap_source_instrument') or '—'} · "
        f"alignment {payload.get('aligned_rows', 0)}/{payload.get('index_rows', 0)} "
        f"({payload.get('alignment_coverage_pct', 0)}%) · "
        f"volume rows {payload.get('positive_volume_rows', 0)} · "
        f"{payload.get('execution_scope') or 'HISTORICAL_REPLAY_ONLY'}"
    )
    return {
        "Service": "Red Bar V2 Futures VWAP",
        "State": state,
        "Detail": detail,
    }
