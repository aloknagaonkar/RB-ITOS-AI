from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
import sqlite3
from time import monotonic
from typing import Any

from .models import (
    DualPcrResearchSnapshot,
    OptionOiCell,
    PcrWindowDefinition,
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
CREATE TABLE IF NOT EXISTS market_trend_research_anchors (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 anchor_timestamp TEXT NOT NULL,
 spot REAL NOT NULL,
 window_json TEXT NOT NULL,
 cells_json TEXT NOT NULL,
 PRIMARY KEY(underlying, trading_date)
);
"""


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(
        f"unsupported research serialization type: {type(value).__name__}"
    )


def _payload(snapshot: DualPcrResearchSnapshot) -> str:
    return json.dumps(
        asdict(snapshot),
        default=_json_value,
        sort_keys=True,
        separators=(",", ":"),
    )


class MarketTrendResearchRepository:
    def __init__(self, database_path: str | Path, *, retention: int = 500) -> None:
        self.path = Path(database_path)
        self.retention = retention

    def persist_once(
        self,
        snapshot: DualPcrResearchSnapshot,
        *,
        evaluation_started: float,
        database_read_ms: float,
        normalization_ms: float,
        calculation_ms: float,
        hard_deadline_ms: float,
    ) -> DualPcrResearchSnapshot:
        """Publish one final record through one SQLite commit.

        The first insert and final timing update occur inside the same uncommitted
        transaction, so no provisional READY projection is externally visible.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        persistence_started = monotonic()
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
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
                    snapshot.source_timestamp.isoformat(),
                    snapshot.evaluated_at.isoformat(),
                    snapshot.quality.state.value,
                    _payload(snapshot),
                ),
            )
            connection.execute(
                """DELETE FROM market_trend_research_snapshots
                   WHERE snapshot_id IN (
                       SELECT snapshot_id
                       FROM market_trend_research_snapshots
                       WHERE underlying=?
                       ORDER BY evaluated_at DESC
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
            final_quality = (
                ResearchDataQuality(
                    final_state,
                    snapshot.quality.source_age_seconds,
                    ("DEADLINE_EXCEEDED",),
                )
                if final_state is ResearchState.TIMEOUT
                else snapshot.quality
            )
            final_snapshot = replace(
                snapshot,
                quality=final_quality,
                latency=ResearchLatencyEvidence(
                    database_read_ms=database_read_ms,
                    normalization_ms=normalization_ms,
                    calculation_ms=calculation_ms,
                    persistence_ms=persistence_ms,
                    end_to_end_ms=end_to_end_ms,
                ),
            )
            connection.execute(
                """UPDATE market_trend_research_snapshots
                   SET state=?, payload_json=?
                   WHERE snapshot_id=?""",
                (
                    final_snapshot.quality.state.value,
                    _payload(final_snapshot),
                    final_snapshot.snapshot_id,
                ),
            )
            connection.commit()
        return final_snapshot

    def persist(self, snapshot: DualPcrResearchSnapshot) -> None:
        """Compatibility helper for tests and explicit repository callers."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_snapshots
                   (snapshot_id, underlying, trading_date, source_timestamp,
                    evaluated_at, state, payload_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.underlying,
                    snapshot.trading_date.isoformat(),
                    snapshot.source_timestamp.isoformat(),
                    snapshot.evaluated_at.isoformat(),
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
                       WHERE underlying=? ORDER BY evaluated_at DESC LIMIT 1""",
                    (underlying,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def create_anchor(
        self,
        *,
        underlying: str,
        trading_date: date,
        anchor_timestamp: datetime,
        spot: float,
        window: PcrWindowDefinition,
        cells: tuple[OptionOiCell, ...],
    ) -> bool:
        window_json = json.dumps(
            asdict(window), default=_json_value, sort_keys=True
        )
        cells_json = json.dumps(
            [asdict(cell) for cell in cells],
            default=_json_value,
            sort_keys=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(_SCHEMA)
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_anchors
                   (underlying, trading_date, anchor_timestamp, spot,
                    window_json, cells_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    underlying,
                    trading_date.isoformat(),
                    anchor_timestamp.isoformat(),
                    spot,
                    window_json,
                    cells_json,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def load_anchor(
        self, *, underlying: str, trading_date: date
    ) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """SELECT anchor_timestamp, spot, window_json, cells_json
                       FROM market_trend_research_anchors
                       WHERE underlying=? AND trading_date=?""",
                    (underlying, trading_date.isoformat()),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        if row is None:
            return None
        return {
            "anchor_timestamp": row[0],
            "spot": row[1],
            "window": json.loads(row[2]),
            "cells": json.loads(row[3]),
        }
