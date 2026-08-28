from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.attribution_automation import (
    AttributionAwarePaperAutomationService,
)
from red_bar_lab.execution.paper_strategy_authority import PaperStrategyAuthority
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.market.upstox_intelligence import (
    UnifiedUpstoxMarketIntelligenceService,
)
from red_bar_lab.services.upstox_service import RedBarUpstoxService
from red_bar_lab.storage.database import RedBarDatabase


IST = ZoneInfo("Asia/Kolkata")


def _write_heartbeat(state_path: Path, **kwargs) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "component": "position_monitor",
        "pid": os.getpid(),
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    fd, tmp = tempfile.mkstemp(
        dir=str(state_path.parent), suffix=".tmp", prefix="position_monitor_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(state_path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fast paper-position price, protection and exit monitor. "
            "This process never scans strategies or sends broker orders."
        )
    )
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument(
        "--underlying",
        choices=("NIFTY 50", "BANK NIFTY"),
        default="NIFTY 50",
    )
    parser.add_argument("--minimum-score", type=float, default=65.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--heartbeat-path",
        default=None,
        help="Path to write atomic JSON heartbeat (for platform supervisor)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()

    if args.interval_seconds < 2:
        raise SystemExit("Use an interval of at least 2 seconds.")

    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN is required.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    heartbeat_path = Path(args.heartbeat_path) if args.heartbeat_path else (
        Path(__file__).resolve().parent.parent.parent / "artifacts" / "red_bar" / "platform" / "position_monitor_heartbeat.json"
    )

    settings = RedBarSettings.from_env()
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    authority = PaperStrategyAuthority.from_env()
    authority_ready, authority_reason = authority.validate()
    if not authority_ready:
        raise SystemExit(
            f"Paper strategy authority is blocked: {authority_reason}"
        )

    database.execution_source_enabled = authority.source_enabled

    upstox = RedBarUpstoxService(access_token)
    intelligence = UnifiedUpstoxMarketIntelligenceService(
        upstox,
        cache_ttl_seconds=2.0,
    )
    adapter = UpstoxPaperMarketAdapter(
        intelligence,
        args.underlying,
        UNDERLYINGS[args.underlying],
    )

    automation = AttributionAwarePaperAutomationService(
        zerodha=adapter,
        database=database,
        settings=settings,
        underlying_name=args.underlying,
        initial_capital=args.capital,
        minimum_candidate_score=args.minimum_score,
    )

    logging.info(
        "Fast paper-position monitor started. "
        "Underlying=%s interval=%ss mode=PAPER_ONLY",
        args.underlying,
        args.interval_seconds,
    )

    _write_heartbeat(
        heartbeat_path,
        state="RUNNING",
        started_at=datetime.now(IST).isoformat(),
        underlying=args.underlying,
        interval_seconds=args.interval_seconds,
    )

    while True:
        cycle_started = time.perf_counter()

        try:
            open_before = database.read_open_paper_execution_orders("PAPER-STD")

            if open_before:
                closed, errors = automation.monitor_and_exit()
                open_after = database.read_open_paper_execution_orders("PAPER-STD")
            else:
                closed, errors = 0, []
                open_after = []

            elapsed_ms = (time.perf_counter() - cycle_started) * 1000.0

            logging.info(
                "position_cycle=%s open_before=%s open_after=%s "
                "closed=%s errors=%s duration_ms=%.1f",
                datetime.now(IST).isoformat(),
                len(open_before),
                len(open_after),
                closed,
                len(errors),
                elapsed_ms,
            )

            _write_heartbeat(
                heartbeat_path,
                state="RUNNING",
                last_cycle_completed_at=datetime.now(IST).isoformat(),
                last_outcome=f"open={len(open_after)} closed={closed}",
                open_positions=len(open_after),
                closed_this_cycle=closed,
                duration_ms=round(elapsed_ms, 1),
            )

            for error in errors:
                logging.warning("position monitor: %s", error)

        except Exception:
            logging.exception("Fast position-monitor cycle failed")
            _write_heartbeat(
                heartbeat_path,
                state="ERROR",
                last_error="Cycle failed — see log",
                last_cycle_completed_at=datetime.now(IST).isoformat(),
            )

        if args.once:
            break

        elapsed = time.perf_counter() - cycle_started
        delay = max(
            0.25,
            float(args.interval_seconds) - elapsed,
        )
        time.sleep(delay)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
