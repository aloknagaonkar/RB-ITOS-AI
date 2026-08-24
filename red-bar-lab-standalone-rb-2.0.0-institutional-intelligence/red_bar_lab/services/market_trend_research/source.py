from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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


@dataclass(frozen=True, slots=True)
class SourceReadResult:
    snapshots: tuple[NormalizedChainSnapshot, ...]
    database_read_ms: float
    normalization_ms: float


class OptionParticipationSnapshotSource:
    """Read normalized option-participation batches; never call a provider."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @staticmethod
    def _snapshot(rows: list[sqlite3.Row]) -> NormalizedChainSnapshot:
        if not rows:
            raise ValueError("EMPTY_SOURCE_BATCH")
        source_timestamp = datetime.fromisoformat(str(rows[0]["observed_at"]))
        if source_timestamp.tzinfo is None or source_timestamp.utcoffset() is None:
            raise ValueError("SOURCE_TIMESTAMP_NAIVE")
        expiry = date.fromisoformat(str(rows[0]["expiry"]))
        spot = float(rows[0]["spot_price"])
        underlying = str(rows[0]["underlying_name"])
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
            underlying=underlying,
            provider="UPSTOX",
            source_timestamp=source_timestamp,
            spot=spot,
            expiry=expiry,
            cells=tuple(cells),
        )

    def recent_with_timings(
        self,
        *,
        underlying: str,
        limit: int = 2,
    ) -> SourceReadResult:
        if type(limit) is not int or limit < 1 or limit > 10:
            raise ValueError("limit invalid")
        if not self.database_path.exists():
            return SourceReadResult((), 0.0, 0.0)

        database_started = monotonic()
        raw_batches: list[list[sqlite3.Row]] = []
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.row_factory = sqlite3.Row
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
                        raw_batches.append(list(rows))
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return SourceReadResult((), 0.0, 0.0)
            raise
        database_read_ms = (monotonic() - database_started) * 1000.0

        normalization_started = monotonic()
        snapshots = tuple(self._snapshot(rows) for rows in raw_batches)
        normalization_ms = (monotonic() - normalization_started) * 1000.0
        return SourceReadResult(snapshots, database_read_ms, normalization_ms)

    def recent(
        self,
        *,
        underlying: str,
        limit: int = 2,
    ) -> tuple[NormalizedChainSnapshot, ...]:
        return self.recent_with_timings(
            underlying=underlying,
            limit=limit,
        ).snapshots

    def latest(self, *, underlying: str) -> NormalizedChainSnapshot | None:
        snapshots = self.recent(underlying=underlying, limit=1)
        return snapshots[0] if snapshots else None
