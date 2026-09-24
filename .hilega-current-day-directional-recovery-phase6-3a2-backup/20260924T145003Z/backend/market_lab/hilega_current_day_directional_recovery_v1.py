from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .hilega_directional_coordinator_v1 import HilegaDirectionalCoordinatorV1
from .hilega_directional_historical_replay_v1 import _row_from_decision
from .hilega_milega_historical_replay_v1 import (
    UNDERLYING,
    aggregate_exact_5m,
    load_or_fetch_1m,
)
from .hilega_milega_strategy_v1 import FiveMinuteBar

IST = ZoneInfo("Asia/Kolkata")
MODEL = "HILEGA_CURRENT_DAY_DIRECTIONAL_RECOVERY_V1"
SOURCE_STAGE = "UNDERLYING_5M_BUILD"


class CacheOnlyHistoricalGateway:
    """Fail closed if warmup data is not already cached."""

    def historical_candles(self, instrument_key: str, session_date: date):
        raise RuntimeError(
            f"CACHE_ONLY_WARMUP_MISS:{instrument_key}:{session_date.isoformat()}"
        )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value}")
    return dt.astimezone(IST)


def extract_underlying_5m_from_audit(
    audit_path: str | Path,
    session_date: date,
) -> list[FiveMinuteBar]:
    """Read exact completed 5m OHLC rows already recorded by the live audit.

    No OHLC is synthesized. Duplicate timestamps are accepted only when every
    recorded OHLC value is identical.
    """

    path = Path(audit_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    by_ts: dict[datetime, FiveMinuteBar] = {}
    conflicts: list[str] = []

    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {lineno}: {exc}") from exc

            if str(record.get("stage")) != SOURCE_STAGE:
                continue

            payload = record.get("payload") or {}
            raw_ts = payload.get("bar_timestamp")
            if not raw_ts:
                continue

            ts = _to_dt(raw_ts).replace(second=0, microsecond=0)
            if ts.date() != session_date:
                continue

            required = ("open", "high", "low", "close")
            if any(payload.get(k) is None for k in required):
                raise ValueError(
                    f"incomplete {SOURCE_STAGE} OHLC at {ts.isoformat()}"
                )

            bar = FiveMinuteBar(
                ts=ts,
                open=float(payload["open"]),
                high=float(payload["high"]),
                low=float(payload["low"]),
                close=float(payload["close"]),
                volume=(
                    int(payload["volume"])
                    if payload.get("volume") is not None
                    else None
                ),
            )

            old = by_ts.get(ts)
            if old is not None and old != bar:
                conflicts.append(ts.isoformat())
                continue
            by_ts[ts] = bar

    if conflicts:
        raise ValueError(
            "conflicting duplicate live candle evidence: " + ",".join(conflicts)
        )

    return [by_ts[k] for k in sorted(by_ts)]


def _warm_from_cache(
    coordinator: HilegaDirectionalCoordinatorV1,
    *,
    target_date: date,
    cache_root: str | Path,
    warmup_calendar_days: int,
) -> dict[str, Any]:
    gateway = CacheOnlyHistoricalGateway()
    start = target_date - timedelta(days=warmup_calendar_days)
    d = start
    loaded_sessions = 0
    loaded_bars = 0
    cache_misses: list[str] = []

    while d < target_date:
        try:
            candles = load_or_fetch_1m(
                gateway,
                underlying=UNDERLYING,
                session_date=d,
                cache_root=cache_root,
                refresh_cache=False,
            )
        except RuntimeError as exc:
            if str(exc).startswith("CACHE_ONLY_WARMUP_MISS:"):
                cache_misses.append(d.isoformat())
                d += timedelta(days=1)
                continue
            raise

        if candles:
            bars = aggregate_exact_5m(candles, d)
            for bar in bars:
                coordinator.bullish.indicators.update(bar.close)
                coordinator.bearish.indicators.update(bar.close)
            loaded_sessions += 1
            loaded_bars += len(bars)

            # Match the historical replay warmup semantics: indicator history is
            # retained, but session-to-session comparison state is not.
            coordinator.bullish.previous_indicators = None
            coordinator.bullish.previous_bar = None
            coordinator.bearish.previous_indicators = None
            coordinator.bearish.previous_bar = None

        d += timedelta(days=1)

    if loaded_sessions == 0:
        raise RuntimeError("NO_CACHED_WARMUP_SESSIONS_AVAILABLE")

    return {
        "warmup_sessions_loaded": loaded_sessions,
        "warmup_5m_bars_loaded": loaded_bars,
        "warmup_cache_misses": cache_misses,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def recover_current_day_directional_timeline(
    *,
    session_date: date,
    source_audit: str | Path = "data/live-observation/hilega-milega-v1/step-audit.jsonl",
    output_root: str | Path = "data/historical-evidence/hilega-directional-replay-v1",
    cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
    warmup_calendar_days: int = 45,
    force: bool = False,
) -> dict[str, Any]:
    source_audit = Path(source_audit)
    output_root = Path(output_root)
    session_dir = output_root / session_date.isoformat()
    json_path = session_dir / "directional-candle-by-candle.json"
    csv_path = session_dir / "directional-candle-by-candle.csv"
    manifest_path = session_dir / "current-day-recovery-manifest.json"

    if json_path.exists() and not force:
        raise FileExistsError(
            f"{json_path} already exists; use --force only after deliberate review"
        )

    bars = extract_underlying_5m_from_audit(source_audit, session_date)
    if not bars:
        raise RuntimeError(
            f"NO_RECORDED_{SOURCE_STAGE}_BARS_FOR_{session_date.isoformat()}"
        )

    coordinator = HilegaDirectionalCoordinatorV1()
    warmup = _warm_from_cache(
        coordinator,
        target_date=session_date,
        cache_root=cache_root,
        warmup_calendar_days=warmup_calendar_days,
    )

    rows: list[dict[str, Any]] = []
    for bar in bars:
        decision = coordinator.on_bar(bar)
        row = _row_from_decision(bar, decision, coordinator)
        row["reconstructed"] = True
        row["recovery_source"] = "RECORDED_LIVE_UNDERLYING_5M_BUILD"
        rows.append(row)

    session_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(rows, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, rows)

    manifest = {
        "model": MODEL,
        "status": "PASS",
        "session_date": session_date.isoformat(),
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "source_audit": str(source_audit),
        "source_audit_sha256": _sha256(source_audit),
        "source_stage": SOURCE_STAGE,
        "source_5m_bars": len(bars),
        "recovered_directional_rows": len(rows),
        "first_bar": rows[0]["bar_timestamp"] if rows else None,
        "last_bar": rows[-1]["bar_timestamp"] if rows else None,
        "output_json": str(json_path),
        "output_csv": str(csv_path),
        **warmup,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
