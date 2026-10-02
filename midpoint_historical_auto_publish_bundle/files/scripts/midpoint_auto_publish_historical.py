#!/usr/bin/env python3
"""Publish completed Midpoint live-audit sessions into Historical Replay.

Only sessions strictly earlier than today's IST date are eligible.  The
canonical append script remains responsible for exact 360-minute validation,
audit parity, immutable session directories, and atomic manifest publication.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from market_lab.domain import IST
from market_lab.midpoint_strategy.replay import load_audit_jsonl


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data/live-observation/midpoint-strategy-v1/audit.jsonl"
REPLAY_ROOT = ROOT / (
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)
MANIFEST = REPLAY_ROOT / "manifest.json"
MATERIALIZER = ROOT / "scripts/midpoint_append_live_dates_to_replay.py"
LOCK = ROOT / "data/runtime/midpoint-historical-publisher.lock"


def _row_day(row: dict[str, Any]) -> str | None:
    for key in ("session_date", "event_timestamp", "source_candle_timestamp"):
        value = str(row.get(key) or "")
        if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
            return value[:10]
    return None


def eligible_missing_dates(
    audit_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    now: datetime,
) -> list[str]:
    """Return prior audited sessions absent from both manifest and disk."""
    today = now.astimezone(IST).date().isoformat()
    audited = {day for row in audit_rows if (day := _row_day(row)) and day < today}
    published = {
        str(row.get("session_date"))
        for row in manifest.get("sessions", [])
        if row.get("session_date")
    }
    return sorted(
        day
        for day in audited - published
        if not (REPLAY_ROOT / day).exists()
    )


def publish_once(*, python: str = sys.executable) -> list[str]:
    if not AUDIT.exists():
        print(f"WAIT: live audit unavailable: {AUDIT}", flush=True)
        return []
    if not MANIFEST.exists():
        print(f"WAIT: historical manifest unavailable: {MANIFEST}", flush=True)
        return []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    days = eligible_missing_dates(
        load_audit_jsonl(AUDIT), manifest, now=datetime.now(IST)
    )
    if not days:
        print("NOOP: no completed audited session awaiting publication", flush=True)
        return []

    command = [
        python,
        str(MATERIALIZER),
        "--dates",
        *days,
        "--accept-revised-candles",
    ]
    print("PUBLISHING:", ", ".join(days), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    return days


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one publication check and exit",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=900,
        help="Daemon polling interval; default 900 seconds",
    )
    args = parser.parse_args()
    if args.interval_seconds < 60:
        raise SystemExit("STOP: interval must be at least 60 seconds")

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(LOCK), timeout=1):
            while True:
                try:
                    publish_once(python=sys.executable)
                except Exception as exc:
                    print(
                        f"RETRY: publication failed: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    if args.once:
                        return 1
                if args.once:
                    return 0
                time.sleep(args.interval_seconds)
    except Timeout:
        print("NOOP: another historical publisher owns the lock", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
