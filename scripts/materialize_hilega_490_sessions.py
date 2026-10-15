#!/usr/bin/env python3
"""Extend the immutable Hilega underlying cache to 490 analysis sessions.

Ten additional sessions are retained only as leading indicator context.  The
script never overwrites an existing cache file and never changes strategy,
service, audit, order, paper-order, or quantity state.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from market_lab.gateways import UpstoxGateway
from market_lab.hilega_milega_historical_replay_v1 import (
    UNDERLYING,
    _read_cache,
    _write_cache,
    aggregate_exact_5m,
)


DEFAULT_CACHE = Path(
    "data/historical-evidence/hilega-milega-underlying-cache-v1"
)
DEFAULT_REPORT = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "materialization-report.json"
)


def cache_date(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def valid_cached_sessions(cache_root: Path) -> list[date]:
    result: list[date] = []
    for path in sorted(cache_root.glob("*.json")):
        day = cache_date(path)
        if day is None:
            continue
        candles = _read_cache(path, UNDERLYING, day)
        if not candles:
            continue
        try:
            bars = aggregate_exact_5m(candles, day, require_full_session=True)
        except ValueError:
            continue
        if len(bars) == 75:
            result.append(day)
    return result


def fetch_with_retry(
    gateway: UpstoxGateway,
    day: date,
    *,
    attempts: int,
) -> tuple[list[Any], str | None]:
    error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            rows = gateway.historical_candles(UNDERLYING, day)
            return sorted(rows, key=lambda row: row.timestamp), None
        except Exception as exc:  # gateway translates provider errors
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
    return [], error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-sessions", type=int, default=490)
    parser.add_argument("--context-sessions", type=int, default=10)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.20)
    parser.add_argument("--max-calendar-days", type=int, default=1600)
    args = parser.parse_args()

    if args.analysis_sessions < 1 or args.context_sessions < 0:
        raise SystemExit("STOP: session counts must be positive")
    required = args.analysis_sessions + args.context_sessions

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("STOP: UPSTOX_ACCESS_TOKEN is unavailable")

    args.cache_root.mkdir(parents=True, exist_ok=True)
    before = valid_cached_sessions(args.cache_root)
    if not before:
        raise SystemExit(
            "STOP: no existing valid Hilega session establishes the latest date"
        )

    gateway = UpstoxGateway(token)
    acquired: list[str] = []
    unavailable: list[dict[str, str | None]] = []
    current = min(before) - timedelta(days=1)
    examined = 0
    valid = list(before)

    try:
        while len(valid) < required and examined < args.max_calendar_days:
            examined += 1
            if current.weekday() >= 5:
                current -= timedelta(days=1)
                continue

            path = args.cache_root / f"{current.isoformat()}.json"
            if path.exists():
                # Existing evidence is immutable, even if incomplete.
                unavailable.append(
                    {"session_date": current.isoformat(), "reason": "EXISTING_INVALID_CACHE"}
                )
                current -= timedelta(days=1)
                continue

            candles, error = fetch_with_retry(
                gateway, current, attempts=max(args.attempts, 1)
            )
            if error is not None:
                unavailable.append({"session_date": current.isoformat(), "reason": error})
            elif not candles:
                unavailable.append(
                    {"session_date": current.isoformat(), "reason": "NO_CANDLES"}
                )
            else:
                try:
                    bars = aggregate_exact_5m(
                        candles, current, require_full_session=True
                    )
                except ValueError as exc:
                    unavailable.append(
                        {
                            "session_date": current.isoformat(),
                            "reason": f"INCOMPLETE_SESSION: {exc}",
                        }
                    )
                else:
                    if len(bars) != 75:
                        unavailable.append(
                            {
                                "session_date": current.isoformat(),
                                "reason": f"EXPECTED_75_BARS_GOT_{len(bars)}",
                            }
                        )
                    else:
                        _write_cache(path, UNDERLYING, current, candles)
                        valid.append(current)
                        acquired.append(current.isoformat())
                        print(
                            "VALIDATED",
                            current.isoformat(),
                            "1m", len(candles),
                            "5m", len(bars),
                            "total", len(valid),
                            flush=True,
                        )
            current -= timedelta(days=1)
            if args.request_delay > 0:
                time.sleep(args.request_delay)
    finally:
        gateway.close()

    after = sorted(set(valid_cached_sessions(args.cache_root)))
    analysis = after[-args.analysis_sessions:]
    context = after[-required:-args.analysis_sessions]
    status = "PASS" if len(after) >= required else "INCOMPLETE"
    report = {
        "model": "HILEGA_490_SESSION_MATERIALIZATION_V1",
        "status": status,
        "analysis_sessions_requested": args.analysis_sessions,
        "context_sessions_requested": args.context_sessions,
        "valid_sessions_before": len(before),
        "valid_sessions_after": len(after),
        "new_sessions_acquired": len(acquired),
        "analysis_first": analysis[0].isoformat() if analysis else None,
        "analysis_last": analysis[-1].isoformat() if analysis else None,
        "context_first": context[0].isoformat() if context else None,
        "context_last": context[-1].isoformat() if context else None,
        "acquired": acquired,
        "unavailable": unavailable,
        "safety": {
            "existing_cache_overwritten": False,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "valid_sessions_before", "valid_sessions_after",
        "new_sessions_acquired", "analysis_first", "analysis_last",
    )}, indent=2))
    print("Output:", args.report)
    print("Existing cache files and live runtime were untouched.")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
