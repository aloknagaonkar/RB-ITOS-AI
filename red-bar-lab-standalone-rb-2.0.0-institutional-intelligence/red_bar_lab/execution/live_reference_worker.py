from __future__ import annotations

import argparse
import json
import logging
import os
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from red_bar_lab.collector.service import market_session_phase
from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.live_service import RedBarLiveService
from red_bar_lab.services.upstox_service import RedBarUpstoxService, resolve_access_token
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase

IST = ZoneInfo("Asia/Kolkata")
WORKER_ID = "LIVE_REFERENCE_WORKER"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Continuously refresh current-session one-minute candles and persist "
            "daily reference levels independently of the Streamlit UI."
        )
    )
    parser.add_argument(
        "--underlying",
        default="NIFTY 50",
        choices=tuple(UNDERLYINGS),
    )
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one refresh immediately and exit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh outside the normal OPEN market phase.",
    )
    return parser


def _status_path(settings: RedBarSettings) -> Path:
    return Path(settings.database_path).parent / "live_reference_worker_status.json"


def _write_status(
    path: Path,
    *,
    status: str,
    now: datetime,
    underlying_name: str,
    message: str,
    result: Any | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "worker_id": WORKER_ID,
        "status": status,
        "heartbeat_at": now.isoformat(),
        "underlying_name": underlying_name,
        "message": message,
        "last_error": error,
        "pid": os.getpid(),
    }
    if result is not None:
        payload.update(
            {
                "trading_date": result.trading_date.isoformat(),
                "connected": bool(result.connected),
                "source_rows": int(result.source_rows),
                "levels_stored": int(result.levels_stored),
                "completed_five_minute_rows": int(
                    result.completed_five_minute_rows
                ),
                "last_refresh": result.last_refresh.isoformat(),
            }
        )
        current_price = getattr(result, "current_price", None)
        if current_price is not None:
            payload["current_price"] = float(current_price)
        attempts = getattr(result, "attempts", None)
        if attempts is not None:
            payload["attempts"] = int(attempts)
        active = getattr(result, "active", None)
        if active is not None:
            payload["active_attempts"] = int(active)
        awaiting = getattr(result, "awaiting", None)
        if awaiting is not None:
            payload["awaiting_attempts"] = int(awaiting)
        level_diagnostics = getattr(result, "level_diagnostics", None)
        if level_diagnostics:
            payload["level_diagnostics"] = list(level_diagnostics)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _format_level_diagnostics(
    level_diagnostics: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> str:
    """Render per-level diagnostics into a single human-readable line."""
    if not level_diagnostics:
        return "no-levels-built-yet"
    parts: list[str] = []
    for entry in level_diagnostics:
        level_type = entry.get("level_type")
        status = entry.get("status")
        explanation = entry.get("explanation")
        parts.append(
            f"{level_type}={status}"
            + (f" ({explanation})" if explanation else "")
        )
    return "; ".join(parts)


def _should_refresh(now: datetime, *, force: bool) -> bool:
    return force or market_session_phase(now) == "OPEN"


def _build_service(settings: RedBarSettings) -> RedBarLiveService:
    layout = ArtifactLayout(settings)
    layout.ensure()
    database = RedBarDatabase(settings.database_path)
    database.initialize()
    token = resolve_access_token("")
    provider = RedBarUpstoxService(token)
    historical = RedBarHistoricalService(provider, layout)
    return RedBarLiveService(historical, layout, database)


def run_cycle(
    service: RedBarLiveService,
    *,
    instrument_key: str,
    underlying_name: str,
    status_path: Path,
    now: datetime,
    force: bool = False,
) -> Any | None:
    phase = market_session_phase(now)
    if not _should_refresh(now, force=force):
        message = f"Waiting; market phase is {phase}."
        _write_status(
            status_path,
            status="WAITING",
            now=now,
            underlying_name=underlying_name,
            message=message,
        )
        logging.info(message)
        return None

    try:
        result = service.refresh(instrument_key)
    except Exception as exc:
        message = f"Live reference refresh failed: {exc}"
        _write_status(
            status_path,
            status="ERROR",
            now=now,
            underlying_name=underlying_name,
            message=message,
            error=str(exc)[:1000],
        )
        logging.exception(message)
        return None

    status = "RUNNING" if result.connected else "DEGRADED"
    _write_status(
        status_path,
        status=status,
        now=now,
        underlying_name=underlying_name,
        message=result.message,
        result=result,
    )
    attempts_value = int(getattr(result, "attempts", 0) or 0)
    current_price = getattr(result, "current_price", None)
    level_diagnostics = getattr(result, "level_diagnostics", ()) or ()
    active_count = int(getattr(result, "active", 0) or 0)
    awaiting_count = int(getattr(result, "awaiting", 0) or 0)
    logging.info(
        "live reference refresh status=%s date=%s source_rows=%s levels=%s "
        "completed_5m=%s current_price=%s attempts=%s active=%s awaiting=%s message=%s",
        status,
        result.trading_date,
        result.source_rows,
        result.levels_stored,
        result.completed_five_minute_rows,
        current_price,
        attempts_value,
        active_count,
        awaiting_count,
        result.message,
    )
    if attempts_value == 0 and not active_count and not awaiting_count:
        logging.info(
            "live reference monitor: no signal candidates this cycle. "
            "current_price=%s levels_built=%s diagnostic=%s",
            current_price,
            len(level_diagnostics),
            _format_level_diagnostics(level_diagnostics),
        )
    return result


def main() -> int:
    args = _parser().parse_args()
    if args.interval_seconds < 30:
        raise SystemExit("Minimum live-reference interval is 30 seconds.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = RedBarSettings.from_env()
    status_path = _status_path(settings)
    service = _build_service(settings)
    instrument_key = UNDERLYINGS[args.underlying]

    logging.info(
        "starting live reference worker underlying=%s interval=%ss status_file=%s",
        args.underlying,
        args.interval_seconds,
        status_path,
    )

    while True:
        now = datetime.now(IST)
        run_cycle(
            service,
            instrument_key=instrument_key,
            underlying_name=args.underlying,
            status_path=status_path,
            now=now,
            force=args.force or args.once,
        )
        if args.once:
            break
        time_module.sleep(args.interval_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WORKER_ID", "main", "run_cycle"]
