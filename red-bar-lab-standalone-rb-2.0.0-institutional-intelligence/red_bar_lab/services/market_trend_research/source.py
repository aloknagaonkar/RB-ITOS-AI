from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
from time import monotonic

from .models import OptionOiCell


@dataclass(frozen=True, slots=True)
class NormalizedChainSnapshot:
    underlying: str
    provider: str
    source_timestamp: datetime
    spot: float
    expiry: date
    cells: tuple[OptionOiCell, ...]
    provider_request_ms: float = 0.0
    normalization_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class SourceReadResult:
    snapshots: tuple[NormalizedChainSnapshot, ...]
    database_read_ms: float
    normalization_ms: float


class OptionParticipationSnapshotSource:
    """Read isolated research snapshots, falling back to 10A evidence only."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @staticmethod
    def _aware(value: object) -> datetime:
        result = datetime.fromisoformat(str(value))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("SOURCE_TIMESTAMP_NAIVE")
        return result

    @classmethod
    def _research_snapshot(cls, payload: dict[str, object]) -> NormalizedChainSnapshot:
        source_timestamp = cls._aware(payload["source_timestamp"])
        expiry = date.fromisoformat(str(payload["expiry"]))
        cells = tuple(
            OptionOiCell(
                instrument_key=str(item["instrument_key"]),
                option_side=str(item["option_side"]),
                strike=float(item["strike"]),
                expiry=date.fromisoformat(str(item["expiry"])),
                current_oi=float(item["current_oi"]),
                provider_prev_oi=(
                    None
                    if item.get("provider_prev_oi") is None
                    else float(item["provider_prev_oi"])
                ),
                source_timestamp=cls._aware(item["source_timestamp"]),
            )
            for item in payload.get("cells", [])
        )
        return NormalizedChainSnapshot(
            underlying=str(payload["underlying"]),
            provider=str(payload.get("provider") or "UPSTOX"),
            source_timestamp=source_timestamp,
            spot=float(payload["spot"]),
            expiry=expiry,
            cells=cells,
            provider_request_ms=float(payload.get("request_ms") or 0.0),
            normalization_ms=float(payload.get("normalization_ms") or 0.0),
        )

    @classmethod
    def _legacy_snapshot(cls, rows: list[sqlite3.Row]) -> NormalizedChainSnapshot:
        if not rows:
            raise ValueError("EMPTY_SOURCE_BATCH")
        source_timestamp = cls._aware(rows[0]["observed_at"])
        expiry = date.fromisoformat(str(rows[0]["expiry"]))
        cells: list[OptionOiCell] = []
        for row in rows:
            if row["instrument_key"] is None or row["strike"] is None or row["oi"] is None:
                continue
            cells.append(
                OptionOiCell(
                    instrument_key=str(row["instrument_key"]),
                    option_side=str(row["option_type"]),
                    strike=float(row["strike"]),
                    expiry=expiry,
                    current_oi=float(row["oi"]),
                    provider_prev_oi=(
                        None if row["prev_oi"] is None else float(row["prev_oi"])
                    ),
                    source_timestamp=source_timestamp,
                )
            )
        return NormalizedChainSnapshot(
            underlying=str(rows[0]["underlying_name"]),
            provider="UPSTOX",
            source_timestamp=source_timestamp,
            spot=float(rows[0]["spot_price"]),
            expiry=expiry,
            cells=tuple(cells),
        )

    def recent_with_timings(
        self,
        *,
        underlying: str,
        limit: int = 2,
    ) -> SourceReadResult:
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("limit invalid")
        if not self.database_path.exists():
            return SourceReadResult((), 0.0, 0.0)
        database_started = monotonic()
        research_payloads: list[dict[str, object]] = []
        legacy_batches: list[list[sqlite3.Row]] = []
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.row_factory = sqlite3.Row
                try:
                    research_rows = connection.execute(
                        """SELECT payload_json
                           FROM market_trend_research_source_snapshots
                           WHERE underlying=?
                           ORDER BY source_timestamp DESC LIMIT ?""",
                        (underlying, limit),
                    ).fetchall()
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
                    research_rows = []
                research_payloads = [json.loads(row["payload_json"]) for row in research_rows]
                if not research_payloads:
                    stamps = connection.execute(
                        """SELECT DISTINCT observed_at
                           FROM option_participation_snapshots
                           WHERE underlying_name=?
                           ORDER BY julianday(observed_at) DESC, observed_at DESC
                           LIMIT ?""",
                        (underlying, limit),
                    ).fetchall()
                    for stamp in stamps:
                        rows = connection.execute(
                            """SELECT observed_at, underlying_name, spot_price, expiry,
                                      option_type, instrument_key, strike, oi, prev_oi
                               FROM option_participation_snapshots
                               WHERE underlying_name=? AND observed_at=?
                               ORDER BY strike, option_type""",
                            (underlying, stamp["observed_at"]),
                        ).fetchall()
                        if rows:
                            legacy_batches.append(list(rows))
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return SourceReadResult((), 0.0, 0.0)
            raise
        database_read_ms = (monotonic() - database_started) * 1000.0
        normalization_started = monotonic()
        snapshots = (
            tuple(self._research_snapshot(payload) for payload in research_payloads)
            if research_payloads
            else tuple(self._legacy_snapshot(rows) for rows in legacy_batches)
        )
        normalization_ms = (monotonic() - normalization_started) * 1000.0
        return SourceReadResult(snapshots, database_read_ms, normalization_ms)

    def recent(self, *, underlying: str, limit: int = 2) -> tuple[NormalizedChainSnapshot, ...]:
        return self.recent_with_timings(underlying=underlying, limit=limit).snapshots

    def latest(self, *, underlying: str) -> NormalizedChainSnapshot | None:
        snapshots = self.recent(underlying=underlying, limit=1)
        return snapshots[0] if snapshots else None
