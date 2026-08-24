from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from time import monotonic
from typing import Any

from .models import (
    DualPcrResearchSnapshot,
    MorningReference,
    OpeningOiBaseline,
    OptionOiCell,
    ResearchDataQuality,
    ResearchLatencyEvidence,
    ResearchState,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_trend_research_snapshots (
 snapshot_id TEXT PRIMARY KEY,
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 evaluated_at TEXT NOT NULL,
 state TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_trend_research_latest
ON market_trend_research_snapshots(underlying, trading_date, evaluated_at DESC);
CREATE TABLE IF NOT EXISTS market_trend_research_references (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 reference_timestamp TEXT NOT NULL,
 expiry TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 PRIMARY KEY(underlying, trading_date)
);
CREATE TABLE IF NOT EXISTS market_trend_research_oi_baselines (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 baseline_timestamp TEXT NOT NULL,
 expiry TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 PRIMARY KEY(underlying, trading_date)
);
CREATE TABLE IF NOT EXISTS market_trend_research_source_snapshots (
 snapshot_key TEXT PRIMARY KEY,
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 expiry TEXT NOT NULL,
 provider TEXT NOT NULL,
 spot REAL NOT NULL,
 request_ms REAL NOT NULL,
 normalization_ms REAL NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_trend_research_source_latest
ON market_trend_research_source_snapshots(underlying, trading_date, source_timestamp DESC);
CREATE TABLE IF NOT EXISTS market_trend_research_runtime_health (
 runtime_name TEXT PRIMARY KEY,
 heartbeat_at TEXT NOT NULL,
 last_success_at TEXT,
 last_failure_at TEXT,
 last_failure_reason TEXT,
 consecutive_failures INTEGER NOT NULL,
 dropped_obsolete_tasks INTEGER NOT NULL,
 payload_json TEXT NOT NULL
);
"""


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"unsupported research serialization type: {type(value).__name__}")


def _json(value: object) -> str:
    return json.dumps(value, default=_json_value, sort_keys=True, separators=(",", ":"))


def _payload(snapshot: DualPcrResearchSnapshot) -> str:
    return _json(asdict(snapshot))


def _utc_iso(value: datetime, *, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


class MarketTrendResearchRepository:
    def __init__(self, database_path: str | Path, *, retention: int = 500) -> None:
        self.path = Path(database_path)
        self.retention = retention

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(_SCHEMA)
        return connection

    def persist_once(
        self,
        snapshot: DualPcrResearchSnapshot,
        *,
        evaluation_started: float,
        database_read_ms: float,
        normalization_ms: float,
        calculation_ms: float,
        hard_deadline_ms: float,
        provider_request_ms: float = 0.0,
        dropped_obsolete_tasks: int = 0,
        consecutive_failures: int = 0,
    ) -> DualPcrResearchSnapshot:
        """Publish one externally visible record through one SQLite commit."""
        source_timestamp = _utc_iso(
            snapshot.source_timestamp,
            field_name="source_timestamp",
        )
        evaluated_at = _utc_iso(snapshot.evaluated_at, field_name="evaluated_at")
        persistence_started = monotonic()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_snapshots
                   (snapshot_id, underlying, trading_date, source_timestamp,
                    evaluated_at, state, payload_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.underlying,
                    snapshot.trading_date.isoformat(),
                    source_timestamp,
                    evaluated_at,
                    snapshot.quality.state.value,
                    _payload(snapshot),
                ),
            )
            connection.execute(
                """DELETE FROM market_trend_research_snapshots
                   WHERE snapshot_id IN (
                     SELECT snapshot_id FROM market_trend_research_snapshots
                     WHERE underlying=?
                     ORDER BY julianday(evaluated_at) DESC, evaluated_at DESC
                     LIMIT -1 OFFSET ?
                   )""",
                (snapshot.underlying, self.retention),
            )
            persistence_ms = (monotonic() - persistence_started) * 1000.0
            end_to_end_ms = (monotonic() - evaluation_started) * 1000.0
            final_state = (
                ResearchState.TIMEOUT
                if end_to_end_ms > hard_deadline_ms
                else snapshot.quality.state
            )
            quality = (
                ResearchDataQuality(
                    ResearchState.TIMEOUT,
                    snapshot.quality.source_age_seconds,
                    ("DEADLINE_EXCEEDED",),
                )
                if final_state is ResearchState.TIMEOUT
                else snapshot.quality
            )
            final_snapshot = replace(
                snapshot,
                quality=quality,
                latency=ResearchLatencyEvidence(
                    database_read_ms=database_read_ms,
                    normalization_ms=normalization_ms,
                    calculation_ms=calculation_ms,
                    persistence_ms=persistence_ms,
                    end_to_end_ms=end_to_end_ms,
                    provider_request_ms=provider_request_ms,
                    dropped_obsolete_tasks=dropped_obsolete_tasks,
                    consecutive_failures=consecutive_failures,
                ),
            )
            connection.execute(
                """UPDATE market_trend_research_snapshots
                   SET state=?, payload_json=? WHERE snapshot_id=?""",
                (
                    final_snapshot.quality.state.value,
                    _payload(final_snapshot),
                    final_snapshot.snapshot_id,
                ),
            )
            connection.commit()
        return final_snapshot

    def persist(self, snapshot: DualPcrResearchSnapshot) -> None:
        source_timestamp = _utc_iso(
            snapshot.source_timestamp,
            field_name="source_timestamp",
        )
        evaluated_at = _utc_iso(snapshot.evaluated_at, field_name="evaluated_at")
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_snapshots
                   (snapshot_id, underlying, trading_date, source_timestamp,
                    evaluated_at, state, payload_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.underlying,
                    snapshot.trading_date.isoformat(),
                    source_timestamp,
                    evaluated_at,
                    snapshot.quality.state.value,
                    _payload(snapshot),
                ),
            )
            connection.commit()

    def latest_projection(self, *, underlying: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """SELECT payload_json FROM market_trend_research_snapshots
                       WHERE underlying=?
                       ORDER BY julianday(evaluated_at) DESC, evaluated_at DESC
                       LIMIT 1""",
                    (underlying,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def create_reference(self, reference: MorningReference) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_references
                   (underlying, trading_date, reference_timestamp, expiry, payload_json)
                   VALUES (?,?,?,?,?)""",
                (
                    reference.underlying,
                    reference.trading_date.isoformat(),
                    reference.reference_timestamp.isoformat(),
                    reference.expiry.isoformat(),
                    _json(asdict(reference)),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def load_reference(self, *, underlying: str, trading_date: date) -> dict[str, Any] | None:
        return self._load_daily(
            table="market_trend_research_references",
            underlying=underlying,
            trading_date=trading_date,
        )

    def create_oi_baseline(self, baseline: OpeningOiBaseline) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_oi_baselines
                   (underlying, trading_date, baseline_timestamp, expiry, payload_json)
                   VALUES (?,?,?,?,?)""",
                (
                    baseline.underlying,
                    baseline.trading_date.isoformat(),
                    baseline.baseline_timestamp.isoformat(),
                    baseline.expiry.isoformat(),
                    _json(asdict(baseline)),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def load_oi_baseline(self, *, underlying: str, trading_date: date) -> dict[str, Any] | None:
        return self._load_daily(
            table="market_trend_research_oi_baselines",
            underlying=underlying,
            trading_date=trading_date,
        )

    def _load_daily(self, *, table: str, underlying: str, trading_date: date) -> dict[str, Any] | None:
        if table not in {
            "market_trend_research_references",
            "market_trend_research_oi_baselines",
        }:
            raise ValueError("unsupported research table")
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    f"SELECT payload_json FROM {table} WHERE underlying=? AND trading_date=?",
                    (underlying, trading_date.isoformat()),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def persist_source_snapshot(
        self,
        *,
        snapshot_key: str,
        underlying: str,
        trading_date: date,
        source_timestamp: datetime,
        expiry: date,
        provider: str,
        spot: float,
        cells: tuple[OptionOiCell, ...],
        request_ms: float,
        normalization_ms: float,
    ) -> None:
        payload = {
            "underlying": underlying,
            "provider": provider,
            "source_timestamp": source_timestamp,
            "spot": spot,
            "expiry": expiry,
            "cells": [asdict(cell) for cell in cells],
            "request_ms": request_ms,
            "normalization_ms": normalization_ms,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_source_snapshots
                   (snapshot_key, underlying, trading_date, source_timestamp, expiry,
                    provider, spot, request_ms, normalization_ms, payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot_key,
                    underlying,
                    trading_date.isoformat(),
                    source_timestamp.isoformat(),
                    expiry.isoformat(),
                    provider,
                    spot,
                    request_ms,
                    normalization_ms,
                    _json(payload),
                ),
            )
            connection.execute(
                """DELETE FROM market_trend_research_source_snapshots
                   WHERE snapshot_key IN (
                     SELECT snapshot_key FROM market_trend_research_source_snapshots
                     WHERE underlying=? ORDER BY source_timestamp DESC
                     LIMIT -1 OFFSET ?
                   )""",
                (underlying, self.retention),
            )
            connection.commit()

    def recent_source_payloads(self, *, underlying: str, limit: int = 2) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        try:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """SELECT payload_json FROM market_trend_research_source_snapshots
                       WHERE underlying=? ORDER BY source_timestamp DESC LIMIT ?""",
                    (underlying, limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return ()
            raise
        return tuple(json.loads(row[0]) for row in rows)

    def persist_runtime_health(
        self,
        *,
        runtime_name: str,
        heartbeat_at: datetime,
        last_success_at: datetime | None,
        last_failure_at: datetime | None,
        last_failure_reason: str | None,
        consecutive_failures: int,
        dropped_obsolete_tasks: int,
    ) -> None:
        payload = {
            "runtime_name": runtime_name,
            "heartbeat_at": heartbeat_at,
            "last_success_at": last_success_at,
            "last_failure_at": last_failure_at,
            "last_failure_reason": last_failure_reason,
            "consecutive_failures": consecutive_failures,
            "dropped_obsolete_tasks": dropped_obsolete_tasks,
        }
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_runtime_health
                   (runtime_name, heartbeat_at, last_success_at, last_failure_at,
                    last_failure_reason, consecutive_failures,
                    dropped_obsolete_tasks, payload_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    runtime_name,
                    heartbeat_at.isoformat(),
                    None if last_success_at is None else last_success_at.isoformat(),
                    None if last_failure_at is None else last_failure_at.isoformat(),
                    last_failure_reason,
                    consecutive_failures,
                    dropped_obsolete_tasks,
                    _json(payload),
                ),
            )
            connection.commit()

    def latest_runtime_health(self, *, runtime_name: str = "MARKET_TREND_RESEARCH") -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """SELECT payload_json FROM market_trend_research_runtime_health
                       WHERE runtime_name=?""",
                    (runtime_name,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def create_anchor(self, **_: object) -> bool:
        raise ValueError("MORNING_ANCHOR_REPLACED_BY_SPLIT_LIFECYCLE")

    def load_anchor(self, **_: object) -> None:
        return None
