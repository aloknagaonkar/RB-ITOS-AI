from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import time
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.independent_strategy_shadow_worker import (
    IndependentStrategyShadowWorker,
)
from red_bar_lab.execution.process_lock import ProcessLock, WorkerAlreadyRunning
from red_bar_lab.execution.strategy_shadow_comparison import (
    StrategyShadowComparisonService,
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


def _read_latest_jsonl(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            latest = value
    return latest


def _latest_from_directory(root: Path, safe: str) -> dict[str, object] | None:
    direct = root / f"{safe}.jsonl"
    latest = _read_latest_jsonl(direct)
    if latest is not None:
        return latest
    candidates = sorted(root.glob("*.jsonl"), key=lambda path: path.stat().st_mtime)
    for path in reversed(candidates):
        latest = _read_latest_jsonl(path)
        if latest is not None:
            return latest
    return None


def _legacy_red_bar_snapshot(
    database: RedBarDatabase,
    instrument_key: str,
    trading_date: str,
) -> dict[str, object] | None:
    methods = (
        lambda: database.read_signal_attempts(instrument_key, trading_date),
        lambda: database.read_signal_attempts(instrument_key=instrument_key, trading_date=trading_date),
        lambda: database.read_signal_attempts(instrument_key, trading_date, limit=500),
    )
    rows = None
    for method in methods:
        try:
            rows = method()
            break
        except TypeError:
            continue
        except Exception:
            return None
    records = [dict(row) for row in (rows or []) if isinstance(row, Mapping)]
    if not records:
        return None
    latest = max(
        records,
        key=lambda row: str(
            row.get("confirmation_timestamp")
            or row.get("cross_timestamp")
            or row.get("timestamp")
            or ""
        ),
    )
    return {"status": latest.get("state") or latest.get("status"), "latest_attempt": latest}


def build_legacy_snapshot_loader(
    *,
    settings: RedBarSettings,
    database: RedBarDatabase,
    instrument_key: str,
):
    safe = _safe_instrument(instrument_key)

    def load() -> dict[str, object]:
        trading_date = datetime.now(IST).date().isoformat()
        return {
            "red_bar": _legacy_red_bar_snapshot(database, instrument_key, trading_date),
            "directional_regime": _latest_from_directory(
                settings.runs_root / "fresh_setup_bundles_v43", safe
            ),
            "rsi_reversal": _latest_from_directory(
                settings.runs_root / "rsi_extreme_reversal_v1", safe
            ),
        }

    return load


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


def _comparison_status_path(settings: RedBarSettings, instrument_key: str) -> Path:
    return (
        settings.runs_root
        / "independent_strategy_comparison_v1"
        / f"{_safe_instrument(instrument_key)}.status.json"
    )


def _lock_path(settings: RedBarSettings, instrument_key: str) -> Path:
    return (
        settings.runs_root
        / "independent_strategy_shadow_v1"
        / f"{_safe_instrument(instrument_key)}.lock"
    )


def _print_json_file(path: Path, label: str) -> int:
    if not path.exists():
        print(f"No {label} is available at {path}")
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read {label}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, default=str))
    return 0


def print_status(settings: RedBarSettings, instrument_key: str) -> int:
    return _print_json_file(_status_path(settings, instrument_key), "shadow-worker status")


def print_comparison_status(settings: RedBarSettings, instrument_key: str) -> int:
    return _print_json_file(
        _comparison_status_path(settings, instrument_key),
        "strategy-comparison status",
    )


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
    parser.add_argument("--once", action="store_true", help="Evaluate one poll and exit.")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the latest heartbeat/status JSON and exit.",
    )
    parser.add_argument(
        "--comparison-status",
        action="store_true",
        help="Print the latest legacy-versus-shadow comparison JSON and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = RedBarSettings.from_env()
    instrument_key = args.instrument_key or UNDERLYINGS[args.underlying]

    if args.status:
        return print_status(settings, instrument_key)
    if args.comparison_status:
        return print_comparison_status(settings, instrument_key)

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
    comparison = StrategyShadowComparisonService(
        runs_root=settings.runs_root,
        instrument_key=instrument_key,
        legacy_snapshot_loader=build_legacy_snapshot_loader(
            settings=settings,
            database=database,
            instrument_key=instrument_key,
        ),
    )
    lock = ProcessLock(
        _lock_path(settings, instrument_key),
        f"Independent Strategy Shadow Worker [{instrument_key}]",
    )

    print("Independent Strategy Shadow Worker")
    print(f"Instrument: {instrument_key}")
    print(f"Poll interval: {worker.poll_seconds} seconds")
    print(f"Journal: {worker.journal_path}")
    print(f"Heartbeat: {worker.status_path}")
    print(f"Comparison journal: {comparison.journal_path}")
    print(f"Comparison status: {comparison.status_path}")
    print(f"Process lock: {lock.path}")
    print("Mode: SHADOW ONLY — no production persistence, reservation or orders")

    try:
        lock.acquire()
    except WorkerAlreadyRunning as exc:
        print(f"WORKER_ALREADY_RUNNING: {exc}", file=sys.stderr)
        return 3

    try:
        if args.once:
            try:
                result = worker.run_once()
            except Exception as exc:
                worker.write_error_status(exc)
                print(f"Shadow poll failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
            comparison_result = comparison.compare_and_record(result.as_record())
            print(json.dumps(result.as_record(), indent=2, default=str))
            print("Comparison:")
            print(json.dumps(comparison_result, indent=2, default=str))
            return 0

        print("Press Ctrl+C to stop.")
        last_compared_identity = None
        while True:
            try:
                result = worker.run_once()
                if result.scan_identity and result.scan_identity != last_compared_identity:
                    comparison.compare_and_record(result.as_record())
                    last_compared_identity = result.scan_identity
            except Exception as exc:
                worker.write_error_status(exc)
            time.sleep(worker.poll_seconds)
    except KeyboardInterrupt:
        print("\nShadow worker stopped cleanly.")
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "reference_levels_from_rows",
    "build_legacy_snapshot_loader",
    "build_worker",
    "print_status",
    "print_comparison_status",
    "main",
]
