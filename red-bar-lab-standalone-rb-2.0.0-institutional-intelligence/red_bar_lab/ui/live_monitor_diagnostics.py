from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from red_bar_lab.config import RedBarSettings


logger = logging.getLogger(__name__)


def live_reference_worker_status_path(
    settings: RedBarSettings,
) -> Path:
    """Return the on-disk path of the live reference worker's status JSON."""
    return Path(settings.database_path).parent / "live_reference_worker_status.json"


def read_live_reference_worker_status(
    settings: RedBarSettings,
) -> dict[str, Any] | None:
    """Read the live reference worker's most recent status JSON.

    Returns ``None`` if the file does not exist, is empty, or fails to parse.
    All exceptions are swallowed because this is a UI helper and must never
    break the surrounding page.
    """
    path = live_reference_worker_status_path(settings)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read live reference worker status: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _format_age(heartbeat_at: str | None) -> str:
    if not heartbeat_at:
        return "—"
    try:
        stamp = datetime.fromisoformat(heartbeat_at)
    except ValueError:
        return heartbeat_at
    delta = datetime.now(stamp.tzinfo) - stamp if stamp.tzinfo else None
    if delta is None:
        return heartbeat_at
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s ago"
    hours, rem = divmod(minutes, 60)
    return f"{hours}h {rem}m ago"


def _status_badge(status: str | None) -> str:
    if not status:
        return "UNKNOWN"
    upper = status.upper()
    if upper in {"RUNNING", "OK", "READY"}:
        return f"✅ {upper}"
    if upper in {"DEGRADED"}:
        return f"⚠️ {upper}"
    if upper in {"WAITING"}:
        return f"⏳ {upper}"
    if upper in {"ERROR", "FAILED"}:
        return f"❌ {upper}"
    return upper


def build_live_monitor_diagnostic_rows(
    status: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (summary_rows, level_rows) for the UI table renderers.

    ``summary_rows`` describe the overall monitor state. ``level_rows``
    describe each reference level's price-relative status with the same
    fields the live service emits at INFO level so the UI log view and
    the table view stay consistent.
    """
    summary_rows: list[dict[str, Any]] = [
        {
            "Field": "Status",
            "Value": _status_badge(status.get("status")),
        },
        {
            "Field": "Heartbeat",
            "Value": f"{status.get('heartbeat_at') or '—'} ({_format_age(status.get('heartbeat_at'))})",
        },
        {
            "Field": "Trading date",
            "Value": status.get("trading_date") or "—",
        },
        {
            "Field": "Source rows (1m candles)",
            "Value": str(status.get("source_rows") or 0),
        },
        {
            "Field": "Levels stored",
            "Value": str(status.get("levels_stored") or 0),
        },
        {
            "Field": "Completed 5-min candles",
            "Value": str(status.get("completed_five_minute_rows") or 0),
        },
        {
            "Field": "Current spot price",
            "Value": (
                f"{float(status['current_price']):.2f}"
                if status.get("current_price") is not None
                else "—"
            ),
        },
        {
            "Field": "Signal attempts (this cycle)",
            "Value": str(status.get("attempts") if status.get("attempts") is not None else "—"),
        },
        {
            "Field": "Active attempts",
            "Value": str(status.get("active_attempts") if status.get("active_attempts") is not None else "—"),
        },
        {
            "Field": "Awaiting confirmation",
            "Value": str(status.get("awaiting_attempts") if status.get("awaiting_attempts") is not None else "—"),
        },
    ]
    if status.get("last_error"):
        summary_rows.append(
            {"Field": "Last error", "Value": str(status["last_error"])}
        )

    level_rows: list[dict[str, Any]] = []
    for entry in status.get("level_diagnostics") or []:
        if not isinstance(entry, dict):
            continue
        level_rows.append(
            {
                "Level": entry.get("level_type") or "—",
                "Source timestamp": entry.get("source_timestamp") or "—",
                "Range": (
                    f"{float(entry['source_low']):.2f} – {float(entry['source_high']):.2f}"
                    if entry.get("source_low") is not None
                    and entry.get("source_high") is not None
                    else "—"
                ),
                "Midpoint": (
                    f"{float(entry['midpoint']):.2f}"
                    if entry.get("midpoint") is not None
                    else "—"
                ),
                "Spot price": (
                    f"{float(entry['current_price']):.2f}"
                    if entry.get("current_price") is not None
                    else "—"
                ),
                "Distance to high": (
                    f"{float(entry['distance_to_high']):+.2f}"
                    if entry.get("distance_to_high") is not None
                    else "—"
                ),
                "Distance to low": (
                    f"{float(entry['distance_to_low']):+.2f}"
                    if entry.get("distance_to_low") is not None
                    else "—"
                ),
                "Status": entry.get("status") or "—",
                "Last attempt state": entry.get("last_attempt_state") or "—",
                "Why no signal": entry.get("explanation") or "—",
            }
        )
    return summary_rows, level_rows


__all__ = [
    "build_live_monitor_diagnostic_rows",
    "live_reference_worker_status_path",
    "read_live_reference_worker_status",
]
