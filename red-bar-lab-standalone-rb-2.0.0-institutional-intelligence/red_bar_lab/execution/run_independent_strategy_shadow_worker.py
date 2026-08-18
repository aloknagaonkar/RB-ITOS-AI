from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.independent_strategy_shadow_worker import (
    IndependentStrategyShadowWorker,
)
from red_bar_lab.services.stateful_regime_store import StatefulRegimeStore
from red_bar_lab.services.upstox_service import (
    MissingAccessToken,
    RedBarUpstoxService,
    resolve_access_token,
)
from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.strategy.models import ReferenceLevel


IST = ZoneInfo("Asia/Kolkata")


def _safe_instrument(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(value)
    )
    return safe.strip("_") or "UNKNOWN"


def _as_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(IST)
    else:
        timestamp = timestamp.tz_convert(IST)
    return timestamp.to_pydatetime()


def reference_levels_from_rows(
    rows: Iterable[Mapping[str, object]],
) -> tuple[ReferenceLevel, ...]:
    """Convert existing database rows without changing Red Bar level policy."""
    levels: list[ReferenceLevel] = []
    for raw in rows:
        row = dict(raw)
        level_type = str(row.get("level_type") or row.get("type") or "").strip()
        value = row.get("level_value", row.get("value"))
        source_timestamp = row.get("source_timestamp") or row.get("timestamp")
        if not level_type or value in (None, "") or source_timestamp in (None, ""):
            continue
        try:
            levels.append(
                ReferenceLevel(
                    level_type=level_type,
                    value=float(value),
                    source_timestamp=_as_datetime(source_timestamp),
                    source_high=float(row.get("source_high") or row.get("high") or value),
                    source_low=float(row.get("source_low") or row.get("low") or value),
                    interval_minutes=int(row.get("interval_minutes") or row.get("interval") or 5),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(levels)


def build_worker(
    *,
    settings: RedBarSettings,
    provider: RedBarUpstoxService,
    database: RedBarDatabase,
    instrument_key: str,
    poll_seconds: int,
    lookback_days: int = 7,
) -> IndependentStrategyShadowWorker:
    safe = _safe_instrument(instrument_key)

    def load_candles() -> pd.DataFrame:
        now = datetime.now(IST)
        frames: list[pd.DataFrame] = []
        try:
            history = provider.historical_candles(
                instrument_key,
                now.date() - timedelta(days=max(2, lookback_days)),
                now.date() - timedelta(days=1),
                interval_minutes=1,
            )
            if history is not None and not history.empty:
                frames.append(history)
        except Exception:
            pass
        intraday = provider.intraday_candles(
            instrument_key,
            interval_minutes=1,
        )
        if intraday is not None and not intraday.empty:
            frames.append(intraday)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def load_reference_levels() -> tuple[ReferenceLevel, ...]:
        today = datetime.now(IST).date().isoformat()
        rows = database.read_reference_levels(instrument_key, today) or []
        return reference_levels_from_rows(rows)

    regime_store = StatefulRegimeStore(
        settings.runs_root / "stateful_regime_v43" / f"{safe}.jsonl"
    )

    return IndependentStrategyShadowWorker(
        candle_loader=load_candles,
        reference_level_loader=load_reference_levels,
        previous_regime_loader=regime_store.latest,
        instrument_key=instrument_key,
        runs_root=settings.runs_root,
        poll_seconds=poll_seconds,
    )


def _status_path(settings: RedBarSettings, instrument_key: str) -> Path:
    return (
        settings.runs_root
        / "independent_strategy_shadow_v1"
        / f"{_safe_instrument(instrument_key)}.status.json"
    )


def print_status(settings: RedBarSettings, instrument_key: str) -> int:
    path = _status_path(settings, instrument_key)
    if not path.exists():
        print(f"No shadow-worker status is available at {path}")
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read shadow-worker status: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run independent Red Bar, DRI and RSI evaluation in shadow-only mode. "
            "No production signal, bundle, capital or order state is written."
        )
    )
    parser.add_argument(
        "--underlying",
        choices=tuple(UNDERLYINGS),
        default="NIFTY 50",
        help="Configured underlying name.",
    )
    parser.add_argument(
        "--instrument-key",
        default=None,
        help="Explicit instrument key; overrides --underlying.",
    )
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Evaluate one poll and exit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the latest heartbeat/status JSON and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = RedBarSettings.from_env()
    instrument_key = args.instrument_key or UNDERLYINGS[args.underlying]

    if args.status:
        return print_status(settings, instrument_key)

    try:
        token = resolve_access_token("")
    except MissingAccessToken as exc:
        print(str(exc), file=sys.stderr)
        return 2

    database = RedBarDatabase(settings.database_path)
    database.initialize()
    worker = build_worker(
        settings=settings,
        provider=RedBarUpstoxService(token),
        database=database,
        instrument_key=instrument_key,
        poll_seconds=max(1, args.poll_seconds),
        lookback_days=max(2, args.lookback_days),
    )

    print("Independent Strategy Shadow Worker")
    print(f"Instrument: {instrument_key}")
    print(f"Poll interval: {worker.poll_seconds} seconds")
    print(f"Journal: {worker.journal_path}")
    print(f"Heartbeat: {worker.status_path}")
    print("Mode: SHADOW ONLY — no production persistence, reservation or orders")

    if args.once:
        try:
            result = worker.run_once()
        except Exception as exc:
            worker.write_error_status(exc)
            print(f"Shadow poll failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result.as_record(), indent=2, default=str))
        return 0

    print("Press Ctrl+C to stop.")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        print("\nShadow worker stopped cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "reference_levels_from_rows",
    "build_worker",
    "print_status",
    "main",
]
