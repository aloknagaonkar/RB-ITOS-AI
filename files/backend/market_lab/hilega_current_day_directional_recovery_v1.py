from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .domain import HistoricalCandle
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
PRIMARY_SOURCE_STAGE = "UNDERLYING_5M_BUILD"


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


def _same_bar(a: FiveMinuteBar, b: FiveMinuteBar) -> bool:
    return (
        a.ts == b.ts
        and a.open == b.open
        and a.high == b.high
        and a.low == b.low
        and a.close == b.close
        and (a.volume == b.volume or a.volume is None or b.volume is None)
    )


def extract_underlying_5m_from_audit(
    audit_path: str | Path,
    session_date: date,
) -> list[FiveMinuteBar]:
    """Read exact completed 5m OHLC rows already recorded by the original audit."""

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

            if str(record.get("stage")) != PRIMARY_SOURCE_STAGE:
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
                    f"incomplete {PRIMARY_SOURCE_STAGE} OHLC at {ts.isoformat()}"
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
            if old is not None and not _same_bar(old, bar):
                conflicts.append(ts.isoformat())
                continue
            by_ts[ts] = bar

    if conflicts:
        raise ValueError(
            "conflicting duplicate primary live candle evidence: "
            + ",".join(conflicts)
        )

    return [by_ts[k] for k in sorted(by_ts)]


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def extract_underlying_1m_from_market_evidence(
    evidence_path: str | Path,
    session_date: date,
    *,
    underlying: str = UNDERLYING,
) -> list[HistoricalCandle]:
    """Extract exact recorded Nifty 1m candles from an evidence journal.

    The evidence journal contains warmup and repeated market-source responses.
    We do not depend on a particular `kind`. Instead, only embedded objects with
    the canonical HistoricalCandle identity are accepted:
      session_date == target
      instrument_key == underlying
      interval_seconds == 60

    Repeated identical minutes are deduplicated. Conflicting duplicates fail
    closed; no latest-wins policy is allowed.
    """

    path = Path(evidence_path)
    if not path.is_file():
        return []

    by_ts: dict[datetime, HistoricalCandle] = {}
    conflicts: list[str] = []

    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid market evidence JSONL at line {lineno}: {exc}"
                ) from exc

            for obj in _walk_dicts(record.get("response")):
                if obj.get("session_date") != session_date.isoformat():
                    continue
                if obj.get("instrument_key") != underlying:
                    continue
                if int(obj.get("interval_seconds") or 0) != 60:
                    continue

                required = ("timestamp", "open", "high", "low", "close")
                if any(obj.get(k) is None for k in required):
                    raise ValueError(
                        f"incomplete recorded 1m candle in {path} line {lineno}"
                    )

                candle = HistoricalCandle(
                    provider=str(obj.get("provider") or "upstox"),
                    instrument_key=underlying,
                    session_date=session_date,
                    interval_seconds=60,
                    timestamp=_to_dt(obj["timestamp"]),
                    open=float(obj["open"]),
                    high=float(obj["high"]),
                    low=float(obj["low"]),
                    close=float(obj["close"]),
                    volume=(
                        int(obj["volume"])
                        if obj.get("volume") is not None
                        else None
                    ),
                    open_interest=(
                        int(obj["open_interest"])
                        if obj.get("open_interest") is not None
                        else None
                    ),
                )

                ts = candle.timestamp.astimezone(IST).replace(
                    second=0, microsecond=0
                )
                old = by_ts.get(ts)
                if old is not None:
                    old_id = (
                        old.open, old.high, old.low, old.close,
                        old.volume, old.open_interest,
                    )
                    new_id = (
                        candle.open, candle.high, candle.low, candle.close,
                        candle.volume, candle.open_interest,
                    )
                    if old_id != new_id:
                        conflicts.append(ts.isoformat())
                        continue
                by_ts[ts] = candle

    if conflicts:
        raise ValueError(
            "conflicting duplicate 1m market evidence: "
            + ",".join(sorted(set(conflicts)))
        )

    return [by_ts[k] for k in sorted(by_ts)]


def merge_recorded_5m_sources(
    primary_bars: list[FiveMinuteBar],
    supplemental_bars: list[FiveMinuteBar],
) -> tuple[list[FiveMinuteBar], dict[str, int]]:
    """Merge exact recorded sources by timestamp; overlaps must agree."""

    merged: dict[datetime, FiveMinuteBar] = {x.ts: x for x in primary_bars}
    supplemented = 0
    overlap = 0
    conflicts: list[str] = []

    for bar in supplemental_bars:
        old = merged.get(bar.ts)
        if old is None:
            merged[bar.ts] = bar
            supplemented += 1
            continue
        overlap += 1
        if not _same_bar(old, bar):
            conflicts.append(bar.ts.isoformat())

    if conflicts:
        raise ValueError(
            "primary/supplemental 5m evidence conflict: "
            + ",".join(conflicts)
        )

    rows = [merged[k] for k in sorted(merged)]
    return rows, {
        "primary_5m_bars": len(primary_bars),
        "supplemental_5m_bars": len(supplemental_bars),
        "supplemented_missing_5m_bars": supplemented,
        "agreeing_overlap_5m_bars": overlap,
        "merged_5m_bars": len(rows),
    }


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
    supplemental_evidence: str | Path | None = None,
    output_root: str | Path = "data/historical-evidence/hilega-directional-replay-v1",
    cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
    warmup_calendar_days: int = 45,
    force: bool = False,
) -> dict[str, Any]:
    source_audit = Path(source_audit)
    if supplemental_evidence is None:
        supplemental_evidence = (
            Path("data/live-observation/hilega-directional-market-evidence-v1")
            / f"{session_date.isoformat()}.jsonl"
        )
    supplemental_evidence = Path(supplemental_evidence)

    output_root = Path(output_root)
    session_dir = output_root / session_date.isoformat()
    json_path = session_dir / "directional-candle-by-candle.json"
    csv_path = session_dir / "directional-candle-by-candle.csv"
    manifest_path = session_dir / "current-day-recovery-manifest.json"

    if json_path.exists() and not force:
        raise FileExistsError(
            f"{json_path} already exists; use --force only after deliberate review"
        )

    primary_bars = extract_underlying_5m_from_audit(source_audit, session_date)
    if not primary_bars:
        raise RuntimeError(
            f"NO_RECORDED_{PRIMARY_SOURCE_STAGE}_BARS_FOR_{session_date.isoformat()}"
        )

    supplemental_1m = extract_underlying_1m_from_market_evidence(
        supplemental_evidence,
        session_date,
    )
    supplemental_5m = (
        aggregate_exact_5m(supplemental_1m, session_date)
        if supplemental_1m
        else []
    )

    bars, source_counts = merge_recorded_5m_sources(
        primary_bars, supplemental_5m
    )

    coordinator = HilegaDirectionalCoordinatorV1()
    warmup = _warm_from_cache(
        coordinator,
        target_date=session_date,
        cache_root=cache_root,
        warmup_calendar_days=warmup_calendar_days,
    )

    rows: list[dict[str, Any]] = []
    primary_ts = {x.ts for x in primary_bars}
    supplemental_ts = {x.ts for x in supplemental_5m}

    for bar in bars:
        decision = coordinator.on_bar(bar)
        row = _row_from_decision(bar, decision, coordinator)
        row["reconstructed"] = True
        if bar.ts in primary_ts and bar.ts in supplemental_ts:
            row["recovery_source"] = "RECORDED_PRIMARY_AND_MARKET_EVIDENCE"
        elif bar.ts in supplemental_ts:
            row["recovery_source"] = "RECORDED_DIRECTIONAL_MARKET_EVIDENCE_1M"
        else:
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
        "supplemental_evidence": str(supplemental_evidence),
        "supplemental_evidence_present": supplemental_evidence.is_file(),
        "supplemental_evidence_sha256": (
            _sha256(supplemental_evidence)
            if supplemental_evidence.is_file()
            else None
        ),
        "supplemental_1m_candles": len(supplemental_1m),
        **source_counts,
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
